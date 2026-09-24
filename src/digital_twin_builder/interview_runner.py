"""Read the interview agent's reply as the schema's JSON, and judge whether it did.

The UI agent answers with a JSON document: `{"completed": true,
"requirements": {...}, "message": "..."}` when the interview is finished, or
`{"completed": false, "message": "..."}` when it is asking the user a question.
Nothing in the pipeline ever checked that, and a small model gets it wrong in
ways the client cannot recover from — it emits its `<think>` block before the
JSON, writes a stray extra `}` after the object, or runs out of tokens mid-object
— so the reply reaches `JSON.parse` unreadable and the finished interview is
dropped in silence.

This module closes that gap the way `sql_runner` and `des_runner` close it for
their stages: it reads the reply, returns a report that can be fed back to the
agent for a correction, and runs the same submit/repair loop. `completed: false`
is a legitimate answer and is not repaired — the agent asking a question is the
interview working, not failing. Only a reply that cannot be read as the schema's
JSON, or that claims to be finished while its `requirements` is incomplete, is.

`strip_think` is what makes the read reliable: the model's reasoning is prose,
and a brace inside it would otherwise be mistaken for the start of the answer.
"""
from __future__ import annotations

import json
import re

try:  # the app imports this as a top-level module; tests may import it as a package
    from config import UI_REPAIR_ATTEMPTS
except ImportError:  # pragma: no cover - fallback for a bare `python interview_runner.py`
    UI_REPAIR_ATTEMPTS = 2

# A reasoning block, with a closing tag. SmolLM3 writes `<think>`; the variants
# are cheap to accept and cost nothing.
THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>",
                      re.DOTALL | re.IGNORECASE)
# An opening tag whose block was never closed — the turn was cut off inside its
# reasoning, so there is no answer after it.
THINK_OPEN_RE = re.compile(r"<think(?:ing)?>", re.IGNORECASE)

# How much of the reply is fed back to the agent with the verdict. Enough for the
# whole object on a normal reply, short enough not to crowd out the repair prompt.
REPORT_CHARS = 4000

# The requirements schema the UI agent is asked for: the 13 top-level fields of
# the object in `prompts.system.UI`. All of them must be present on a finished
# interview — a field with nothing to report is null or empty, not absent.
REQUIRED_KEYS = (
    "production_type", "processes", "equipment", "sensors", "cameras",
    "goals", "data_sources", "update_frequency", "critical_parameters",
    "line", "des_horizon", "units", "additional_info",
)

# The fields whose *shape* the schema fixes and a consumer depends on: the DB
# prompt iterates `sensors` and `cameras`, the DES prompt reads `line` and
# `des_horizon`. A field of the wrong kind is a defect, not a deviation.
LIST_KEYS = ("processes", "sensors", "cameras")
MAPPING_KEYS = ("line", "des_horizon", "units", "critical_parameters")
# `equipment` is deliberately unconstrained. The schema shows it as a list, but
# the recorded runs answer with a nested object, and no consumer reads it: every
# prompt renders the whole requirements object as JSON and the agent is told to
# treat the equipment as context only. Its kind is therefore not something a
# reply can get wrong, and rejecting one spelling would only send a readable
# reply back for a correction it does not need.


def strip_think(text: str) -> str:
    """Drop the model's reasoning block, keeping everything after it.

    A closed `<think>…</think>` is removed wherever it sits. An opening tag with
    no closing one means the turn ended inside the reasoning: everything from it
    is discarded, so what is left is empty and the reply is read as "no answer"
    rather than as JSON that a brace in the reasoning happened to start.
    """
    text = THINK_RE.sub("", text or "")
    m = THINK_OPEN_RE.search(text)
    return text[:m.start()] if m else text


def extract_json_object(text: str) -> str | None:
    """The first complete JSON object in `text`, or None if there is none.

    Braces inside strings do not count, so the object ends at its own matching
    brace — not at the last brace in the text. That distinction is the whole
    point: the agent writes an extra `}` after the requirements often enough
    that slicing to the last brace hands `json.loads` trailing junk and rejects
    an object that is in fact complete. The scan returns that complete object and
    ignores whatever follows it.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if in_string:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_reply(reply: str) -> dict | None:
    """The reply's JSON object, or None when it cannot be read as one."""
    raw = extract_json_object(strip_think(reply or ""))
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _device_problem(entries, name: str) -> str | None:
    """Why a `sensors` / `cameras` list cannot be used, or None when it can.

    Every entry has to be an object with a name: the DB prompt resolves a device
    from its identifier, and an entry without one cannot be mapped to a machine.
    """
    for i, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            return (f"`requirements.{name}[{i}]` is not an object: every entry "
                    f"needs a `name` (and its address, when the user named one)")
        label = entry.get("name")
        if not isinstance(label, str) or not label.strip():
            return (f"`requirements.{name}[{i}]` has no `name`, so the device "
                    f"cannot be identified")
    return None


def _rate_problem(requirements: dict) -> str | None:
    """Why `line.defects.rate` is not a fraction, or None when it is.

    The rest of the object states a share as a fraction (`water_tank: 0.05` for
    5 %), so a defect rate written as a percentage (`2` for 2 %) is a unit
    error the downstream model would read as a 200 % scrap rate. It is caught
    here because it is the one semantic slip the recorded runs kept making.
    """
    line = requirements.get("line")
    if not isinstance(line, dict):
        return None
    defects = line.get("defects")
    if not isinstance(defects, dict):
        return None
    rate = defects.get("rate")
    if rate is None or isinstance(rate, bool):
        return None
    if not isinstance(rate, (int, float)):
        return ("`requirements.line.defects.rate` is not a number. It is the "
                "fraction of parts that are scrapped, e.g. 0.02 for 2 %")
    if not 0.0 <= float(rate) <= 1.0:
        return (f"`requirements.line.defects.rate` is {rate}, but it is a "
                f"fraction of the parts, not a percentage: 2 % is 0.02, the "
                f"same way the water threshold 5 % is written 0.05 elsewhere "
                f"in the object")
    return None


def summarize(requirements) -> dict:
    """The counts a client can show for a requirements object. Never raises."""
    if not isinstance(requirements, dict):
        return {}

    def count(value):
        return len(value) if isinstance(value, list) else 0

    line = requirements.get("line")
    line = line if isinstance(line, dict) else {}
    return {
        "keys_present": sum(1 for key in REQUIRED_KEYS if key in requirements),
        "sensors": count(requirements.get("sensors")),
        "cameras": count(requirements.get("cameras")),
        "stations": count(line.get("stations")),
        "buffers": count(line.get("buffers")),
    }


def check(reply: str) -> str | None:
    """Why the reply is not a readable answer, or None when it is.

    Each branch names the defect concretely enough for the UI agent to correct
    it: the object was cut off, the requirements field is missing, the device
    list has no names, the defect rate is a percentage instead of a fraction.
    """
    text = strip_think(reply or "")
    if not text.strip():
        return ("the agent returned nothing: the reply is empty, so there is no "
                "answer to read")
    raw = extract_json_object(text)
    if raw is None:
        if "{" in text:
            return ("the reply contains a `{` but no complete JSON object: the "
                    "object is never closed, so it was cut off before its final "
                    "`}` — the answer has to be one complete JSON object")
        return ("the reply contains no JSON object. The interview agent answers "
                "with a single JSON object — `{\"completed\": ...}` — and a "
                "reply without one cannot be read")
    try:
        parsed = json.loads(raw)
    except ValueError as e:
        return (f"the JSON object in the reply does not parse: {e}. An extra or "
                f"missing brace, a trailing comma or an unquoted value makes "
                f"the whole object unreadable")
    if not isinstance(parsed, dict):
        return "the reply's JSON is not an object at the top level"

    completed = parsed.get("completed")
    if not isinstance(completed, bool):
        return ("the reply's JSON has no boolean `completed` field. It must be "
                "`true` when the requirements are complete and `false` when "
                "there are questions left to ask")
    if not completed:
        message = parsed.get("message")
        if not isinstance(message, str) or not message.strip():
            return ("`completed` is false but there is no `message`: a turn that "
                    "does not finish the interview has to carry the questions "
                    "for the user in `message`")
        return None

    requirements = parsed.get("requirements")
    if not isinstance(requirements, dict):
        return ("`completed` is true but `requirements` is missing or is not an "
                "object: a finished interview has to carry the whole "
                "requirements object")
    missing = [key for key in REQUIRED_KEYS if key not in requirements]
    if missing:
        return ("the requirements object is missing "
                + ", ".join(f"`{key}`" for key in missing)
                + ". Every one of the 13 fields of the schema must be present "
                  "(a field with nothing to report is `null`, an empty list or "
                  "an empty string — not absent)")
    for key in LIST_KEYS:
        if not isinstance(requirements.get(key), list):
            return (f"`requirements.{key}` is not a list, but the schema "
                    f"defines it as a list of entries")
    for key in MAPPING_KEYS:
        if not isinstance(requirements.get(key), dict):
            return (f"`requirements.{key}` is not an object, but the schema "
                    f"defines it as an object")
    problem = _device_problem(requirements.get("sensors"), "sensors")
    if problem:
        return problem
    problem = _device_problem(requirements.get("cameras"), "cameras")
    if problem:
        return problem
    return _rate_problem(requirements)


def _report(reason: str, reply: str) -> str:
    """`reason` plus the reply it was found in, as the text fed to the agent."""
    body = strip_think(reply or "").strip()
    return (reason + ".\n\nThe reply that was returned "
            f"(last {REPORT_CHARS} characters):\n"
            f"{body[-REPORT_CHARS:] or '(empty reply)'}")


def verify(reply: str) -> dict:
    """Decide whether the interview agent's reply is a readable answer.

    Success needs a reply that parses as the schema's JSON and, when it claims
    to be finished, carries a `requirements` object with all 13 fields. `report`
    is the text handed back to the agent on failure — empty when `ok` is True.
    """
    reason = check(reply)
    parsed = parse_reply(reply)
    requirements = parsed.get("requirements") if parsed else None
    requirements = requirements if isinstance(requirements, dict) else None
    message = parsed.get("message") if parsed else None
    completed = bool(parsed.get("completed")) if parsed else False
    return {
        "ok": reason is None,
        "completed": completed and reason is None,
        "requirements": requirements,
        "message": message if isinstance(message, str) else "",
        "summary": summarize(requirements),
        "report": _report(reason, reply) if reason else "",
    }


def generate_with_repair(submit, *, attempts: int | None = None,
                         repair_prompt=None, on_attempt=None) -> dict:
    """Ask `submit` for an answer, read it, and ask again while it does not read.

    `submit(prompt_text, attempt)` returns the agent's reply for one turn — or
    None if the turn produced no reply at all (task failed or timed out), which
    stops the loop because there is nothing to read or to correct.
    `repair_prompt(previous_reply, report, attempt, total)` builds the follow-up
    message (normally `prompts.user.make_ui_repair`). The loop reads the reply
    after every turn and stops at the first one that is readable — including a
    `completed: false` question, which is an answer and not a defect. It always
    returns the last reply, successful or not, together with the verdict and the
    requirements or question it carried.
    """
    total = UI_REPAIR_ATTEMPTS if attempts is None else attempts
    # `total` counts repairs, so a total of 2 allows 3 replies: the initial one
    # plus two corrections.
    replies: list[str] = []
    verdict: dict | None = None
    prompt = None

    for i in range(total + 1):
        reply = submit(prompt, i)
        if reply is None:
            verdict = {"ok": False, "completed": False, "requirements": None,
                       "message": "", "summary": {},
                       "report": ("The agent returned no answer for this turn "
                                  "(the task failed or did not complete in "
                                  "time), so there was nothing to read")}
            if callable(on_attempt):
                on_attempt(i, None, verdict)
            break
        replies.append(reply)
        verdict = verify(reply)
        if callable(on_attempt):
            on_attempt(i, reply, verdict)
        if verdict["ok"] or i == total:
            break
        prompt = (repair_prompt(reply, verdict["report"], i + 1, total)
                  if callable(repair_prompt) else verdict["report"])

    return {
        "reply": replies[-1] if replies else None,
        "replies": replies,
        "ok": bool(verdict and verdict["ok"]),
        "completed": bool(verdict and verdict.get("completed")),
        "requirements": (verdict or {}).get("requirements"),
        "message": (verdict or {}).get("message", "") or "",
        "summary": (verdict or {}).get("summary", {}) or {},
        "report": (verdict or {}).get("report", ""),
        "repaired": max(len(replies) - 1, 0),
        "attempts": len(replies),
    }
