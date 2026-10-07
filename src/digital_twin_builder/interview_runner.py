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

try:  # see the `config` import above
    import requirements_schema
except ImportError:  # pragma: no cover
    from . import requirements_schema

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

# The requirements schema — its fields, their shapes, and the fraction rule for
# `line.defects.rate` — is defined once in `requirements_schema`, so the prompt
# the agent is shown, this validator and the client all check the same list.
# `REQUIRED_KEYS` is re-exported here for callers that read it from this module.
REQUIRED_KEYS = requirements_schema.REQUIRED_KEYS


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
    return requirements_schema.problem(requirements)


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
    stops the loop because there is nothing to read or to correct. In that case
    the outcome keeps the last verdict that *was* read, so the report still says
    why that reply was rejected and the requirements it carried are not lost;
    only a first turn that produces nothing yields the generic "nothing to read".
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
            # A turn that produced nothing is not a verdict on any reply: there
            # is nothing to read or to correct. Record it as such *for this
            # turn*, but keep the last *read* verdict for the outcome when there
            # is one. Overwriting it made the outcome contradict itself: it
            # handed the last reply back in `reply`/`replies` while the report
            # claimed there was nothing to read, and a readable `completed: true`
            # reply that was rejected for one missing key lost the requirements
            # it did carry. The correction turn's failure is added to the report
            # so both facts survive.
            no_answer = {"ok": False, "completed": False,
                         "requirements": None, "message": "", "summary": {},
                         "report": ("The agent returned no answer for this turn "
                                    "(the task failed or did not complete in "
                                    "time), so there was nothing to read")}
            if verdict is None:
                verdict = no_answer
            else:
                verdict = {
                    **verdict,
                    "report": (verdict.get("report", "").rstrip()
                               + "\n\nThe correction turn produced no answer "
                                 "(the task failed or did not complete in "
                                 "time), so the reply above is still the one "
                                 "to fix.").strip(),
                }
            if callable(on_attempt):
                on_attempt(i, None, no_answer)
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
