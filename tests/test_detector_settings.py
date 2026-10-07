"""Tests for the detector's runtime settings store.

The control page on the anomaly API writes `detector_settings`; the detector
mirrors those rows into its process through `poll_detector_settings` and the
loops read them via `get_setting`. These cover the three things that matter:
a NULL/absent value falls back to the built-in default (so an untouched stack
behaves as before), a written value wins, and a CKAAD toggle under the `shared`
pseudo-zone reaches the per-zone switches the camera loop actually reads.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "anomaly"))

from detector import shared  # noqa: E402


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, cursor_factory=None):
        return _Cursor(self.rows)

    def rollback(self):
        pass


def _row(**overrides):
    base = {
        "zone_name": "zone",
        "detector_type": "m2ad",
        "enabled": None,
        "auto_retrain": None,
        "min_train_samples": None,
        "retrain_every": None,
        "pvalue_threshold": None,
        "score_threshold": None,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _restore_state():
    """Snapshot and restore the module globals each test mutates."""
    with shared.detector_settings_lock:
        settings = dict(shared.detector_settings)
    with shared.detector_enabled_lock:
        enabled = dict(shared.detector_enabled)
    with shared.running_zones_lock:
        zones = set(shared.running_zones)
    yield
    with shared.detector_settings_lock:
        shared.detector_settings.clear()
        shared.detector_settings.update(settings)
    with shared.detector_enabled_lock:
        shared.detector_enabled.clear()
        shared.detector_enabled.update(enabled)
    with shared.running_zones_lock:
        shared.running_zones.clear()
        shared.running_zones.update(zones)


def test_defaults_apply_when_nothing_is_configured():
    with shared.detector_settings_lock:
        shared.detector_settings.clear()

    assert shared.get_setting("zone", "m2ad", "min_train_samples") == 150
    assert shared.get_setting("zone", "m2ad", "retrain_every") == 10
    assert shared.get_setting("zone", "m2ad", "pvalue_threshold") == 0.005
    assert shared.get_setting("zone", "m2ad", "enabled") is True
    assert shared.get_ckaad_setting("min_train_samples") == 200
    assert shared.get_ckaad_setting("retrain_every") == 50


def test_a_written_row_overrides_the_default():
    shared.poll_detector_settings(_Conn([
        _row(min_train_samples=40, retrain_every=3, auto_retrain=False,
             pvalue_threshold=0.02, enabled=False),
    ]))

    assert shared.get_setting("zone", "m2ad", "min_train_samples") == 40
    assert shared.get_setting("zone", "m2ad", "retrain_every") == 3
    assert shared.get_setting("zone", "m2ad", "auto_retrain") is False
    assert shared.get_setting("zone", "m2ad", "pvalue_threshold") == 0.02
    assert shared.is_detector_enabled("zone", "m2ad") is False


def test_null_columns_fall_back_to_their_defaults():
    """"Unset" is a NULL column, not false/zero, so it must not win."""
    shared.poll_detector_settings(_Conn([_row(min_train_samples=None)]))

    assert shared.get_setting("zone", "m2ad", "min_train_samples") == 150
    assert shared.get_setting("zone", "m2ad", "enabled") is True


def test_ckaad_toggle_fans_out_to_the_running_zones():
    """The camera loop checks `<zone>:ckaad`, but CKAAD is stored under
    `shared`; without the fan-out a control-page toggle changed a key nothing
    read and the model kept scoring."""
    shared.register_zone("boiler_zone")
    shared.set_detector_enabled("boiler_zone", "ckaad", True)

    shared.poll_detector_settings(_Conn([
        _row(zone_name="shared", detector_type="ckaad", enabled=False),
    ]))

    assert shared.is_detector_enabled("boiler_zone", "ckaad") is False
    assert shared.is_detector_enabled("shared", "ckaad") is False


def test_settings_for_a_removed_row_stop_applying():
    """A cleared table leaves the built-in defaults in force."""
    shared.poll_detector_settings(_Conn([_row(min_train_samples=40)]))
    assert shared.get_setting("zone", "m2ad", "min_train_samples") == 40

    shared.poll_detector_settings(_Conn([]))
    assert shared.get_setting("zone", "m2ad", "min_train_samples") == 150


def test_ckaad_threshold_prefers_zone_then_shared_then_calibrated():
    """The one cutoff the camera loop's gates share: a per-zone override beats
    the `shared` fallback, which beats the model's own calibrated value."""
    with shared.detector_settings_lock:
        shared.detector_settings.clear()
    # Nothing configured -> the calibrated value passes straight through.
    assert shared.get_ckaad_alert_threshold("zone", 0.42) == 0.42

    # A shared fallback reaches a zone with no override of its own.
    shared.poll_detector_settings(_Conn([
        _row(zone_name="shared", detector_type="ckaad", score_threshold=0.6),
    ]))
    assert shared.get_ckaad_alert_threshold("zone", 0.42) == 0.6

    # A per-zone override wins for that zone only.
    shared.poll_detector_settings(_Conn([
        _row(zone_name="shared", detector_type="ckaad", score_threshold=0.6),
        _row(zone_name="zone", detector_type="ckaad", score_threshold=0.75),
    ]))
    assert shared.get_ckaad_alert_threshold("zone", 0.42) == 0.75
    assert shared.get_ckaad_alert_threshold("other", 0.42) == 0.6


def test_poll_failure_is_swallowed():
    class _Boom(_Conn):
        def cursor(self, cursor_factory=None):
            raise RuntimeError("db down")

    assert shared.poll_detector_settings(_Boom([])) is False


def test_fusion_sensitivity_defaults_to_zero_and_is_overridable():
    """Fusion's `score_threshold` is a sensitivity, not a score; the untouched
    stack corroborates at 0 and a written row lifts it for that zone only."""
    with shared.detector_settings_lock:
        shared.detector_settings.clear()
    assert shared.get_fusion_sensitivity("zone") == 0.0

    shared.poll_detector_settings(_Conn([
        _row(zone_name="zone", detector_type="fusion", score_threshold=0.4),
    ]))
    assert shared.get_fusion_sensitivity("zone") == 0.4
    assert shared.get_fusion_sensitivity("other") == 0.0


def test_sensor_margin_measures_decades_below_the_cutoff():
    # No flag, or a flag exactly at the cutoff, has no margin.
    assert shared.sensor_margin(0.005, 0.0) == 0.0
    assert shared.sensor_margin(0.005, 0.995) == 0.0
    # A p one decade under the cutoff is half of the two-decade scale.
    assert shared.sensor_margin(0.005, 1 - 0.0005) == pytest.approx(0.5)
    # Two decades under saturates.
    assert shared.sensor_margin(0.005, 1 - 0.00005) == pytest.approx(1.0)


def test_ckaad_margin_is_relative_to_the_effective_cutoff():
    assert shared.ckaad_margin(0.5, 0.7) == 0.0
    assert shared.ckaad_margin(0.7, 0.7) == 0.0
    assert shared.ckaad_margin(1.05, 0.7) == pytest.approx(0.5)
    assert shared.ckaad_margin(1.4, 0.7) == pytest.approx(1.0)
    # A raised cutoff raises the bar; the same score now has no margin.
    assert shared.ckaad_margin(0.8, 1.6) == 0.0
    assert shared.ckaad_margin(0.8, 0.0) == 0.0


def test_fusion_requires_both_margins_to_clear_sensitivity():
    # S = 0: both just past their boundary fires; either at the boundary does not.
    assert shared.fusion_should_fire(0.1, 0.1, 0.0) is True
    assert shared.fusion_should_fire(0.1, 0.0, 0.0) is False
    assert shared.fusion_should_fire(0.0, 0.1, 0.0) is False
    # A loud modality cannot fire on its own...
    assert shared.fusion_should_fire(0.9, 0.0, 0.0) is False
    # ...nor drag a weak one over a sensitivity it does not clear.
    assert shared.fusion_should_fire(0.9, 0.05, 0.1) is False
    # Strict comparison: a margin equal to S does not fire.
    assert shared.fusion_should_fire(0.5, 0.5, 0.5) is False
    assert shared.fusion_should_fire(0.6, 0.6, 0.5) is True
