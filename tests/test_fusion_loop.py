"""Tests for the fusion loop's alerting contract.

Fusion exists to combine the sensor and camera verdicts. Each of those already
has a loop that writes its own alerts, so fusion's only non-duplicate output is
the `cross_modal` alert — both modalities past their own cutoffs at once. The
loop used to write `sensor_anomaly` / `camera_anomaly` rows too, so a flag from
one modality came out twice; with the camera offline (`camera_score` always 0)
*every* sensor anomaly was written twice. These tests pin the contract: only
cross-modal fires, and the cooldown branch still waits instead of spinning.

What the loop reads is the *normalized margin* of each modality, not its raw
score — the modalities' units differ (a p-value vs a raw CKAAD score), so the
loops publish `sensor_margin` / `camera_margin` alongside the scores and fusion
comparing them against the per-zone sensitivity S is the only comparison that
means the same thing on both sides. The margin math itself is covered in
`test_detector_settings.py`; here the fixture publishes margins directly so the
decision path can be exercised in isolation.
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


def _run(monkeypatch, sensor_score, camera_score, alert_due=True,
         sensor_margin=None, camera_margin=None):
    """Run one iteration with the given published state; return what it did.

    Margins default to the raw scores: for the `both modalities` cases that
    puts each just past a zero cutoff, which is the corroboration case the
    default sensitivity S=0 admits.
    """
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
        "sensor_margin": sensor_score if sensor_margin is None else sensor_margin,
        "camera_margin": camera_score if camera_margin is None else camera_margin,
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


def test_loud_scores_with_no_margin_do_not_fire(monkeypatch):
    # The decision reads margins, not raw scores. Two 0.9s are only
    # corroboration if each is past its own cutoff; with both margins at 0
    # (at or under the cutoff) fusion must stay silent. The old `score > 0.3`
    # gate would have fired here, so this pins the change.
    writes, cleared, _ = _run(monkeypatch, sensor_score=0.9, camera_score=0.9,
                              sensor_margin=0.0, camera_margin=0.0)
    assert writes == []
    assert cleared == [f"fusion:{ZONE}"]


def test_margins_drive_the_fire_not_the_raw_scores(monkeypatch):
    # The converse: a modest raw score is a strong signal when it sits far
    # past its own cutoff. Two tiny scores with large margins fire where the
    # old absolute gate would not have.
    writes, cleared, _ = _run(monkeypatch, sensor_score=0.05, camera_score=0.05,
                              sensor_margin=0.9, camera_margin=0.9)
    assert cleared == []
    assert len(writes) == 1
    assert writes[0][0]["alert_type"] == "cross_modal"
