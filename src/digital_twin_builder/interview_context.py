"""The conversation the interview agent is shown, kept small enough to run.

The interview agent re-reads its whole conversation on every turn (see
`UserInteractionAgent.process_task`), so the prompt handed to the local model
grows with the dialogue. It grows faster than the dialogue does: the previous
reply is replayed on the next turn, and a correction turn carries the failure
report, which quotes that same reply back. A transformer's attention buffer
grows with the square of its input, so the second turn of a session is where the
GPU ran out of memory — recorded runs failed with `CUDA out of memory` while
allocating a several-gigabyte attention tensor for a ~38k-character prompt,
having answered the first turn of ~11k characters without trouble.

`fit_context` bounds that prompt without throwing the dialogue away:

* the model's own reasoning is removed first — `<think>…</think>` is not part of
  the conversation, and replaying it spends the budget the answer itself needs
  (it was ~36% of the recorded reply);
* a single non-system message longer than `MAX_MESSAGE_CHARS` is shortened
  end-preserving — its head and its tail — because the head names the subject
  and the tail is where a correction prompt's closing rules and a reply's final
  fields sit; a normal turn is far below the cap and is untouched. The system
  message is exempt: it is the instruction set, its JSON-type rules sit past the
  halfway point, and clipping it there silently dropped them from every prompt;
* if the prompt is still over `MAX_CONTEXT_CHARS`, the *oldest* middle messages
  are dropped — assistant turns first, so the user's own words outlive the
  model's — and the system instructions and the turn the model is answering are
  never dropped.

Pure and stdlib-only, so the agent (which imports torch) and the tests can both
call it.
"""
from __future__ import annotations

try:  # the app imports this as a top-level module; tests may import it as a package
    from config import UI_MAX_CONTEXT_CHARS, UI_MAX_MESSAGE_CHARS
except ImportError:  # pragma: no cover - fallback for a bare import
    UI_MAX_CONTEXT_CHARS = 18000
    UI_MAX_MESSAGE_CHARS = 7000

try:  # see the `config` import above
    from interview_runner import strip_think
except ImportError:  # pragma: no cover
    from .interview_runner import strip_think


# The whole assembled prompt, and any one message in it. Both are proxies: the
# local model's tokenizer turns Cyrillic at roughly three characters per token,
# so a character budget is a stable stand-in for the token count the attention
# buffer actually scales with.
MAX_CONTEXT_CHARS = UI_MAX_CONTEXT_CHARS
MAX_MESSAGE_CHARS = UI_MAX_MESSAGE_CHARS

# The marker `_excerpt` leaves where it cut a message's middle. Kept short and
# plain so a model reading it understands the text is incomplete, not corrupt.
_EXCERPT_MARKER = "\n…[сокращено]…\n"

# How much of the turn being answered must survive even when the instructions
# alone have filled the budget: a question cut shorter than this cannot be
# answered, so the instructions are shortened instead.
MIN_TURN_CHARS = 1000


def _excerpt(text: str, limit: int) -> str:
    """`text` shortened to `limit` characters, keeping its head and its tail."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(_EXCERPT_MARKER):
        return text[:limit]
    head = (limit - len(_EXCERPT_MARKER)) // 2
    tail = limit - len(_EXCERPT_MARKER) - head
    return text[:head] + _EXCERPT_MARKER + text[-tail:]


def _chars(messages) -> int:
    return sum(len(m["content"]) for m in messages)


def fit_context(messages, max_chars: int = MAX_CONTEXT_CHARS,
                max_message_chars: int = MAX_MESSAGE_CHARS) -> list[dict]:
    """`messages` with reasoning removed and its total size bounded.

    The first message (the system instructions) and the last (the turn the model
    is answering) are always kept. Everything between them is droppable, oldest
    first and the model's own turns before the user's.
    """
    msgs = []
    for m in (messages or []):
        role = m.get("role", "")
        content = strip_think(m.get("content") or "")
        # The system message is the instruction set, not one turn: it carries the
        # JSON value types and the defect-fraction rule, and those sit past the
        # halfway point, so clipping its middle with the per-message cap quietly
        # removed them from every prompt. It is bounded by the context budget
        # below instead; the cap stays for an oversized turn (a reply or a
        # correction prompt).
        if role != "system":
            content = _excerpt(content, max_message_chars)
        msgs.append({"role": role, "content": content})
    if len(msgs) == 1:
        msgs[0]["content"] = _excerpt(msgs[0]["content"], max_chars)
        return msgs
    if not msgs:
        return msgs

    # Drop the oldest middle message while the prompt is over budget. Assistant
    # turns go before user turns: the user's words are what the requirements are
    # built from, and a model turn can be asked for again.
    for role in ("assistant", "user"):
        i = 1
        while _chars(msgs) > max_chars and i < len(msgs) - 1:
            if msgs[i]["role"] == role:
                del msgs[i]
            else:
                i += 1

    # Not enough room even for the instructions and the current turn. Shorten
    # the current turn to what is left, but never below a question that can still
    # be answered; the instructions give up whatever remains.
    if _chars(msgs) > max_chars:
        room = max_chars - len(msgs[0]["content"]) - _chars(msgs[1:-1])
        if room < MIN_TURN_CHARS:
            room = min(MIN_TURN_CHARS, max_chars)
        msgs[-1]["content"] = _excerpt(msgs[-1]["content"], room)
    if _chars(msgs) > max_chars:
        msgs[0]["content"] = _excerpt(msgs[0]["content"],
                                      max(max_chars - _chars(msgs[1:]), 0))
    return msgs
