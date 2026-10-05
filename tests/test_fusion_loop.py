"""Tests for the fusion loop's alerting contract.

Fusion exists to combine the sensor and camera verdicts. Each of those already
has a loop that writes its own alerts, so fusion's only non-duplicate output is
the `cross_modal` alert — both modalities over threshold at once. The loop used
to write `sensor_anomaly` / `camera_anomaly` rows too, so a flag from one
modality came out twice; with the camera offline (`camera_score` always 0)
*every* sensor anomaly was written twice. These tests pin the contract: only
cross-modal fires, and the cooldown branch still waits instead of spinning.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "anomaly"))

from detector import fusion_loop  # noqa: E402

ZONE = "zone"


class _OneShotEvent:
    """`shutdown_event` stand-in: set itself on the first wait.

    The loop checks `is_set()` at the top, so the first iteration runs and the
    first `wait()` ends it — exactly one pass per test.
    """

    def __init__(self):
        self._set = False
        self.timeouts = []

    def is_set(self):
        return self._set

    def wait(self, timeout=None):
        self.timeouts.append(timeout)
        self._set = True
        return True


class _FakeConn:
    def close(self):
        pass

    def rollback(self):
        pass


def _run(monkeypatch, sensor_score, camera_score, alert_due=True):
    """Run one iteration with the given published scores; return what it did."""
    writes = []
    cleared = []
    event = _OneShotEvent()

    monkeypatch.setattr(fusion_loop, "shutdown_event", event)
    monkeypatch.setattr(fusion_loop, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(fusion_loop, "is_detector_enabled", lambda z, t: True)
    monkeypatch.setattr(fusion_loop, "alert_due", lambda key, cooldown: alert_due)
    monkeypatch.setattr(fusion_loop, "clear_alert", lambda key: cleared.append(key))
    monkeypatch.setattr(
        fusion_loop, "write_alerts", lambda conn, alerts: writes.append(alerts)
    )

    fusion_loop.fusion_state[ZONE] = {
        "sensor_max_score": sensor_score,
        "camera_max_score": camera_score,
        "sensor_anomaly_count": 1 if sensor_score > 0 else 0,
    }
    try:
        fusion_loop.fusion_loop(ZONE)
    finally:
        fusion_loop.fusion_state.pop(ZONE, None)

    return writes, cleared, event


def test_a_sensor_only_flag_is_not_duplicated(monkeypatch):
    # The sensor loop already wrote this one; fusion must stay silent.
    writes, cleared, _ = _run(monkeypatch, sensor_score=0.983, camera_score=0.0)
    assert writes == []
    assert cleared == [f"fusion:{ZONE}"]


def test_a_camera_only_flag_is_not_duplicated(monkeypatch):
    writes, cleared, _ = _run(monkeypatch, sensor_score=0.0, camera_score=0.8)
    assert writes == []
    assert cleared == [f"fusion:{ZONE}"]


def test_both_modalities_write_exactly_one_cross_modal_alert(monkeypatch):
    writes, cleared, _ = _run(monkeypatch, sensor_score=0.9, camera_score=0.9)
    assert cleared == []
    assert len(writes) == 1
    alert = writes[0][0]
    assert alert["alert_type"] == "cross_modal"
    assert alert["score"] == 1.0 - (1.0 - 0.9) * (1.0 - 0.9)  # 0.99
    assert alert["source_id"] == f"zone_{ZONE}"


def test_the_cooldown_branch_waits_instead_of_spinning(monkeypatch):
    # Cross-modal but suppressed: no write, and the loop must still have waited
    # out the interval rather than `continue`-ing at full speed.
    writes, _, event = _run(
        monkeypatch, sensor_score=0.9, camera_score=0.9, alert_due=False
    )
    assert writes == []
    assert fusion_loop.FUSION_INTERVAL in event.timeouts
