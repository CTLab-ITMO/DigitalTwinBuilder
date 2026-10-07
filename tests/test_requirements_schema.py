"""Tests for the shared requirements schema.

`requirements_schema` is the single definition of the interview's fields: the UI
prompt renders its example, `interview_runner` validates against it, and the API
hands `as_dict()` to the client. These tests pin that the three stay one list —
the example the agent is shown is a complete, passing object, and every rule a
consumer depends on is expressed once and enforced by `problem()`.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "digital_twin_builder"))

import requirements_schema  # noqa: E402
from prompts import system as system_prompts  # noqa: E402


# --------------------------------------------------------------------------- #
# the fields
# --------------------------------------------------------------------------- #
def test_the_schema_is_the_thirteen_interview_fields():
    assert len(requirements_schema.REQUIRED_KEYS) == 13
    assert tuple(requirements_schema.FIELDS) == requirements_schema.REQUIRED_KEYS
    assert requirements_schema.REQUIRED_KEYS[0] == "production_type"
    assert requirements_schema.REQUIRED_KEYS[-1] == "additional_info"


def test_only_the_consumed_fields_fix_a_shape():
    # The DB prompt resolves sensors and cameras by name; the DES prompt reads
    # `line`. Everything else is the agent's to spell.
    shaped = {name: f.kind for name, f in requirements_schema.FIELDS.items()
              if f.kind != "any"}
    assert shaped == {
        "processes": "list", "sensors": "list", "cameras": "list",
        "critical_parameters": "dict", "line": "dict", "des_horizon": "dict",
        "units": "dict",
    }


def test_equipment_is_deliberately_unconstrained():
    # The recorded runs answer with a nested object where the example shows a
    # list, and no consumer reads it — one spelling must not be rejectable.
    assert requirements_schema.FIELDS["equipment"].kind == "any"


# --------------------------------------------------------------------------- #
# the example
# --------------------------------------------------------------------------- #
def test_example_carries_every_field():
    assert set(requirements_schema.example_requirements()) == set(
        requirements_schema.REQUIRED_KEYS)


def test_example_is_a_complete_passing_object():
    assert requirements_schema.problem(
        requirements_schema.example_requirements()) is None


def test_example_is_a_fresh_copy():
    first = requirements_schema.example_requirements()
    first["processes"].append("mutated")
    assert requirements_schema.example_requirements()["processes"] == [
        "список процессов"]


def test_example_json_parses_back_to_the_example():
    assert json.loads(requirements_schema.example_json()) == \
        requirements_schema.example_requirements()


# --------------------------------------------------------------------------- #
# as_dict — what the client validates with
# --------------------------------------------------------------------------- #
def test_as_dict_names_every_field_in_order():
    assert [f["name"] for f in requirements_schema.as_dict()] == \
        list(requirements_schema.REQUIRED_KEYS)


def test_as_dict_carries_the_entry_and_fraction_rules():
    by_name = {f["name"]: f for f in requirements_schema.as_dict()}
    assert by_name["sensors"]["entry_requires"] == ["name"]
    assert by_name["cameras"]["entry_requires"] == ["name"]
    assert by_name["line"]["fraction"] == ["defects", "rate"]
    assert by_name["goals"]["kind"] == "any"


# --------------------------------------------------------------------------- #
# problem — the shape rules
# --------------------------------------------------------------------------- #
def full(**overrides):
    req = requirements_schema.example_requirements()
    req.update(overrides)
    return req


def test_problem_accepts_the_example():
    assert requirements_schema.problem(requirements_schema.example_requirements()) is None


def test_problem_names_every_missing_field_and_the_count():
    reason = requirements_schema.problem({"production_type": "x"})

    assert "13 fields" in reason
    for name in requirements_schema.REQUIRED_KEYS[1:]:
        assert f"`{name}`" in reason


@pytest.mark.parametrize("name", ["processes", "sensors", "cameras"])
def test_problem_rejects_a_list_field_that_is_not_a_list(name):
    reason = requirements_schema.problem(full(**{name: {"a": 1}}))

    assert reason == f"`requirements.{name}` is not a list, but the schema " \
                     f"defines it as a list of entries"


@pytest.mark.parametrize("name", ["critical_parameters", "line", "des_horizon",
                                  "units"])
def test_problem_rejects_an_object_field_that_is_not_an_object(name):
    reason = requirements_schema.problem(full(**{name: "nope"}))

    assert reason == f"`requirements.{name}` is not an object, but the schema " \
                     f"defines it as an object"


@pytest.mark.parametrize("name", ["sensors", "cameras"])
def test_problem_rejects_a_device_entry_that_is_not_an_object(name):
    reason = requirements_schema.problem(full(**{name: ["192.168.1.1"]}))

    assert f"`requirements.{name}[0]` is not an object" in reason


@pytest.mark.parametrize("name", ["sensors", "cameras"])
def test_problem_rejects_a_device_without_a_name(name):
    reason = requirements_schema.problem(full(**{name: [{"ip": "10.0.0.1"}]}))

    assert f"`requirements.{name}[0]` has no `name`" in reason


def test_problem_rejects_a_blank_device_name():
    reason = requirements_schema.problem(full(sensors=[{"name": "   "}]))

    assert "has no `name`" in reason


def test_problem_accepts_an_empty_device_list():
    assert requirements_schema.problem(full(sensors=[], cameras=[])) is None


def test_problem_rejects_a_defect_rate_written_as_a_percentage():
    reason = requirements_schema.problem(
        full(line={**requirements_schema.example_requirements()["line"],
                   "defects": {"rate": 2}}))

    assert "not a percentage" in reason
    assert "`requirements.line.defects.rate` is 2" in reason


def test_problem_rejects_a_non_numeric_defect_rate():
    reason = requirements_schema.problem(
        full(line={"defects": {"rate": "2%"}}))

    assert "is not a number" in reason


@pytest.mark.parametrize("rate", [0, 0.02, 1, None])
def test_problem_accepts_a_fractional_or_absent_defect_rate(rate):
    assert requirements_schema.problem(
        full(line={"defects": {"rate": rate}})) is None


def test_problem_accepts_a_missing_defects_section():
    assert requirements_schema.problem(full(line={"topology": "serial"})) is None


# --------------------------------------------------------------------------- #
# the prompt is built from the schema
# --------------------------------------------------------------------------- #
def test_ui_prompt_fills_the_requirements_token():
    prompt = system_prompts.ui_prompt()

    assert system_prompts.UI_REQUIREMENTS_TOKEN not in prompt
    assert '"production_type": "описание типа производства"' in prompt
    assert "defects" in prompt


def test_the_example_in_the_prompt_is_the_schema_example():
    prompt = system_prompts.ui_prompt()

    start = prompt.index('"requirements": ') + len('"requirements": ')
    text = prompt[start:]
    # The envelope's closing brace is the last one; the example itself is the
    # balanced object that starts here.
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                text = text[:i + 1]
                break
    assert json.loads(text) == requirements_schema.example_requirements()
