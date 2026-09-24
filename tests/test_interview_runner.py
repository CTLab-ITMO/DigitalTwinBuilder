"""Tests for reading the interview agent's reply in `interview_runner`.

The UI agent answers with the requirements JSON, and a small model gets it wrong
in ways the client cannot recover from: it writes its `<think>` block before the
answer, adds a stray extra `}` after the object, or is cut off mid-object. This
module and its tests pin the read the client used to do itself — the thinking
block is stripped before the object is looked for, the object is the first
*balanced* one rather than everything up to the last brace, and a reply that is
not the schema's JSON is named concretely enough to repair.

What is pinned here:

* the read — a stray extra brace is recovered, a brace inside the reasoning is
  not mistaken for the answer, and a truncated object is reported as truncated;
* the verdict — `completed: false` is a valid answer (the agent asking a
  question) and is not repaired, while a `completed: true` reply whose
  `requirements` is incomplete or mistyped is;
* the loop — a broken reply followed by a valid one is repaired, both turns are
  recorded, and the requirements that come back are the valid ones.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "digital_twin_builder"))

import interview_runner  # noqa: E402
from prompts import user as user_prompts  # noqa: E402


REQ = {
    "production_type": "демонстрационное производство напитков",
    "processes": ["нагрев воды", "заваривание эспрессо"],
    "equipment": ["кофемашина"],
    "sensors": [{"name": "boiler_temp_c", "ip": "192.168.1.209", "port": 1502}],
    "cameras": [{"name": "brewer_render", "ip": "192.168.1.209", "port": 8554}],
    "goals": "онлайн-мониторинг состояния",
    "data_sources": "Modbus TCP, RTSP",
    "update_frequency": "100 мс",
    "critical_parameters": {"boiler_temp_c": 120},
    "line": {
        "topology": "serial",
        "source": {"inter_arrival_time_s": 60},
        "stations": [{"id": "M1", "processing_time_s": 45,
                      "availability_pct": 99.0, "mttr_s": 300,
                      "power_working_kw": 1.4, "power_idle_kw": 0.35}],
        "buffers": [{"id": "B0", "capacity": 4, "before": "source",
                     "after": "M1"}],
        "defects": {"rate": 0.02},
    },
    "des_horizon": {"warmup_s": 1800, "window_s": 28800, "replications": 5},
    "units": {"time": "s", "power": "kW", "energy": "kWh"},
    "additional_info": "бак 1500 мл, чашка 150 мл",
}

VALID = json.dumps({"completed": True, "requirements": REQ,
                    "message": "готово"}, ensure_ascii=False)

# The recorded failure: a second `}` closes the outer object right after the
# requirements, so the `"message"` that follows it is trailing junk. Slicing to
# the last brace hands `json.loads` that junk and rejects an object that is in
# fact complete.
_REQ_JSON = json.dumps(REQ, ensure_ascii=False, indent=2)
REPLY_EXTRA_BRACE = (
    '{\n  "completed": true,\n  "requirements": ' + _REQ_JSON +
    '\n  },\n  "message": "готово"\n}'
)

# The recorded failure: the reply ran out of tokens inside the object, so no
# brace ever closes it.
REPLY_TRUNCATED = VALID[:VALID.rindex("}")]

# A reasoning block, then the answer. The brace inside the reasoning is not the
# answer and must not be read as one.
THINKING = ('<think>\nLet me collect the fields as {"a": 1} and then write the '
            'object.\n</think>\n\n' + VALID)

QUESTION = json.dumps({"completed": False,
                       "message": "Уточните, пожалуйста, тип производства."},
                      ensure_ascii=False)


def without(key):
    """`REQ` with one key removed, as a `completed: true` reply."""
    return json.dumps({"completed": True,
                       "requirements": {k: v for k, v in REQ.items() if k != key},
                       "message": "готово"}, ensure_ascii=False)


def mutated(key, value, section=None):
    """`REQ` with `key` (optionally inside `section`) set to `value`."""
    req = json.loads(json.dumps(REQ))
    if section is None:
        req[key] = value
    else:
        req[section][key] = value
    return json.dumps({"completed": True, "requirements": req,
                       "message": "готово"}, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# the read
# --------------------------------------------------------------------------- #
def test_strip_think_removes_a_closed_block():
    assert interview_runner.strip_think(THINKING).strip() == VALID


def test_strip_think_drops_an_unclosed_block_entirely():
    assert interview_runner.strip_think("<think>still reasoning…").strip() == ""


def test_extract_reads_a_brace_in_a_string_as_text():
    text = '{"message": "a } brace and a { brace", "completed": false}'

    assert interview_runner.extract_json_object(text) == text


def test_extract_returns_the_first_balanced_object():
    assert interview_runner.extract_json_object(
        'noise {"a": 1} trailing {"b": 2}') == '{"a": 1}'


def test_extract_returns_none_without_a_closing_brace():
    assert interview_runner.extract_json_object('{"a": 1') is None


def test_parse_recovers_the_object_before_a_stray_extra_brace():
    parsed = interview_runner.parse_reply(REPLY_EXTRA_BRACE)

    assert parsed["completed"] is True
    assert parsed["requirements"] == REQ


def test_parse_reads_the_object_after_a_think_block():
    assert interview_runner.parse_reply(THINKING)["requirements"] == REQ


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def test_check_accepts_a_finished_interview():
    assert interview_runner.check(VALID) is None


def test_check_accepts_a_question():
    assert interview_runner.check(QUESTION) is None


@pytest.mark.parametrize("reply", ["", "   ", "Твой ответ…", "<think>only thought"])
def test_check_rejects_a_reply_with_no_object(reply):
    reason = interview_runner.check(reply)

    assert reason is not None
    assert "no JSON object" in reason or "returned nothing" in reason


def test_check_reports_a_truncated_object_as_cut_off():
    reason = interview_runner.check(REPLY_TRUNCATED)

    assert reason is not None
    assert "never closed" in reason


def test_check_rejects_missing_completed():
    reason = interview_runner.check('{"requirements": {}}')

    assert reason is not None
    assert "boolean `completed`" in reason


def test_check_rejects_a_question_without_a_message():
    reason = interview_runner.check('{"completed": false}')

    assert reason is not None
    assert "has to carry the questions" in reason


def test_check_rejects_true_without_requirements():
    reason = interview_runner.check('{"completed": true}')

    assert reason is not None
    assert "`requirements` is missing" in reason


def test_check_names_every_missing_requirements_field():
    reason = interview_runner.check(without("units"))

    assert reason is not None
    assert "`units`" in reason
    assert "13 fields" in reason


def test_check_rejects_a_sensor_list_that_is_not_a_list():
    reason = interview_runner.check(mutated("sensors", {"name": "temp"}))

    assert reason is not None
    assert "`requirements.sensors` is not a list" in reason


def test_check_rejects_a_line_that_is_not_an_object():
    reason = interview_runner.check(mutated("line", "serial"))

    assert reason is not None
    assert "`requirements.line` is not an object" in reason


def test_check_rejects_a_sensor_without_a_name():
    reason = interview_runner.check(mutated("sensors", [{"ip": "10.0.0.1"}]))

    assert reason is not None
    assert "has no `name`" in reason


def test_check_rejects_a_defect_rate_written_as_a_percentage():
    reply = json.dumps({"completed": True,
                        "requirements": {**REQ, "line": {**REQ["line"],
                                                         "defects": {"rate": 2}}},
                        "message": "готово"}, ensure_ascii=False)

    reason = interview_runner.check(reply)

    assert reason is not None
    assert "not a percentage" in reason


def test_check_accepts_a_fraction_defect_rate():
    assert interview_runner.check(VALID) is None


def test_check_accepts_a_null_defect_rate():
    reply = json.dumps({"completed": True,
                        "requirements": {**REQ, "line": {**REQ["line"],
                                                         "defects": {"rate": None}}},
                        "message": "готово"}, ensure_ascii=False)

    assert interview_runner.check(reply) is None


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def test_verify_returns_the_requirements_and_their_counts():
    verdict = interview_runner.verify(VALID)

    assert verdict["ok"] is True
    assert verdict["completed"] is True
    assert verdict["requirements"] == REQ
    assert verdict["message"] == "готово"
    assert verdict["report"] == ""
    assert verdict["summary"] == {"keys_present": 13, "sensors": 1, "cameras": 1,
                                  "stations": 1, "buffers": 1}


def test_verify_returns_a_question_as_a_valid_answer():
    verdict = interview_runner.verify(QUESTION)

    assert verdict["ok"] is True
    assert verdict["completed"] is False
    assert verdict["requirements"] is None
    assert "Уточните" in verdict["message"]


def test_verify_never_calls_a_rejected_reply_completed():
    verdict = interview_runner.verify(without("units"))

    assert verdict["ok"] is False
    assert verdict["completed"] is False
    assert "13 fields" in verdict["report"]
    assert "The reply that was returned" in verdict["report"]


def test_verify_reports_the_reply_verbatim_on_failure():
    verdict = interview_runner.verify(REPLY_TRUNCATED)

    assert "never closed" in verdict["report"]
    assert REPLY_TRUNCATED[-200:] in verdict["report"]


# --------------------------------------------------------------------------- #
# generate_with_repair
# --------------------------------------------------------------------------- #
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


def test_loop_repairs_an_unreadable_reply_and_returns_the_valid_one():
    submit, calls = scripted(REPLY_TRUNCATED, VALID)
    seen = []

    outcome = interview_runner.generate_with_repair(
        submit, attempts=2,
        repair_prompt=user_prompts.make_ui_repair,
        on_attempt=lambda i, reply, verdict: seen.append((i, verdict["ok"])))

    assert outcome["ok"] is True
    assert outcome["completed"] is True
    assert outcome["requirements"] == REQ
    assert outcome["reply"] == VALID
    assert outcome["attempts"] == 2
    assert outcome["repaired"] == 1
    assert outcome["report"] == ""
    assert seen == [(0, False), (1, True)]
    assert [c["attempt"] for c in calls] == [0, 1]
    assert calls[0]["prompt"] is None
    assert "попытка исправления 1 из 2" in calls[1]["prompt"]


def test_loop_keeps_the_first_reply_when_it_is_a_question():
    submit, calls = scripted(QUESTION)

    outcome = interview_runner.generate_with_repair(submit, attempts=2)

    assert outcome["ok"] is True
    assert outcome["completed"] is False
    assert outcome["requirements"] is None
    assert "Уточните" in outcome["message"]
    assert outcome["attempts"] == 1
    assert outcome["repaired"] == 0
    assert len(calls) == 1


def test_loop_stops_when_a_turn_returns_nothing():
    submit, calls = scripted(REPLY_TRUNCATED, None, VALID)

    outcome = interview_runner.generate_with_repair(submit, attempts=2)

    assert outcome["ok"] is False
    assert outcome["reply"] == REPLY_TRUNCATED
    assert outcome["attempts"] == 1
    assert outcome["repaired"] == 0
    assert "no answer" in outcome["report"]
    assert len(calls) == 2


def test_loop_returns_the_last_reply_when_every_attempt_fails():
    submit, calls = scripted(REPLY_TRUNCATED, REPLY_TRUNCATED, REPLY_TRUNCATED)

    outcome = interview_runner.generate_with_repair(submit, attempts=2)

    assert outcome["ok"] is False
    assert outcome["reply"] == REPLY_TRUNCATED
    assert outcome["attempts"] == 3      # initial + 2 repairs
    assert outcome["repaired"] == 2
    assert "never closed" in outcome["report"]
    assert len(calls) == 3


def test_loop_defaults_its_attempts_to_config():
    submit, calls = scripted(*([REPLY_TRUNCATED] * 8))

    interview_runner.generate_with_repair(submit)

    assert len(calls) == interview_runner.UI_REPAIR_ATTEMPTS + 1
