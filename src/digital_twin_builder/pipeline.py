"""The DB and DES slots as one generate -> validate -> repair pipeline.

The Streamlit app drove these two slots itself: it built the first-turn prompt,
submitted it to the agent, read the reply back, validated it with `sql_runner`
or `des_runner`, and re-submitted the reply with the validation report until the
artifact passed or the attempts ran out. The Vue frontend cannot do any of that
— it has no access to `prompts/`, no SQL parser and no Python interpreter — so
the loop moves here, next to the runners it uses, and the frontend calls one
endpoint per slot.

This module is the whole of that move: prompt construction and the runner call,
nothing else. It is deliberately free of HTTP, of a database and of the LLM: the
agent is reached through an injected synchronous `submit`, so the loop can be
driven by a test with a scripted reply, by `api-server.py` with an HTTP bridge,
or by the benchmark harness with its own client. Nothing here reads `config`
either — the runners already default their attempts, timeouts and interpreter
from it, and `submit` is the only thing that has to know how long a turn may
take.

The contract `submit(prompt, attempt) -> str | None` is the runners' own: it
returns the agent's reply for one turn, or None when the turn produced no reply
at all (the task failed or timed out), which stops the loop. Every prompt handed
to `submit` is text — the first-turn prompt is built here, not by the caller, so
that `prompts.user` is read in exactly one place.
"""
from __future__ import annotations

import json

try:  # the app imports these as top-level modules; tests may import them as a package
    import des_runner
    import sql_runner
    from prompts import user as user_prompts
except ImportError:  # pragma: no cover - package layout
    from . import des_runner, sql_runner
    from .prompts import user as user_prompts

__all__ = [
    "normalize_requirements",
    "generate_db_schema",
    "generate_des_model",
    "job_result",
]


def normalize_requirements(requirements) -> dict | None:
    """The interview result as an object, or None when it does not parse.

    The UI agent answers with a JSON document and the client stores it either
    parsed or as the raw text it received; both spellings reach here. An object
    is passed through, a string is decoded, anything else (None, a number) has
    no requirements in it and returns None. The DES slot uses the object for the
    arrival-rate sanity check, which a result that does not parse simply
    disables.
    """
    if isinstance(requirements, dict):
        return requirements
    if isinstance(requirements, str):
        try:
            parsed = json.loads(requirements)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _prompt_requirements(requirements):
    """`requirements` as the prompt builders should see it.

    `make_db_prompt` / `make_gen_des` splice the value into their text with
    `json.dumps`. Handed the raw JSON string that would re-encode the document
    into a quoted, escaped blob; handed the decoded object it embeds the object
    the model was meant to read. So a string that parses is decoded first, and a
    value that does not parse is passed through unchanged — the prompt then
    carries the result the client actually has, verbatim.
    """
    return normalize_requirements(requirements) or requirements


def _with_first_prompt(submit, first_prompt):
    """Adapt `submit` so the runner's first-turn `None` becomes `first_prompt`.

    The repair loop calls `submit(None, 0)` for its first turn, leaving the
    first-turn prompt to the caller. The caller here is this module, which owns
    the prompt builders, so the injected `submit` only ever sees real text.
    """
    def bound(prompt, attempt):
        return submit(first_prompt if prompt is None else prompt, attempt)
    return bound


def generate_db_schema(submit, requirements, *, attempts=None,
                       on_attempt=None) -> dict:
    """Produce a PostgreSQL schema, validate it, and repair it while it fails.

    The first turn asks `make_db_prompt(requirements)`; every later turn is
    `make_db_repair` carrying what validating the previous reply found. Returns
    `sql_runner.generate_with_repair`'s outcome unchanged: the last schema, the
    verdict, the report and the attempt count.

    `attempts` is how many corrections follow the first reply (None takes
    `config.DB_REPAIR_ATTEMPTS`); `on_attempt(i, sql, verdict)` is called after
    every turn so a caller can record progress.
    """
    req = _prompt_requirements(requirements)
    return sql_runner.generate_with_repair(
        _with_first_prompt(submit, user_prompts.make_db_prompt(req)),
        attempts=attempts,
        repair_prompt=lambda sql, report, attempt, total: (
            user_prompts.make_db_repair(req, sql, report, attempt, total)),
        on_attempt=on_attempt,
    )


def generate_des_model(submit, requirements, schema, *, attempts=None,
                       timeout_s=None, python=None, reject_all_zero=True,
                       on_attempt=None) -> dict:
    """Produce a SimPy program, run it, and repair it while it fails.

    The first turn asks `make_gen_des(requirements, schema)`; every later turn is
    `make_gen_des_repair` carrying the run's traceback, timeout notice or
    accuracy verdict. Returns `des_runner.generate_with_repair`'s outcome: the
    last program, its KPIs, the execution record and the attempt count.

    `requirements` is decoded for both the prompt and the runner's semantic
    bounds, so a result the client stored as text is checked like one stored as
    an object. `attempts`, `timeout_s` (the program's execution timeout) and
    `python` (the interpreter, which must have simpy) default the same way they
    do in the runner: None takes `config`'s value.
    """
    req = _prompt_requirements(requirements)
    return des_runner.generate_with_repair(
        _with_first_prompt(submit, user_prompts.make_gen_des(req, schema)),
        requirements=normalize_requirements(requirements),
        attempts=attempts,
        timeout_s=timeout_s,
        python=python,
        reject_all_zero=reject_all_zero,
        repair_prompt=lambda code, report, attempt, total: (
            user_prompts.make_gen_des_repair(
                req, schema, code, report, attempt, total)),
        on_attempt=on_attempt,
    )


def job_result(slot: str, outcome: dict) -> dict:
    """The runner's outcome as a JSON-serializable job result.

    `artifact` is the thing the user is given — the schema or the program —
    and is None exactly when the slot produced nothing at all. The per-stage
    keys differ (a schema has a `summary`, a program has `kpis` and the status
    of the run), so they are named by slot rather than merged into one bag.
    """
    outcome = outcome or {}
    ok = bool(outcome.get("ok"))
    attempts = int(outcome.get("attempts") or 0)
    repaired = int(outcome.get("repaired") or 0)
    report = outcome.get("report") or ""

    if slot == "db":
        artifact = outcome.get("sql")
        return {
            "slot": "db",
            "ok": ok,
            "artifact": artifact,
            "attempts": attempts,
            "repaired": repaired,
            "report": report,
            "summary": outcome.get("summary") or {},
        }
    if slot == "des":
        artifact = outcome.get("code")
        execution = outcome.get("execution") or {}
        status = execution.get("status")
        if status is None and artifact is None:
            status = "no_reply"
        return {
            "slot": "des",
            "ok": ok,
            "artifact": artifact,
            "attempts": attempts,
            "repaired": repaired,
            "report": report,
            "kpis": outcome.get("kpis") or {},
            "status": status,
            "elapsed_s": execution.get("elapsed_s"),
        }
    raise ValueError(f"unknown pipeline slot: {slot!r}")
