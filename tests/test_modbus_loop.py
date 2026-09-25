"""Tests for the Modbus ingestion loop and the alert cooldown.

`modbus_loop` turns the interview's per-sensor addressing into readings, and the
one thing that must not go wrong is the addressing itself: a register reference
read off a datasheet is 1-based, the wire address is not, and a coil is a bit
while a holding register is a word. A sensor the user described only partially
must be read with the protocol's own defaults (port 502, unit 1) but must not
have those invented for it anywhere upstream.

`shared.alert_due`/`clear_alert` are the cooldown that stops a sustained
anomaly writing one alert per detection interval; the "cleared" case is what
makes the next, separate anomaly alert immediately rather than wait out a
window.

No DB and no device: the client is faked, so this runs anywhere.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "anomaly"))

from detector import modbus_loop, shared  # noqa: E402


class _Response:
    def __init__(self, *, registers=None, bits=None, error=False):
        self.registers = registers
        self.bits = bits
        self._error = error

    def isError(self):
        return self._error


class _FakeClient:
    """The slice of `ModbusTcpClient` `_read_value` touches."""

    def __init__(self, spec, *, connected=True, response=None):
        self.spec = spec
        self._connected = connected
        self._response = response
        self.closed = 0

    def connect(self):
        return self._connected

    def close(self):
        self.closed += 1

    def read_holding_registers(self, address, count, device_id):
        self.last = (address, count, device_id)
        return self._response

    def read_input_registers(self, address, count, device_id):
        return self.read_holding_registers(address, count, device_id)

    def read_coils(self, address, count, device_id):
        return self.read_holding_registers(address, count, device_id)

    def read_discrete_inputs(self, address, count, device_id):
        return self.read_holding_registers(address, count, device_id)


def test_register_reference_maps_to_a_protocol_address():
    assert modbus_loop.register_address(40001) == 0
    assert modbus_loop.register_address(40002) == 1
    assert modbus_loop.register_address(49999) == 9998
    # Below the reference base it is already a protocol address.
    assert modbus_loop.register_address(0) == 0
    assert modbus_loop.register_address(1) == 1


def test_decode_registers_by_data_type():
    assert modbus_loop.decode_registers("int16", [7]) == 7.0
    assert modbus_loop.decode_registers("uint16", [0xFFFF]) == 65535.0
    assert modbus_loop.decode_registers("int32", [0x0000, 0x0005]) == 5.0
    assert modbus_loop.decode_registers("float32", [0x4348, 0x0000]) == 200.0
    # `float` is the same 32-bit type under a shorter name.
    assert modbus_loop.decode_registers("float", [0x4348, 0x0000]) == 200.0


def test_too_few_registers_or_an_unknown_type():
    # A 32-bit read needs two words; one is not enough to decode.
    assert modbus_loop.decode_registers("int32", [5]) is None
    # An unrecognised type reads as the default (int16), not as nothing.
    assert modbus_loop.decode_registers("mystery", [9]) == 9.0


def test_register_kind_defaults_to_a_holding_register():
    assert modbus_loop._register_kind("holding") == ("read_holding_registers", True)
    assert modbus_loop._register_kind("input") == ("read_input_registers", True)
    assert modbus_loop._register_kind("coil") == ("read_coils", False)
    assert modbus_loop._register_kind("discrete") == ("read_discrete_inputs", False)
    assert modbus_loop._register_kind(None) == ("read_holding_registers", True)
    assert modbus_loop._register_kind("bogus") == ("read_holding_registers", True)
    # Case is folded, as the config may carry `Holding`.
    assert modbus_loop._register_kind("Holding") == ("read_holding_registers", True)


def test_read_value_uses_the_defaults_for_an_unnamed_port_and_unit():
    spec = {"id": "s", "ip": "1.2.3.4", "register": 40001, "data_type": "int16"}
    client = _FakeClient(spec, response=_Response(registers=[42]))
    assert modbus_loop._read_value(client, spec) == 42.0
    # port defaults are applied by the connect side; here unit id and the
    # reference-to-address shift are what `_read_value` owns.
    assert client.last == (0, 1, modbus_loop.DEFAULT_UNIT_ID)


def test_read_value_reads_a_coil_as_a_bit():
    spec = {"id": "s", "ip": "1.2.3.4", "register": 5,
            "register_type": "coil", "data_type": "int16"}
    client = _FakeClient(spec, response=_Response(bits=[True]))
    assert modbus_loop._read_value(client, spec) == 1.0

    client = _FakeClient(spec, response=_Response(bits=[False]))
    assert modbus_loop._read_value(client, spec) == 0.0


def test_read_value_without_addressing_never_touches_the_client():
    for spec in ({"id": "s", "register": 1}, {"id": "s", "ip": "1.2.3.4"}):
        client = _FakeClient(spec, response=_Response(registers=[1]))
        assert modbus_loop._read_value(client, spec) is None
        assert not hasattr(client, "last")


def test_error_response_yields_no_reading():
    spec = {"id": "s", "ip": "1.2.3.4", "register": 1, "data_type": "int16"}
    client = _FakeClient(spec, response=_Response(registers=[1], error=True))
    assert modbus_loop._read_value(client, spec) is None


def test_fetch_sensor_value_returns_none_and_closes_on_a_dead_device():
    spec = {"id": "s", "ip": "1.2.3.4", "register": 1}
    client = _FakeClient(spec, connected=False)
    modbus_loop.ModbusTcpClient = lambda *a, **k: client  # type: ignore[assignment]
    try:
        assert modbus_loop.fetch_sensor_value(spec) is None
        assert client.closed == 1
    finally:
        import pymodbus.client
        modbus_loop.ModbusTcpClient = pymodbus.client.ModbusTcpClient


def test_poller_backs_off_and_releases_the_connection():
    spec = {"id": "s", "ip": "1.2.3.4", "register": 1, "data_type": "int16"}
    poller = modbus_loop._SensorPoller(spec)
    poller.client = _FakeClient(spec)
    real_read = modbus_loop._read_value
    modbus_loop._read_value = lambda client, spec: None
    try:
        assert poller.poll() is None
    finally:
        modbus_loop._read_value = real_read
    assert poller.failures == 1
    assert poller.client is None
    assert poller.retry_at > time.time()
    # A further poll before the retry time does nothing and does not reconnect.
    tried = []
    modbus_loop.ModbusTcpClient = lambda *a, **k: tried.append(k)  # type: ignore[assignment]
    try:
        assert poller.poll() is None
        assert tried == []
    finally:
        import pymodbus.client
        modbus_loop.ModbusTcpClient = pymodbus.client.ModbusTcpClient


def test_poller_success_resets_the_backoff():
    spec = {"id": "s", "ip": "1.2.3.4", "register": 1, "data_type": "int16"}
    poller = modbus_loop._SensorPoller(spec)
    poller.failures = 4
    poller.retry_at = 0.0
    poller.client = _FakeClient(spec)
    real_read = modbus_loop._read_value
    modbus_loop._read_value = lambda client, spec: 3.5
    try:
        assert poller.poll() == 3.5
    finally:
        modbus_loop._read_value = real_read
    assert poller.failures == 0
    assert poller.retry_at == 0.0


def test_backoff_grows_and_is_capped():
    spec = {"id": "s", "ip": "1.2.3.4", "register": 1}
    poller = modbus_loop._SensorPoller(spec)
    delays = []
    for _ in range(20):
        before = time.time()
        poller._back_off("x")
        delays.append(poller.retry_at - before)
    assert delays[0] < delays[1] < delays[2]
    assert max(delays) <= modbus_loop.BACKOFF_MAX + 1


def test_alert_cooldown_suppresses_then_clears():
    key = "test:cooldown"
    shared.clear_alert(key)
    try:
        assert shared.alert_due(key, 300) is True
        assert shared.alert_due(key, 300) is False
        assert shared.alert_due(key, 0) is True  # zero means always due
        shared.clear_alert(key)
        assert shared.alert_due(key, 300) is True  # a new episode alerts at once
    finally:
        shared.clear_alert(key)
