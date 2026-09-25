"""Modbus ingestion: the user's sensors -> `sensor_readings`.

The interview collects, per Modbus sensor, a host and port plus a unit id,
register and data type. This loop reads each one's register and writes the value
as a reading; `sensor_detection_loop` (M2AD) then scores those rows. It replaces
the Kaggle seed path, which fed the demo with NASA datasets instead of the
devices the user actually has.

One unreachable device never stops the loop or the others: a read that fails
logs, backs off, and is retried; the other sensors are read in the same pass.
Nothing here is fatal.
"""
from __future__ import annotations

import logging
import os
import struct
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymodbus.client import ModbusTcpClient

from detector.shared import get_db_connection, shutdown_event

logger = logging.getLogger("detector.modbus")

POLL_INTERVAL = float(os.environ.get("MODBUS_POLL_INTERVAL_S", "5"))
CONNECT_TIMEOUT = float(os.environ.get("MODBUS_TIMEOUT_S", "3"))

# A device that is down should not be retried every five seconds forever. Each
# failed read closes the connection and doubles the wait, up to the cap; the
# first success resets it.
BACKOFF_BASE = float(os.environ.get("MODBUS_BACKOFF_BASE_S", "5"))
BACKOFF_MAX = float(os.environ.get("MODBUS_BACKOFF_MAX_S", "300"))

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_DATA_TYPE = "int16"
DEFAULT_REGISTER_TYPE = "holding"

# How many registers a type spans, and the big-endian struct code that decodes
# them: Modbus words are big-endian on the wire, and a 32-bit value is two
# words with the high word first.
_TYPES: Dict[str, tuple] = {
    "int16": (1, ">h"),
    "uint16": (1, ">H"),
    "int32": (2, ">i"),
    "uint32": (2, ">I"),
    "float32": (2, ">f"),
    "float": (2, ">f"),
}

# The four Modbus data tables, and whether their values are the sixteen-bit
# words `decode_registers` reads (holding/input) or single bits (coil/discrete).
# The interview records `register_type`, defaulting to a holding register, which
# is what a "register number" means unless the user says otherwise.
_REGISTER_TYPES: Dict[str, tuple] = {
    "holding": ("read_holding_registers", True),
    "input": ("read_input_registers", True),
    "coil": ("read_coils", False),
    "discrete": ("read_discrete_inputs", False),
}

# A holding-register reference as printed in a datasheet or PLC address list
# (40001-49999) is 1-based, so the protocol address is the reference minus
# 40001. Anything below 40001 is already a protocol address and is used as it
# stands. Documented in the interview prompt so the number the user reads off
# their device is the number they enter.
_HOLDING_REF_BASE = 40001


def _type_spec(data_type: Optional[str]) -> tuple:
    spec = _TYPES.get(str(data_type or DEFAULT_DATA_TYPE).lower())
    if spec is None:
        logger.warning("data_type %r is not supported; reading as %s", data_type, DEFAULT_DATA_TYPE)
        return _TYPES[DEFAULT_DATA_TYPE]
    return spec


def _register_kind(register_type: Optional[str]) -> tuple:
    """`(read method name, is_word)` for a config's `register_type`.

    An unknown or missing kind reads as a holding register, which is what the
    interview's "register number" means, and says so in the log rather than
    dropping the sensor's readings on the floor.
    """
    kind = str(register_type or DEFAULT_REGISTER_TYPE).lower()
    spec = _REGISTER_TYPES.get(kind)
    if spec is None:
        logger.warning(
            "register_type %r is not supported; reading as %s",
            register_type, DEFAULT_REGISTER_TYPE,
        )
        return _REGISTER_TYPES[DEFAULT_REGISTER_TYPE]
    return spec


def register_address(register: int) -> int:
    """The protocol address for a datasheet register reference."""
    return register - _HOLDING_REF_BASE if register >= _HOLDING_REF_BASE else register


def decode_registers(data_type: Optional[str], registers: List[int]) -> Optional[float]:
    """The registers as one number, or None when there are too few of them."""
    count, fmt = _type_spec(data_type)
    if len(registers) < count:
        return None
    raw = b"".join(struct.pack(">H", value & 0xFFFF) for value in registers[:count])
    return float(struct.unpack(fmt, raw)[0])


def _read_value(client, spec: Dict[str, Any]) -> Optional[float]:
    """One value from one sensor over an already-connected client."""
    sensor_id = spec.get("id")
    register = spec.get("register")
    if not spec.get("ip") or register is None:
        return None

    unit_id = int(spec.get("unit_id") or DEFAULT_UNIT_ID)
    data_type = spec.get("data_type")
    method_name, is_word = _register_kind(spec.get("register_type"))
    count = _type_spec(data_type)[0]
    address = register_address(int(register))

    read = getattr(client, method_name)
    response = read(address, count=count, device_id=unit_id)
    if response.isError():
        logger.warning("[%s] read error at register %s: %s", sensor_id, register, response)
        return None
    if not is_word:
        return float(bool(response.bits[0])) if response.bits else None
    return decode_registers(data_type, list(response.registers))


def fetch_sensor_value(spec: Dict[str, Any]) -> Optional[float]:
    """One reading from one sensor over a fresh connection, or None.

    The poll loop holds its connections open (`_SensorPoller`); this one-shot
    form is for a caller that wants a single value without that state. A sensor
    with no host or no register is not read at all: the interview records null
    rather than inventing addressing, and a device the user never described has
    nothing to read.
    """
    if not spec.get("ip") or spec.get("register") is None:
        return None
    port = int(spec.get("port") or DEFAULT_PORT)
    client = ModbusTcpClient(spec["ip"], port=port, timeout=CONNECT_TIMEOUT)
    try:
        if not client.connect():
            logger.warning("[%s] no Modbus server at %s:%s", spec.get("id"), spec["ip"], port)
            return None
        return _read_value(client, spec)
    except Exception as exc:
        logger.warning("[%s] Modbus read failed: %s", spec.get("id"), exc)
        return None
    finally:
        client.close()


class _SensorPoller:
    """One sensor's connection, and the backoff for when it has none.

    Each poll used to open and close a TCP session, which reconnects every
    interval and hammers a device that is down. The connection is kept for a
    healthy sensor, and a failing one is put on an exponential backoff so a
    dead device is retried rarely instead of every five seconds.
    """

    def __init__(self, spec: Dict[str, Any]):
        self.spec = spec
        self.sensor_id = spec.get("id")
        self.client = None
        self.failures = 0
        self.retry_at = 0.0

    def _back_off(self, reason: str) -> None:
        self.failures += 1
        delay = min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (self.failures - 1)))
        self.retry_at = time.time() + delay
        if self.client is not None:
            self.client.close()
            self.client = None
        logger.warning(
            "[%s] %s; retrying in %.0fs (failure %d)",
            self.sensor_id, reason, delay, self.failures,
        )

    def _connect(self) -> bool:
        port = int(self.spec.get("port") or DEFAULT_PORT)
        client = ModbusTcpClient(self.spec["ip"], port=port, timeout=CONNECT_TIMEOUT)
        if not client.connect():
            client.close()
            self._back_off(f"no Modbus server at {self.spec['ip']}:{port}")
            return False
        self.client = client
        return True

    def poll(self) -> Optional[float]:
        if not self.spec.get("ip") or self.spec.get("register") is None:
            return None
        if time.time() < self.retry_at:
            return None
        if self.client is None and not self._connect():
            return None
        try:
            value = _read_value(self.client, self.spec)
        except Exception as exc:
            self._back_off(f"Modbus read failed: {exc}")
            return None
        if value is None:
            self._back_off("read returned no value")
            return None
        self.failures = 0
        self.retry_at = 0.0
        return value

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None


def store_reading(conn, channel_id: str, value: float) -> None:
    """Append one reading. `dataset` has no default in the schema, so it is
    named here — 'modbus' is the real-device path, alongside the demo datasets
    the column was introduced for."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sensor_readings (channel_id, dataset, timestamp, value)
               VALUES (%s, 'modbus', %s, %s)""",
            (channel_id, datetime.now(timezone.utc), value),
        )
    conn.commit()


def modbus_poll_loop(specs: List[Dict[str, Any]]) -> None:
    """Poll every configured sensor until shutdown, once per POLL_INTERVAL."""
    if not specs:
        logger.info("No Modbus sensors in the config; polling loop not started")
        return

    pollers = [_SensorPoller(spec) for spec in specs]
    logger.info(
        "Modbus polling loop started (%d sensors, every %.0fs)",
        len(pollers), POLL_INTERVAL,
    )
    conn = get_db_connection()
    try:
        while not shutdown_event.is_set():
            started = time.time()
            for poller in pollers:
                if shutdown_event.is_set():
                    break
                value = poller.poll()
                if value is None:
                    continue
                try:
                    store_reading(conn, poller.spec["id"], value)
                except Exception as exc:
                    logger.warning("[%s] could not store reading: %s", poller.sensor_id, exc)
                    conn.rollback()

            remaining = POLL_INTERVAL - (time.time() - started)
            if remaining > 0:
                shutdown_event.wait(timeout=remaining)
    finally:
        for poller in pollers:
            poller.close()
        conn.close()
        logger.info("Modbus polling loop stopped")
