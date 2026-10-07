"""Tests for bounding the interview agent's prompt in `interview_context`.

The interview agent re-feeds its whole conversation to a local model every turn,
and the prompt grows with the dialogue — the previous reply is replayed, and a
repair turn's failure report quotes it back. A transformer's attention buffer
grows with the square of the prompt, which is why a session's second turn ran the
GPU out of memory on a ~38k-character prompt after answering the first turn's
~11k without trouble.

What is pinned here:

* the model's reasoning is removed from every message, so it is neither replayed
  nor charged to the budget;
* the messages that carry the interview — the system instructions, the user's own
  turns, and the turn being answered — survive; the model's own answered turns
  are what a trim gives up first;
* a single oversized non-system message (a correction prompt) is shortened
  end-preserving rather than dropped, because its head names the defect and its
  tail carries the reply contract; the system instructions are exempt from that
  per-message cap, since their JSON-type rules sit past the halfway point and
  clipping the middle dropped them from every prompt.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "digital_twin_builder"))

import interview_context  # noqa: E402


def msg(role, content):
    return {"role": role, "content": content}


def chars(messages):
    return sum(len(m["content"]) for m in messages)


def test_reasoning_is_removed_from_every_message():
    context = [
        msg("system", "instructions"),
        msg("assistant", "<think>long reasoning { with braces }</think>\nanswer"),
    ]

    fitted = interview_context.fit_context(context)

    assert fitted[1]["content"] == "\nanswer"
    assert "reasoning" not in fitted[1]["content"]


def test_an_unclosed_reasoning_block_leaves_nothing_behind():
    context = [
        msg("system", "instructions"),
        msg("assistant", "<think>cut off mid-thought…"),
    ]

    fitted = interview_context.fit_context(context)

    assert fitted[1]["content"] == ""


def test_empty_input_is_empty_output():
    assert interview_context.fit_context([]) == []
    assert interview_context.fit_context(None) == []


def test_a_single_message_is_kept_and_bounded():
    fitted = interview_context.fit_context([msg("system", "x" * 500)],
                                           max_chars=100)

    assert len(fitted) == 1
    assert len(fitted[0]["content"]) == 100


def test_a_normal_conversation_is_left_alone():
    context = [
        msg("system", "s" * 7000),
        msg("assistant", "Привет!"),
        msg("user", "u" * 3000),
    ]

    fitted = interview_context.fit_context(context, max_chars=20000)

    assert fitted == context


def test_the_first_and_last_messages_are_never_dropped():
    context = [
        msg("system", "s" * 100),
        msg("user", "u" * 100),
        msg("assistant", "a" * 100),
        msg("user", "last"),
    ]

    fitted = interview_context.fit_context(context, max_chars=150)

    assert fitted[0]["role"] == "system"
    assert fitted[-1]["content"] == "last"


def test_an_assistant_turn_is_dropped_before_a_user_turn():
    context = [
        msg("system", "s" * 100),
        msg("user", "u" * 100),
        msg("assistant", "a" * 100),
        msg("user", "l" * 100),
    ]

    fitted = interview_context.fit_context(context, max_chars=350)

    roles = [m["role"] for m in fitted]
    # 100 + 100 + 100 + 100 = 400 > 350: exactly one middle has to go, and it is
    # the model's turn, not the user's.
    assert roles == ["system", "user", "user"]
    assert chars(fitted) <= 350


def test_a_long_message_is_shortened_keeping_its_head_and_its_tail():
    body = "HEAD" + "x" * 5000 + "TAIL"

    fitted = interview_context.fit_context(
        [msg("system", "instructions"), msg("user", body)],
        max_message_chars=1000, max_chars=100000)

    shortened = fitted[-1]["content"]
    assert len(shortened) == 1000
    assert shortened.startswith("HEAD")
    assert shortened.endswith("TAIL")
    assert "сокращено" in shortened


def test_the_instructions_are_not_clipped_by_the_per_message_cap():
    # The system message carries the JSON value types and the defect-fraction
    # rule past its halfway point, so the per-message cap — meant for an
    # oversized turn — must not cut its middle out; the context budget bounds it.
    system = "S" * 9000

    fitted = interview_context.fit_context(
        [msg("system", system), msg("user", "u" * 100)],
        max_chars=20000)

    assert fitted[0]["content"] == system


def test_the_recorded_failing_turn_is_bounded_and_keeps_the_interview():
    # The shapes the deployed session recorded: a 7.4k-char system prompt, the
    # user's 3.2k description, a 10.9k reply (a third of it reasoning), and a
    # long correction prompt that quotes the reply back.
    reply = "<think>" + "r" * 3878 + "</think>" + "R" * 7007
    repair = ("Твой предыдущий ответ не удалось прочитать как JSON.\n"
              + "D" * 4000 + "\n" + reply + "\n" + "C" * 1221)
    context = [
        msg("system", "S" * 7413),
        msg("assistant", "Привет! Расскажи о производстве."),
        msg("user", "Хочу цифровой двойник кофейного автомата." + "u" * 3100),
        msg("assistant", reply),
        msg("user", repair),
    ]

    fitted = interview_context.fit_context(context, max_chars=18000)

    assert chars(fitted) <= 18000
    assert fitted[0]["role"] == "system"
    # The instructions and the user's description survive, so the agent can still
    # rebuild the requirements it was asked for.
    assert any(m["role"] == "user" and m["content"].startswith(
        "Хочу цифровой двойник") for m in fitted)
    # The current turn survives — shortened, but with its opening (the defect)
    # and its close (the reply contract) intact.
    assert fitted[-1]["role"] == "user"
    assert fitted[-1]["content"].startswith("Твой предыдущий ответ")
    assert fitted[-1]["content"].endswith("C")
    assert all("<think>" not in m["content"] for m in fitted)


def test_the_instructions_give_up_room_before_the_turn_stops_being_a_question():
    context = [
        msg("system", "S" * 500),
        msg("user", "U" * 500),
    ]

    fitted = interview_context.fit_context(context, max_chars=800)

    assert chars(fitted) <= 800
    # The user's turn could not be dropped (it is the one being answered), and
    # the budget leaves it under the minimum, so the instructions take the cut
    # instead of the question being shortened further.
    assert fitted[-1]["content"] == "U" * 500
    assert len(fitted[0]["content"]) == 300
    assert fitted[0]["content"].startswith("S")


def test_a_turn_under_the_budget_is_shortened_after_the_instructions():
    context = [
        msg("system", "S" * 400),
        msg("user", "U" * 4000),
    ]

    fitted = interview_context.fit_context(context, max_chars=3000)

    assert chars(fitted) <= 3000
    assert fitted[0]["content"] == "S" * 400
    assert len(fitted[-1]["content"]) == 2600
    assert fitted[-1]["content"].startswith("U")
