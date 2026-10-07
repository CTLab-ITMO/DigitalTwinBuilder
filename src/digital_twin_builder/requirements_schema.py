"""The interview requirements schema, as data.

One place defines what the interview agent has to return, and everything else is
built from it: `prompts.system.UI` renders its example, `interview_runner`
validates a reply against it, and the API hands it to the client so the browser's
"is this interview finished?" decision uses the same fields the broker does.

The fields live in `FIELDS`, in the schema's order. Each entry says what kind of
value the field holds (`any`, `list` or `dict`), what the example shows, and —
where a consumer depends on it — the shape rules: a list whose entries each need
a `name` (the DB prompt resolves a device from it), or a nested number that is a
fraction rather than a percentage. Keeping those rules beside the example means
the prompt, the validator and the client cannot drift apart.

Only stdlib is imported, so this module can be used from a prompt literal, the
API server, the repair loop and the tests alike.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Field:
    """One top-level requirements field and the shape a reply must give it.

    `kind` is `any` (unconstrained), `list` or `dict`. `entry_requires` names the
    keys every entry of a list needs. `fraction` is a path *within* the field —
    such as `("defects", "rate")` under `line` — whose number is a 0..1 fraction.
    `note` explains the field for a reader; it is not serialized.
    """

    kind: str = "any"
    example: Any = None
    entry_requires: tuple[str, ...] = ()
    fraction: tuple[str, ...] = ()
    note: str = field(default="", compare=False)


REQUIRED_KEYS: tuple[str, ...] = (
    "production_type", "processes", "equipment", "sensors", "cameras",
    "goals", "data_sources", "update_frequency", "critical_parameters",
    "line", "des_horizon", "units", "additional_info",
)

# The schema, in the order `prompts.system.UI` presents it. `equipment` is
# deliberately `any`: the recorded runs answer with a nested object while the
# example shows a list, no consumer reads it, and the agent is told to treat it
# as context only — so its kind is not something a reply can get wrong.
FIELDS: dict[str, Field] = {
    "production_type": Field(
        example="описание типа производства"),
    "processes": Field(
        kind="list", example=["список процессов"]),
    "equipment": Field(
        example=["список оборудования"]),
    "sensors": Field(
        kind="list",
        entry_requires=("name",),
        example=[{
            "id": "temperature_a", "name": "датчик и его параметр",
            "sensor_type": None, "unit": None, "ip": None, "port": None,
            "unit_id": None, "register": None, "register_type": None,
            "data_type": None, "scale": None,
        }],
        note="Modbus devices; the DB prompt resolves each from its `name`"),
    "cameras": Field(
        kind="list",
        entry_requires=("name",),
        example=[{
            "id": "camera_bottle", "name": "название камеры",
            "category": None, "ip": None, "port": None, "stream_path": None,
        }],
        note="RTSP devices; the DB prompt resolves each from its `name`"),
    "goals": Field(
        example="цели создания цифрового двойника"),
    "data_sources": Field(
        example="описание источников данных"),
    "update_frequency": Field(
        example="частота обновления данных"),
    "critical_parameters": Field(
        kind="dict", example={"параметр": "пороговое_значение"}),
    "line": Field(
        kind="dict",
        fraction=("defects", "rate"),
        example={
            "topology": "serial | serial_with_parallel | assembly | other",
            "source": {"inter_arrival_time_s": None},
            "stations": [{
                "id": "M1", "processing_time_s": None, "availability_pct": None,
                "mttr_s": None, "power_working_kw": None, "power_idle_kw": None,
            }],
            "buffers": [
                {"id": "B0", "capacity": None, "before": "source", "after": "M1"}
            ],
            "defects": {"rate": None},
        },
        note="the DES prompt reads this; `defects.rate` is a fraction, not a %"),
    "des_horizon": Field(
        kind="dict",
        example={"warmup_s": None, "window_s": None, "replications": None}),
    "units": Field(
        kind="dict", example={"time": "s", "power": "kW", "energy": "kWh"}),
    "additional_info": Field(
        example="любая дополнительная важная информация"),
}


def example_requirements() -> dict:
    """A fresh requirements object populated from the fields' examples."""
    return {name: copy.deepcopy(field.example) for name, field in FIELDS.items()}


def example_json(indent: int = 4) -> str:
    """`example_requirements()` as the JSON a prompt shows the agent."""
    return json.dumps(example_requirements(), ensure_ascii=False, indent=indent)


def as_dict() -> list[dict]:
    """The schema as plain data, for the client to validate against.

    Only what a validator needs: the field name, its kind, and the entry keys a
    list requires. The examples and notes are the prompt's concern.
    """
    return [
        {
            "name": name,
            "kind": field.kind,
            "entry_requires": list(field.entry_requires),
            "fraction": list(field.fraction),
        }
        for name, field in FIELDS.items()
    ]


def _entry_problem(entries, name: str, requires: tuple[str, ...]) -> str | None:
    """Why a list field's entries cannot be used, or None when they can.

    Every entry has to be an object carrying each required key: the DB prompt
    resolves a device from its identifier, and an entry without one cannot be
    mapped to a machine.
    """
    for i, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            needed = "`, `".join(requires)
            return (f"`requirements.{name}[{i}]` is not an object: every entry "
                    f"needs a `{needed}` (and its address, when the user named "
                    f"one)")
        for key in requires:
            label = entry.get(key)
            if not isinstance(label, str) or not label.strip():
                return (f"`requirements.{name}[{i}]` has no `{key}`, so the "
                        f"device cannot be identified")
    return None


def _fraction_problem(requirements: dict, name: str, path: tuple[str, ...]) -> str | None:
    """Why `name.path` is not a 0..1 fraction, or None when it is.

    The rest of the object states a share as a fraction (`water_tank: 0.05` for
    5 %), so a rate written as a percentage (`2` for 2 %) is a unit error the
    downstream model would read as a 200 % scrap rate.
    """
    node: Any = requirements.get(name)
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    rate = node
    if rate is None or isinstance(rate, bool):
        return None
    dotted = ".".join((name, *path))
    if not isinstance(rate, (int, float)):
        return (f"`requirements.{dotted}` is not a number. It is the fraction "
                f"of parts that are scrapped, e.g. 0.02 for 2 %")
    if not 0.0 <= float(rate) <= 1.0:
        return (f"`requirements.{dotted}` is {rate}, but it is a fraction of "
                f"the parts, not a percentage: 2 % is 0.02, the same way the "
                f"water threshold 5 % is written 0.05 elsewhere in the object")
    return None


def problem(requirements: dict) -> str | None:
    """Why `requirements` is not a complete schema object, or None when it is.

    Each branch names the defect concretely enough for the UI agent to correct
    it. `requirements` is assumed to be a dict — whether the field is present at
    all is the envelope's concern (`interview_runner.check`).
    """
    missing = [name for name in REQUIRED_KEYS if name not in requirements]
    if missing:
        return ("the requirements object is missing "
                + ", ".join(f"`{name}`" for name in missing)
                + f". Every one of the {len(REQUIRED_KEYS)} fields of the schema "
                  "must be present (a field with nothing to report is `null`, an "
                  "empty list or an empty string — not absent)")
    for name, description in FIELDS.items():
        value = requirements.get(name)
        if description.kind == "list" and not isinstance(value, list):
            return (f"`requirements.{name}` is not a list, but the schema "
                    f"defines it as a list of entries")
        if description.kind == "dict" and not isinstance(value, dict):
            return (f"`requirements.{name}` is not an object, but the schema "
                    f"defines it as an object")
    for name, description in FIELDS.items():
        if not description.entry_requires:
            continue
        found = _entry_problem(requirements.get(name), name,
                               description.entry_requires)
        if found:
            return found
    for name, description in FIELDS.items():
        if not description.fraction:
            continue
        found = _fraction_problem(requirements, name, description.fraction)
        if found:
            return found
    return None
