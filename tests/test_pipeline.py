"""Tests for the DB/DES slot pipeline in `pipeline`.

`pipeline` is the loop the Streamlit app used to run itself and the Vue
frontend cannot run: build the first-turn prompt, submit it, validate the reply
with `sql_runner` / `des_runner`, and re-submit with the validation report until
the artifact passes or the attempts run out. The agent is injected as a
synchronous `submit`, so these tests drive the whole loop with a scripted reply
— no HTTP broker, no LLM, no database, and (because `des_runner.verify` is the
seam that runs the program) no interpreter with simpy.

What is pinned here:

* the repair loop — a broken reply followed by a valid one is repaired, both
  turns are recorded, and the artifact that comes back is the valid one;
* the prompts — the first turn is `make_db_prompt` / `make_gen_des` and every
  later turn is `make_db_repair` / `make_gen_des_repair` carrying the report, so
  the loop cannot drift from the prompt module the rest of the repo uses;
* the requirements normalisation — a result the client stored as raw JSON text
  is decoded for both the prompt and the DES semantic bounds, and a result that
  does not parse disables the bounds instead of crashing the slot;
* the stop conditions — a `submit` that returns None (failed or timed-out turn)
  stops the loop with no artifact, and a slot that never passes returns its last
  artifact with the verdict that rejected it.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "digital_twin_builder"))

import des_runner  # noqa: E402
import pipeline  # noqa: E402
from prompts import user as user_prompts  # noqa: E402


SCHEMA = """CREATE TABLE machines (
    machine_id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE events (
    ts timestamptz NOT NULL,
    machine_id text REFERENCES machines(machine_id),
    duration_s double precision
);

CREATE INDEX events_machine_ts_idx ON events (machine_id, ts);

CREATE VIEW event_counts AS
    SELECT machine_id, count(*) AS n FROM events GROUP BY machine_id;
"""

# A reply that is valid JSON and not SQL — the shape the harness recorded from a
# live run, where a JSON object lifted out of an INSERT was stored as a schema.
BROKEN_SQL = '{"длина": "100 мм", "ширина": "50 мм"}'

REQ = {
    "production_type": "serial line",
    "line": {
        "topology": "serial",
        "source": {"inter_arrival_time_s": 45.0},
        "stations": [{"id": "M1", "processing_time_s": 150,
                      "availability_pct": 98.0, "mttr_s": 600,
                      "power_working_kw": 4.0, "power_idle_kw": 0.4}],
        "buffers": [{"id": "B0", "capacity": 10, "before": "source",
                     "after": "M1"}],
    },
    "des_horizon": {"warmup_s": 21600.0, "window_s": 432000.0,
                    "replications": 10},
}

PROGRAM = "import simpy\nprint('Throughput = 1.0 parts/hour')\n"


def scripted(*replies):
    """A `submit` that answers each turn from `replies`, recording its prompts."""
    calls = []

    def submit(prompt, attempt):
        calls.append({"prompt": prompt, "attempt": attempt})
        index = len(calls) - 1
        if index >= len(replies):
            raise AssertionError(f"submit called {len(calls)} times, only "
                                 f"{len(replies)} replies scripted")
        return replies[index]

    return submit, calls


# --------------------------------------------------------------------------- #
# normalize_requirements
# --------------------------------------------------------------------------- #
def test_normalize_passes_a_dict_through():
    assert pipeline.normalize_requirements(REQ) is REQ


def test_normalize_decodes_a_json_document():
    assert pipeline.normalize_requirements(json.dumps(REQ)) == REQ


@pytest.mark.parametrize("value", [
    None, 7, [], "not json", "[1, 2]", '"a string"',
])
def test_normalize_returns_none_when_there_are_no_requirements(value):
    assert pipeline.normalize_requirements(value) is None


# --------------------------------------------------------------------------- #
# the DB slot
# --------------------------------------------------------------------------- #
def test_db_repairs_a_broken_reply_and_returns_the_valid_schema():
    submit, calls = scripted(BROKEN_SQL, SCHEMA)
    seen = []

    outcome = pipeline.generate_db_schema(
        submit, REQ, attempts=3,
        on_attempt=lambda i, sql, verdict: seen.append((i, sql, verdict["ok"])))

    assert outcome["ok"] is True
    assert outcome["sql"] == SCHEMA
    assert outcome["attempts"] == 2
    assert outcome["repaired"] == 1
    assert outcome["report"] == ""
    assert outcome["summary"]["tables"] == 2
    assert outcome["summary"]["views"] == 1
    assert seen == [(0, BROKEN_SQL, False), (1, SCHEMA, True)]
    assert [c["attempt"] for c in calls] == [0, 1]


def test_db_first_turn_is_make_db_prompt_and_later_turns_carry_the_report():
    submit, calls = scripted(BROKEN_SQL, SCHEMA)

    pipeline.generate_db_schema(submit, REQ, attempts=3)

    assert calls[0]["prompt"] == user_prompts.make_db_prompt(REQ)
    repair = calls[1]["prompt"]
    assert repair.startswith("The SQL you returned is not a usable PostgreSQL "
                             "schema.")
    assert "the reply is a JSON document, not SQL" in repair
    assert BROKEN_SQL in repair          # the reply itself is handed back
    # the prompt text wraps, so compare on unwrapped whitespace
    assert "This is repair attempt 1 of 3." in " ".join(repair.split())


def test_db_decodes_a_requirements_string_for_the_prompt():
    submit, calls = scripted(SCHEMA)

    pipeline.generate_db_schema(submit, json.dumps(REQ))

    assert calls[0]["prompt"] == user_prompts.make_db_prompt(REQ)
    # not the escaped text json.dumps would have produced for a string
    assert '"{\\"production_type\\"' not in calls[0]["prompt"]


def test_db_returns_the_last_reply_when_every_attempt_fails():
    submit, calls = scripted(BROKEN_SQL, "still not sql", "nor this")

    outcome = pipeline.generate_db_schema(submit, REQ, attempts=2)

    assert outcome["ok"] is False
    assert outcome["sql"] == "nor this"
    assert outcome["attempts"] == 3      # initial + 2 repairs
    assert outcome["repaired"] == 2
    assert "not SQL" in outcome["report"]
    assert len(calls) == 3


def test_db_stops_when_a_turn_returns_nothing():
    submit, calls = scripted(BROKEN_SQL, None, SCHEMA)

    outcome = pipeline.generate_db_schema(submit, REQ, attempts=3)

    assert outcome["ok"] is False
    assert outcome["sql"] == BROKEN_SQL
    assert outcome["attempts"] == 1
    assert outcome["repaired"] == 0
    assert "no schema" in outcome["report"]
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# the DES slot
# --------------------------------------------------------------------------- #
def fake_des_verify(verdicts):
    """Replace `des_runner.verify` with a scripted run, recording its calls.

    This is the seam that executes the program, so stubbing it keeps the whole
    repair loop under test without an interpreter that has simpy installed.
    """
    calls = []

    def verify(code, **kwargs):
        calls.append({"code": code, "kwargs": kwargs})
        index = len(calls) - 1
        assert index < len(verdicts), "verify called more often than scripted"
        return verdicts[index]

    return verify, calls


FAILED_RUN = {"ok": False, "kpis": {}, "execution": {"status": "simulation_error",
                                                     "elapsed_s": 0.3},
              "report": "The program did not complete: the program exited with "
                        "code 1."}
GOOD_RUN = {"ok": True, "report": "",
            "kpis": {"throughput_per_hour": 23.5, "wip_parts": 3.2,
                     "energy_per_part_kwh": 0.42},
            "execution": {"status": "ok", "elapsed_s": 1.7}}


def test_des_repairs_a_failing_program_and_returns_the_working_one(monkeypatch):
    verify, runs = fake_des_verify([FAILED_RUN, GOOD_RUN])
    monkeypatch.setattr(des_runner, "verify", verify)
    submit, calls = scripted(PROGRAM, PROGRAM.replace("simpy", "simpy  # v2"))
    seen = []

    outcome = pipeline.generate_des_model(
        submit, REQ, SCHEMA, attempts=2,
        on_attempt=lambda i, code, verdict: seen.append((i, code, verdict["ok"])))

    assert outcome["ok"] is True
    assert outcome["code"] == PROGRAM.replace("simpy", "simpy  # v2")
    assert outcome["attempts"] == 2
    assert outcome["repaired"] == 1
    assert outcome["kpis"] == GOOD_RUN["kpis"]
    assert outcome["execution"]["status"] == "ok"
    assert seen == [(0, PROGRAM, False),
                    (1, PROGRAM.replace("simpy", "simpy  # v2"), True)]
    assert len(runs) == 2


def test_des_first_turn_is_make_gen_des_and_later_turns_carry_the_traceback(monkeypatch):
    verify, _ = fake_des_verify([FAILED_RUN, GOOD_RUN])
    monkeypatch.setattr(des_runner, "verify", verify)
    submit, calls = scripted(PROGRAM, PROGRAM)

    pipeline.generate_des_model(submit, REQ, SCHEMA, attempts=2)

    assert calls[0]["prompt"] == user_prompts.make_gen_des(REQ, SCHEMA)
    assert calls[1]["prompt"] == user_prompts.make_gen_des_repair(
        REQ, SCHEMA, PROGRAM, FAILED_RUN["report"], 1, 2)
    assert "repair attempt 1 of 2" in " ".join(calls[1]["prompt"].split())


def test_des_decodes_a_requirements_string_for_prompt_and_bounds(monkeypatch):
    verify, runs = fake_des_verify([GOOD_RUN])
    monkeypatch.setattr(des_runner, "verify", verify)
    submit, calls = scripted(PROGRAM)

    outcome = pipeline.generate_des_model(submit, json.dumps(REQ), SCHEMA)

    assert calls[0]["prompt"] == user_prompts.make_gen_des(REQ, SCHEMA)
    # the runner's semantic bounds see the object, not the JSON text
    assert runs[0]["kwargs"]["requirements"] == REQ
    assert outcome["ok"] is True


def test_des_passes_the_execution_knobs_to_the_runner(monkeypatch):
    verify, runs = fake_des_verify([GOOD_RUN])
    monkeypatch.setattr(des_runner, "verify", verify)
    submit, _ = scripted(PROGRAM)

    pipeline.generate_des_model(submit, REQ, SCHEMA, timeout_s=42,
                                python="/usr/bin/python3",
                                reject_all_zero=False)

    kwargs = runs[0]["kwargs"]
    assert kwargs["timeout_s"] == 42
    assert kwargs["python"] == "/usr/bin/python3"
    assert kwargs["reject_all_zero"] is False


def test_des_returns_the_last_program_when_every_attempt_fails(monkeypatch):
    verify, _ = fake_des_verify([FAILED_RUN, FAILED_RUN, FAILED_RUN])
    monkeypatch.setattr(des_runner, "verify", verify)
    submit, calls = scripted(PROGRAM, PROGRAM, PROGRAM)

    outcome = pipeline.generate_des_model(submit, REQ, SCHEMA, attempts=2)

    assert outcome["ok"] is False
    assert outcome["code"] == PROGRAM
    assert outcome["attempts"] == 3
    assert outcome["repaired"] == 2
    assert outcome["report"] == FAILED_RUN["report"]
    assert len(calls) == 3


def test_des_stops_when_a_turn_returns_nothing(monkeypatch):
    verify, runs = fake_des_verify([FAILED_RUN])
    monkeypatch.setattr(des_runner, "verify", verify)
    submit, calls = scripted(PROGRAM, None, PROGRAM)

    outcome = pipeline.generate_des_model(submit, REQ, SCHEMA, attempts=3)

    assert outcome["ok"] is False
    assert outcome["code"] == PROGRAM
    assert outcome["attempts"] == 1
    assert "no program" in outcome["report"]
    assert len(runs) == 1
    assert len(calls) == 2


def test_des_survives_a_requirements_result_that_does_not_parse(monkeypatch):
    verify, runs = fake_des_verify([GOOD_RUN])
    monkeypatch.setattr(des_runner, "verify", verify)
    submit, calls = scripted(PROGRAM)

    outcome = pipeline.generate_des_model(submit, "not json at all", SCHEMA)

    assert outcome["ok"] is True
    # the prompt still carries the text the client has, verbatim
    assert calls[0]["prompt"] == user_prompts.make_gen_des(
        "not json at all", SCHEMA)
    # and the sanity check that needs an object is disabled, not crashed on
    assert runs[0]["kwargs"]["requirements"] is None


# --------------------------------------------------------------------------- #
# job_result
# --------------------------------------------------------------------------- #
def test_job_result_names_the_db_artifact_and_verdict():
    result = pipeline.job_result("db", {
        "sql": SCHEMA, "ok": True, "attempts": 2, "repaired": 1,
        "report": "", "summary": {"tables": 2},
    })

    assert result["slot"] == "db"
    assert result["ok"] is True
    assert result["artifact"] == SCHEMA
    assert result["attempts"] == 2
    assert result["repaired"] == 1
    assert result["summary"] == {"tables": 2}


def test_job_result_names_the_des_artifact_kpis_and_status():
    result = pipeline.job_result("des", {
        "code": PROGRAM, "ok": False, "attempts": 1, "repaired": 0,
        "report": "boom", "kpis": {"wip_parts": 3.2},
        "execution": {"status": "simulation_error", "elapsed_s": 0.3},
    })

    assert result["slot"] == "des"
    assert result["artifact"] == PROGRAM
    assert result["status"] == "simulation_error"
    assert result["elapsed_s"] == 0.3
    assert result["kpis"] == {"wip_parts": 3.2}
    assert result["report"] == "boom"


def test_job_result_calls_a_missing_reply_no_reply():
    result = pipeline.job_result("des", {"code": None, "ok": False,
                                         "attempts": 0, "repaired": 0,
                                         "report": "the agent returned nothing",
                                         "kpis": {}, "execution": None})

    assert result["artifact"] is None
    assert result["status"] == "no_reply"
    assert result["kpis"] == {}


def test_job_result_rejects_an_unknown_slot():
    with pytest.raises(ValueError):
        pipeline.job_result("conf", {"ok": True})
