"""Tests for the detector's zero-variance guard and result storage.

An idle machine reports the same value on every channel, and M2AD's `area`
error standardises and rolls that flat residue, so the samples at every window
boundary come out extreme and get flagged — the "everything is anomalous"
reading on a machine that is simply sitting still. `_has_variation` is what the
loop uses to tell "no signal yet" from "something changed" and report idle
instead of scoring.

`_store_m2ad_results` has its own contract: one row per flagged timestep
(attributed to the channel that moved, not one row per channel per flag) and no
re-write of a timestep the loop already recorded on an earlier pass.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "anomaly"))

from detector import sensor_loop  # noqa: E402


def _flat(rows: int = 20) -> np.ndarray:
    value = np.array([930, 0, 1000, 0, 0, 0, 2, 300], dtype=np.float32)
    return np.tile(value, (rows, 1))


def test_a_flat_window_has_no_variation():
    assert sensor_loop._has_variation(_flat()) is False


def test_any_channel_moving_counts_as_variation():
    moving = _flat()
    moving[10, 3] = 5.0  # one sample, one channel
    assert sensor_loop._has_variation(moving) is True


def test_an_empty_window_has_no_variation():
    assert sensor_loop._has_variation(np.zeros((0, 8), dtype=np.float32)) is False


def test_alert_follows_detected_anomalies_not_the_score(monkeypatch):
    """A high normalized score with zero flagged samples must not alert.

    `anomaly_score` is `1 - p`, so a score of 0.31 is a p-value of 0.69 —
    ordinary variation. The old gate alerted on `max_score > 0.3`, i.e.
    `p < 0.7`, while the detector only called `p < 0.1` an anomaly. Alerts key
    off the detector's own `is_anomaly` count now.
    """
    calls = []
    monkeypatch.setattr(sensor_loop, "clear_alert", lambda key: calls.append(("clear", key)))
    monkeypatch.setattr(sensor_loop, "alert_due", lambda key, cooldown: True)
    monkeypatch.setattr(sensor_loop, "write_alerts", lambda conn, alerts: calls.append(("write", alerts)))

    sensor_loop._write_m2ad_alerts_if_needed(None, "zone", 0.95, 0, "run", [0.95])
    assert calls == [("clear", "sensor:zone")]


def test_alert_written_when_a_sample_is_flagged(monkeypatch):
    calls = []
    monkeypatch.setattr(sensor_loop, "clear_alert", lambda key: calls.append(("clear", key)))
    monkeypatch.setattr(sensor_loop, "alert_due", lambda key, cooldown: True)
    monkeypatch.setattr(sensor_loop, "write_alerts", lambda conn, alerts: calls.append(("write", alerts)))

    sensor_loop._write_m2ad_alerts_if_needed(None, "zone", 0.995, 2, "run", [0.995, 0.5])
    assert len(calls) == 1 and calls[0][0] == "write"
    alert = calls[0][1][0]
    assert alert["score"] == 0.995
    assert "2 anomalous" in alert["message"]


def test_m2ad_is_built_with_every_channel_as_a_sensor(monkeypatch):
    """The wrapper defaults to naming only the first column a sensor.

    Without an explicit `sensors` list the library treats column 0 as the one
    scored sensor and columns 1..7 as unscaled covariates, so the detector
    silently monitors one channel and duplicates its verdict across all eight.
    """
    import sys
    import types

    captured = {}

    class FakeM2AD:
        def __init__(self, dataset, **kwargs):
            captured["dataset"] = dataset
            captured.update(kwargs)

        def fit(self, data, progress_callback=None):
            captured["fit_shape"] = tuple(data.shape)
            return True

    fake_module = types.ModuleType("detection.sensor.anomaly")
    fake_module.M2AD = FakeM2AD
    monkeypatch.setitem(sys.modules, "detection.sensor.anomaly", fake_module)
    monkeypatch.setattr(sensor_loop, "update_train_state", lambda *a, **k: None)
    monkeypatch.setattr(sensor_loop, "clear_train", lambda *a, **k: None)

    channels = ["boiler_temp_c", "pump_pressure_bar", "water_tank", "coffee_level",
                "flow_rate_ml_s", "dispensed_ml", "state_code", "target_ml"]
    train_data = np.zeros((60, len(channels)), dtype=np.float32)
    detector = sensor_loop._train_m2ad_if_needed(
        None, "zone", channels, train_data, False, 0, window_size=5)

    assert detector is not None
    assert captured["sensors"] == channels
    assert captured["threshold"] == sensor_loop.SENSOR_PVALUE_THRESHOLD
    assert captured["error_name"] == "area"
    assert "covariates" not in captured or captured.get("covariates") is None
    assert captured["fit_shape"] == train_data.shape


def test_fusion_only_hears_about_detected_anomalies():
    """A clean run must not publish a score to the fusion loop.

    `anomaly_score` is `1 - p`, and fusion alerts at `sensor_max_score > 0.3`
    (`p < 0.7`). Publishing the raw score on a clean run therefore raised a
    fused `sensor_anomaly` alert for ordinary variation. With no flagged
    samples the sensor's contribution is zero.
    """
    sensor_loop.fusion_state.pop("zone", None)
    sensor_loop._update_fusion_sensor_state("zone", 0.71, 0)
    assert sensor_loop.fusion_state["zone"]["sensor_max_score"] == 0.0
    assert sensor_loop.fusion_state["zone"]["sensor_anomaly_count"] == 0

    sensor_loop._update_fusion_sensor_state("zone", 0.99, 3)
    assert sensor_loop.fusion_state["zone"]["sensor_max_score"] == 0.99
    assert sensor_loop.fusion_state["zone"]["sensor_anomaly_count"] == 3
    sensor_loop.fusion_state.pop("zone", None)


# --- _store_m2ad_results contract -----------------------------------------


class _FakeResult:
    def __init__(self, is_anomaly, score, sensor_pvalues=None):
        self.is_anomaly = is_anomaly
        self.anomaly_score = score
        self.details = {"sensor_pvalues": sensor_pvalues or {}}


class _FakeCursor:
    def __init__(self, existing):
        self.existing = list(existing)
        self.executed = []
        self._selected = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "SELECT timestamp" in sql:
            self._selected = [(t,) for t in self.existing]

    def fetchall(self):
        return self._selected

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, existing=()):
        self.cursor_obj = _FakeCursor(existing)

    def cursor(self):
        return self.cursor_obj

    def _inserts(self):
        return [p for sql, p in self.cursor_obj.executed if "INSERT" in sql]


def test_a_flag_is_one_row_attributed_to_the_moving_channel():
    """One multivariate flag must not become one row per channel.

    The fused p-value is identical across all eight channels, so a per-channel
    write made every detection look like eight simultaneous critical faults.
    The row goes to the lowest-p channel — the one that actually moved.
    """
    channels = ["boiler_temp_c", "water_tank", "state_code"]
    ts = [datetime(2026, 10, 5, 17, 15, 57, 331000, tzinfo=timezone.utc)]
    raw = np.array([[120.0, 0.5, 2.0]], dtype=np.float32)
    results = [_FakeResult(True, 0.995, {
        "boiler_temp_c": 0.4, "water_tank": 0.001, "state_code": 0.9})]
    conn = _FakeConn()

    sensor_loop._store_m2ad_results(
        conn, results, raw, ts, channels, "zone", "run", 0.5)

    inserts = conn._inserts()
    assert len(inserts) == 1
    source_id, _, _, timestamp, score, is_anomaly, value, details = inserts[0]
    assert source_id == "water_tank"
    assert timestamp == ts[0]
    assert score == 0.995
    assert is_anomaly is True
    assert value == 0.5  # raw value of the attributed channel
    assert json.loads(details)["sensor_pvalues"]["water_tank"] == 0.001


def test_a_rescanned_timestep_is_not_rewritten():
    """The loop re-scores the same trailing window every interval.

    Without dedupe each 30s pass re-inserted every still-flagged timestep with
    a fresh `now()`, so a persistent episode grew without bound.
    """
    channels = ["boiler_temp_c", "water_tank"]
    ts = [datetime(2026, 10, 5, 17, 15, 57, tzinfo=timezone.utc)]
    raw = np.array([[1.0, 2.0]], dtype=np.float32)
    results = [_FakeResult(True, 0.99, {"boiler_temp_c": 0.01, "water_tank": 0.5})]
    conn = _FakeConn(existing=ts)

    sensor_loop._store_m2ad_results(
        conn, results, raw, ts, channels, "zone", "run", 0.5)

    assert conn._inserts() == []


def test_clean_samples_and_duplicate_ts_within_a_pass_write_nothing_extra():
    channels = ["boiler_temp_c", "water_tank"]
    ts = [
        datetime(2026, 10, 5, 17, 15, 57, tzinfo=timezone.utc),
        datetime(2026, 10, 5, 17, 15, 57, tzinfo=timezone.utc),
    ]
    raw = np.array([[1.0, 2.0], [1.0, 2.0]], dtype=np.float32)
    results = [
        _FakeResult(False, 0.0, {}),  # clean -> skipped
        _FakeResult(True, 0.99, {"boiler_temp_c": 0.01, "water_tank": 0.5}),
        _FakeResult(True, 0.99, {"boiler_temp_c": 0.01, "water_tank": 0.5}),
    ]
    # Third result repeats the second's timestamp: only one row, not two.
    ts = [ts[0], ts[0], ts[0]]
    conn = _FakeConn()

    sensor_loop._store_m2ad_results(
        conn, results, raw, ts, channels, "zone", "run", 0.5)

    assert len(conn._inserts()) == 1
