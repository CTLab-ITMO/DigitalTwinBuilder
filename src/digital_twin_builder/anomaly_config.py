"""The interview's requirements as the anomaly stack's `config.json`.

The anomaly stack (the `anomaly` compose profile) is driven by a small
zone-keyed JSON file: each zone has sensors with a Modbus address and cameras
with an RTSP stream, and the detector polls those addresses. That file was
hand-written for the demo. The interview already asks the user for their
devices, so this module turns the `requirements` document it produces into the
same file, which the API stores per session and the user's machine pulls when it
starts the stack.

Nothing here talks to an LLM, a database or the network: `requirements` in, a
config dict out, so the mapping is unit-tested directly. The detector tolerates
missing addressing (a sensor with no register simply yields no readings), so a
device the user never described keeps its `None`s instead of being invented —
this module normalises shapes and slugifies names, it never fills in a value
that was not in the requirements.

The zone name is the caller's: `api-server.py` passes a slug of the session
title so the Grafana dashboard is recognisable, and the fallback chain here is
the production type, then `production_line`.
"""
from __future__ import annotations

import json
import re

__all__ = ["build_anomaly_config"]

DEFAULT_ZONE = "production_line"
_ZONE_MAX = 100  # zones.name is VARCHAR(100)
_ID_MAX = 100  # registered_sources.source_id is VARCHAR(100)


def build_anomaly_config(requirements, *, zone_name: str | None = None) -> dict:
    """Build the stack's config from an interview result.

    `requirements` is the object the UI agent returned, or the raw JSON text the
    client stored it as — both spellings reach the API, exactly as they reach
    `pipeline.normalize_requirements`. Anything that is not an object with at
    least one sensor or camera produces `{}`: there is nothing to poll, and an
    empty config is the honest answer rather than a zone the detector would
    start with no channels.

    The result is one zone (the interview collects a flat device list with no
    zone membership) holding `sensors` and `cameras`. Each sensor keeps the
    Modbus address the user described; each camera gets an `rtsp_url` assembled
    from its ip, port and stream path, and only when an ip was actually named.
    """
    req = _as_dict(requirements)
    if req is None:
        return {}

    zone = _zone(req, zone_name)
    # One `seen` set for both lists: `registered_sources.source_id` is globally
    # unique and `config_loader` keys on it, so a sensor and a camera that share
    # a base name must not both keep it — the second would overwrite the first
    # and one device's readings would be attributed to the other.
    seen: set[str] = set()
    sensors = _sources(req.get("sensors"), "sensor", seen)
    cameras = _sources(req.get("cameras"), "camera", seen)
    if not sensors and not cameras:
        return {}

    return {
        zone: {
            "description": _text(req.get("production_type")) or f"Zone: {zone}",
            "sensors": sensors,
            "cameras": cameras,
        }
    }


def _as_dict(value) -> dict | None:
    """The requirements as an object, or None when they do not parse.

    Mirrors `pipeline.normalize_requirements`: an object passes through, a string
    is decoded, and anything else (None, a list) carries no requirements.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _zone(req: dict, zone_name: str | None) -> str:
    for candidate in (zone_name, req.get("production_type")):
        slug = _slug(candidate)
        if slug:
            return slug[:_ZONE_MAX]
    return DEFAULT_ZONE


def _sources(raw, kind: str, seen: set[str]) -> list[dict]:
    """The sensor or camera list, normalised and de-duplicated by id.

    The interview's shape is a list of objects; a dict keyed by id (the spelling
    `config_loader` also accepts) is read too, with the key as the id. Entries
    that are not objects are skipped — the model occasionally emits a bare
    string in the list. `seen` is the caller's and spans both lists, because the
    ids share one namespace downstream.
    """
    if isinstance(raw, dict):
        items = [dict(info, id=info.get("id", key)) if isinstance(info, dict) else {"id": key}
                 for key, info in raw.items()]
    elif isinstance(raw, list):
        items = [item for item in raw if isinstance(item, dict)]
    else:
        return []

    out: list[dict] = []
    for index, item in enumerate(items, start=1):
        entry = _sensor(item) if kind == "sensor" else _camera(item)
        if entry is None:
            continue
        entry["id"] = _unique(entry["id"] or f"{kind}_{index}", seen)
        out.append(entry)
    return out


def _sensor(item: dict) -> dict:
    entry: dict = {"id": _id_of(item), "protocol": "modbus"}
    sensor_type = _slug(item.get("sensor_type") or item.get("name"))
    if sensor_type:
        entry["sensor_type"] = sensor_type[:_ID_MAX]
    unit = _text(item.get("unit"))
    if unit:
        entry["unit"] = unit
    _copy_address(entry, item, _SENSOR_KEYS)
    return entry


def _camera(item: dict) -> dict:
    entry: dict = {"id": _id_of(item), "protocol": "rtsp"}
    category = _slug(item.get("category") or item.get("name"))
    if category:
        entry["category"] = category[:_ID_MAX]
    _copy_address(entry, item, _CAMERA_KEYS)
    url = _rtsp_url(entry)
    if url:
        entry["rtsp_url"] = url
    return entry


def _copy_address(entry: dict, item: dict, keys: dict[str, object]) -> None:
    """Copy the addressing keys the user gave, each through its own coercion.

    An ip is text and a port/register is an integer, and the difference matters:
    running an ip through the integer reader would silently drop every sensor's
    address, which is the one thing the detector cannot work without. A value
    that does not coerce (a bool, `"M40001"`) is left out rather than guessed.
    """
    for key, coerce in keys.items():
        value = coerce(item.get(key))
        if value is not None:
            entry[key] = value


def _id_of(item: dict) -> str | None:
    """The device's slug, untruncated — `_unique` bounds it, once suffixed."""
    return _slug(item.get("id")) or _slug(item.get("name")) or None


def _rtsp_url(entry: dict) -> str | None:
    """`rtsp://host:port/path`, and only when the user named a host.

    The port falls back to RTSP's own 554 here, unlike the interview prompt,
    which records null rather than assume it — by this point the user has given
    a host and the URL is the thing the capture loop opens, so it needs a port
    to be a URL at all.
    """
    ip = entry.get("ip")
    if not ip:
        return None
    port = entry.get("port") or 554
    path = entry.get("stream_path") or ""
    if path and not path.startswith("/"):
        path = "/" + path
    return f"rtsp://{ip}:{port}{path}"


def _unique(base: str, seen: set[str]) -> str:
    """`base`, or `base_2`/`base_3`… when an earlier device took the name.

    Every name handed out is recorded, including the suffixed ones — a later
    device's own id can be exactly the suffix an earlier one was given, so
    `a`, `a`, `a_2` has to come out as `a`, `a_2`, `a_2_2` and not hand `a_2`
    to two devices.

    The `VARCHAR(100)` bound is applied here, after the suffix rather than
    before: trimming a 100-character name first would leave no room for `_2`,
    and the over-length id would fail the insert into `registered_sources`
    (taking the whole config load with it) instead of just losing its tail.
    """
    candidate = base[:_ID_MAX]
    suffix = 1
    while candidate in seen:
        suffix += 1
        tail = f"_{suffix}"
        candidate = base[: _ID_MAX - len(tail)] + tail
    seen.add(candidate)
    return candidate


def _slug(value) -> str:
    """A name as an id: punctuation and spaces collapsed to `_`, lowercased.

    `\\w` is Unicode-aware on purpose. The interview is Russian, so a device
    name, a production type and the fallback zone name are usually Cyrillic;
    stripping them to ASCII would leave every id empty and every device would
    collapse to `sensor_1`, `sensor_2`. Kept as they are, `датчик_температуры`
    stays readable in Grafana and still fits the column.
    """
    text = _text(value)
    if not text:
        return ""
    text = re.sub(r"[\W]+", "_", text, flags=re.UNICODE).strip("_").lower()
    return text


def _text(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _as_int(value) -> int | None:
    """An integer, or None. Strings that are not numbers and bools give None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


# Which addressing keys each device carries, and how each is read. Defined here
# because the coercers above are what they name; the order is the output order.
# `register_type` is the Modbus table the register lives in (holding, input,
# coil, discrete), defaulting to a holding register downstream when absent.
_SENSOR_KEYS = {"ip": _text, "port": _as_int, "unit_id": _as_int,
                "register": _as_int, "register_type": _text, "data_type": _text}
_CAMERA_KEYS = {"ip": _text, "port": _as_int, "stream_path": _text}