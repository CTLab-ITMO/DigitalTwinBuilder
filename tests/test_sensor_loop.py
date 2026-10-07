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
        None, "zone", channels, train_data, [], False, 0, window_size=5,
        periodic_ok=False, conn=None)

    assert detector is not None
    assert captured["sensors"] == channels
    assert captured["threshold"] == sensor_loop.SENSOR_PVALUE_THRESHOLD
    assert captured["error_name"] == "area"
    assert "covariates" not in captured or captured.get("covariates") is None
    assert captured["fit_shape"] == train_data.shape


def test_fusion_only_hears_about_detected_anomalies():
    """A clean run must not publish a score or margin to the fusion loop.

    `anomaly_score` is `1 - p`. Fusion now keys off a normalized margin over
    the sensor's own cutoff, but a run that flagged nothing must still
    contribute zero, or ordinary variation would corroborate a camera event.
    With no flagged samples both the score and the margin are zero.
    """
    sensor_loop.fusion_state.pop("zone", None)
    sensor_loop._update_fusion_sensor_state("zone", 0.71, 0, 0.005)
    assert sensor_loop.fusion_state["zone"]["sensor_max_score"] == 0.0
    assert sensor_loop.fusion_state["zone"]["sensor_margin"] == 0.0
    assert sensor_loop.fusion_state["zone"]["sensor_anomaly_count"] == 0

    sensor_loop._update_fusion_sensor_state("zone", 0.99, 3, 0.005)
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


# --- flagged-row exclusion + periodic-retrain gate -------------------------


class _FlagCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return [(t,) for t in self.rows]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FlagConn:
    def __init__(self, flagged=()):
        self.flagged = list(flagged)
        self.rolled = False
        self.cursor_obj = _FlagCursor(self.flagged)

    def cursor(self):
        return self.cursor_obj

    def rollback(self):
        self.rolled = True


def _ts20():
    return [f"2026-10-05T20:{i:02d}:00" for i in range(20)]


def test_flagged_rows_are_dropped_from_the_training_slice():
    """A reading the detector already flagged must not be fitted as baseline.

    Otherwise a caught fault ages out of the scored slice into the training
    slice and a later refit learns "fault = normal", silently degrading
    detection of that fault from then on.
    """
    ts = _ts20()
    data = np.arange(20 * 3, dtype=np.float32).reshape(20, 3)
    conn = _FlagConn(flagged={ts[5], ts[6]})

    out = sensor_loop._drop_flagged_rows(conn, "zone", data, ts, window_size=3)

    assert out.shape[0] == 18
    kept = {tuple(r) for r in out.tolist()}
    assert tuple(data[5]) not in kept and tuple(data[6]) not in kept
    assert tuple(data[4]) in kept and tuple(data[7]) in kept
    # The lookup is bounded to the training slice: from the first timestamp,
    # for this zone, m2ad rows only.
    assert conn.cursor_obj.params == ("zone", ts[0])


def test_flagged_rows_kept_when_dropping_would_starve_the_fit():
    """Exclusion yields to the fit rather than failing it.

    The window was sized to the full slice, so a slice dominated by flagged
    rows is trained on in full this round (with a warning) instead of dropping
    below the minimum the fit needs and failing outright.
    """
    ts = _ts20()
    data = np.arange(20 * 3, dtype=np.float32).reshape(20, 3)
    # window 3 + MIN_FIT_SAMPLES 9 + 1 = 13; dropping all but one -> 1 < 13.
    conn = _FlagConn(flagged=ts[:-1])

    out = sensor_loop._drop_flagged_rows(conn, "zone", data, ts, window_size=3)

    assert out.shape[0] == 20


def test_no_flagged_rows_leaves_the_slice_unchanged():
    ts = _ts20()
    data = np.arange(20 * 3, dtype=np.float32).reshape(20, 3)

    out = sensor_loop._drop_flagged_rows(_FlagConn(flagged=()), "zone", data, ts, window_size=3)

    assert out.shape[0] == 20


def test_flagged_lookup_failure_falls_back_to_the_full_slice():
    """A failed lookup must not take the training slice down with it."""

    class _Boom(_FlagConn):
        def cursor(self):
            raise RuntimeError("db down")

    ts = _ts20()
    data = np.arange(20 * 3, dtype=np.float32).reshape(20, 3)
    conn = _Boom()

    out = sensor_loop._drop_flagged_rows(conn, "zone", data, ts, window_size=3)

    assert out.shape[0] == 20
    assert conn.rolled is True


def test_periodic_refit_is_skipped_while_the_gate_is_closed(monkeypatch):
    """A periodic boundary with `periodic_ok=False` keeps the current model.

    The gate is what holds a refit off while an anomaly episode is open; the
    first fit and a manual Train pass `periodic_ok`/`retrain_requested`
    independently, so only the periodic path is affected.
    """
    import types
    fitted = []

    class FakeM2AD:
        def __init__(self, dataset, **kwargs):
            pass

        def fit(self, data, progress_callback=None):
            fitted.append(tuple(data.shape))
            return True

    fake_module = types.ModuleType("detection.sensor.anomaly")
    fake_module.M2AD = FakeM2AD
    monkeypatch.setitem(sys.modules, "detection.sensor.anomaly", fake_module)
    monkeypatch.setattr(sensor_loop, "update_train_state", lambda *a, **k: None)
    monkeypatch.setattr(sensor_loop, "clear_train", lambda *a, **k: None)

    channels = ["boiler_temp_c", "water_tank"]
    train_data = np.zeros((60, 2), dtype=np.float32)
    existing = object()
    boundary = sensor_loop.RETRAIN_EVERY

    kept = sensor_loop._train_m2ad_if_needed(
        existing, "zone", channels, train_data, [], False, boundary, 5,
        periodic_ok=False, conn=None)
    assert kept is existing
    assert fitted == []

    refit = sensor_loop._train_m2ad_if_needed(
        existing, "zone", channels, train_data, [], False, boundary, 5,
        periodic_ok=True, conn=None)
    assert refit is not existing
    assert fitted == [(60, 2)]


def _fake_m2ad(monkeypatch, captured):
    import types

    class FakeM2AD:
        def __init__(self, dataset, **kwargs):
            captured.update(kwargs)

        def fit(self, data, progress_callback=None):
            captured["fitted"] = captured.get("fitted", 0) + 1
            return True

    fake_module = types.ModuleType("detection.sensor.anomaly")
    fake_module.M2AD = FakeM2AD
    monkeypatch.setitem(sys.modules, "detection.sensor.anomaly", fake_module)
    monkeypatch.setattr(sensor_loop, "update_train_state", lambda *a, **k: None)
    monkeypatch.setattr(sensor_loop, "clear_train", lambda *a, **k: None)


def test_runtime_retrain_every_overrides_the_module_cadence(monkeypatch):
    """The control page's `retrain_every` is what decides the periodic boundary.

    `run_count=2` is a boundary for the runtime value of 2 but not for the
    module default of 10, so a refit here proves the runtime value was used.
    """
    captured = {}
    _fake_m2ad(monkeypatch, captured)

    existing = object()
    data = np.zeros((60, 2), dtype=np.float32)
    refit = sensor_loop._train_m2ad_if_needed(
        existing, "zone", ["a", "b"], data, [], False, 2, 5,
        periodic_ok=True, conn=None, retrain_every=2)

    assert refit is not existing
    assert captured["fitted"] == 1


def test_runtime_pvalue_threshold_reaches_the_model(monkeypatch):
    captured = {}
    _fake_m2ad(monkeypatch, captured)

    sensor_loop._train_m2ad_if_needed(
        None, "zone", ["a"], np.zeros((60, 1), dtype=np.float32), [],
        False, 0, 5, periodic_ok=False, conn=None, pvalue_threshold=0.123)

    assert captured["threshold"] == 0.123
