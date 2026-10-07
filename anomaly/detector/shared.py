import logging
import math
import os
import threading
import time
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("detector.shared")

fusion_state: Dict[str, Dict[str, float]] = {}
fusion_lock = threading.Lock()

detector_enabled: Dict[str, bool] = {}
detector_enabled_lock = threading.Lock()

# Zones this detector actually runs loops for, from config.json. The API builds
# a Grafana dashboard per zone it has ever loaded, and a session that changes
# the zone name leaves the old dashboards behind: a Train press on one of those
# names a zone no loop reads, so the command is marked executed and its
# train_state sits "pending" forever. Control commands are resolved against
# this set so an unknown zone still reaches the loops that exist.
running_zones: set = set()
running_zones_lock = threading.Lock()


def register_zone(zone: str) -> None:
    with running_zones_lock:
        running_zones.add(zone)


def _resolve_command_zones(zone: str) -> List[str]:
    """The zones a control command should be applied to.

    A zone this detector runs is passed through unchanged. A zone it does NOT
    run is a dashboard left over from an earlier config; its command is applied
    to every running zone instead of to a name nothing listens on. An empty
    registry (before startup finishes) keeps the old behaviour and passes the
    name through, so a command issued in the first moments is not dropped.
    """
    if zone == "shared":
        # CKAAD trains under one key shared by every camera. It is not a config
        # zone, so it never appears in the registry and must not be rewritten to
        # a zone name the camera loop does not listen on.
        return ["shared"]
    with running_zones_lock:
        known = sorted(running_zones)
    if not known or zone in known:
        return [zone]
    logger.warning(
        f"Control: zone '{zone}' has no running detector loop; "
        f"applying to {known} (stale dashboard?)"
    )
    return known

train_events: Dict[str, threading.Event] = {}
train_events_lock = threading.Lock()

train_state: Dict[str, Dict[str, Any]] = {}
train_state_lock = threading.Lock()

# The last time each alert key was written. A sustained anomaly is one episode,
# not one alert per detection interval: without this, a score that stays above
# the threshold for an hour writes 120 alerts. `clear_alert` drops the key when
# the condition goes away, so the cooldown is per episode rather than a window
# that would swallow the next, unrelated anomaly.
alert_cooldowns: Dict[str, float] = {}
alert_cooldowns_lock = threading.Lock()


def alert_due(key: str, cooldown_s: float) -> bool:
    """Whether an alert for `key` may be written now, and if so, claim it.

    `cooldown_s` of 0 means no cooldown at all: every call is due.
    """
    if cooldown_s <= 0:
        return True
    now = time.time()
    with alert_cooldowns_lock:
        last = alert_cooldowns.get(key)
        if last is not None and now - last < cooldown_s:
            return False
        alert_cooldowns[key] = now
        return True


def clear_alert(key: str) -> None:
    """Forget `key`'s cooldown so a later anomaly alerts immediately again."""
    with alert_cooldowns_lock:
        alert_cooldowns.pop(key, None)


def alert_active(key: str) -> bool:
    """Whether an alert episode for `key` is currently open.

    An armed cooldown means a flag fired and has not been cleared by a
    subsequent clean pass, so an anomaly is still (or just was) present. The
    sensor loop uses this to hold off a periodic refit while the machine is
    misbehaving.
    """
    with alert_cooldowns_lock:
        return key in alert_cooldowns


def update_train_state(zone: str, detector_type: str, status: str,
                       progress: str = "", message: str = ""):
    key = f"{zone}:{detector_type}"
    with train_state_lock:
        now = time.time()
        if key not in train_state:
            train_state[key] = {"started_at": now}
        train_state[key].update({
            "status": status,
            "progress": progress,
            "message": message,
            "updated_at": now,
        })


def get_train_state_snapshot() -> Dict[str, Dict[str, Any]]:
    with train_state_lock:
        return {k: dict(v) for k, v in train_state.items()}


def update_train_samples(zone: str, detector_type: str, available: int,
                         target: Optional[int] = None,
                         interval_s: Optional[float] = None) -> None:
    """Publish how much data is available to train on, for the control page.

    The page shows this so a `min_train_samples` can be chosen against the data
    that actually exists rather than guessed. Kept separate from
    `update_train_state` so a status/message written by the training path is not
    clobbered by a bare count, and `updated_at` (the status stamp) is left
    alone. `interval_s` is the seconds between detection runs, from which the
    page derives the wall-clock meaning of `retrain_every` (which counts runs).
    """
    key = f"{zone}:{detector_type}"
    with train_state_lock:
        entry = train_state.setdefault(key, {
            "started_at": time.time(), "status": "idle",
            "progress": "", "message": "", "updated_at": time.time(),
        })
        entry["available_samples"] = available
        if target is not None:
            entry["target_samples"] = target
        if interval_s is not None:
            entry["detect_interval_s"] = interval_s


def is_detector_enabled(zone: str, detector_type: str) -> bool:
    with detector_enabled_lock:
        return detector_enabled.get(f"{zone}:{detector_type}", True)


def set_detector_enabled(zone: str, detector_type: str, enabled: bool):
    with detector_enabled_lock:
        detector_enabled[f"{zone}:{detector_type}"] = enabled


# --- runtime settings -------------------------------------------------------
#
# The loops used to read their train floor, retrain cadence and threshold from
# module-level env vars at import, so nothing could be changed without a
# rebuild. These are mirrored from the `detector_settings` table the control
# page writes and read through `get_setting`, so a change lands on the next
# poll. A key with no row (or a NULL column) keeps its built-in default, which
# is the env-var value the loops used before the control page existed — an
# untouched stack behaves exactly as it did.
_SETTING_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "m2ad": {
        "enabled": True,
        "auto_retrain": True,
        "min_train_samples": int(os.environ.get("SENSOR_MIN_TRAIN_READINGS", "150")),
        "retrain_every": int(os.environ.get("SENSOR_RETRAIN_EVERY", "10")),
        "pvalue_threshold": float(os.environ.get("SENSOR_PVALUE_THRESHOLD", "0.005")),
    },
    "ckaad": {
        "enabled": True,
        "auto_retrain": True,
        "min_train_samples": int(os.environ.get("CAMERA_MIN_TRAINING_FRAMES", "200")),
        "retrain_every": int(os.environ.get("CAMERA_RETRAIN_EVERY", "50")),
        # CKAAD's cutoff is a percentile of the fitted error distribution, not a
        # p-value, so it is not exposed as a tunable here.
        "pvalue_threshold": None,
        # Absolute score cutoff, per zone (a `shared` row is the fallback for
        # zones that have none). NULL means "use the model's calibrated value".
        "score_threshold": None,
    },
    # The cross-modal fusion `score_threshold` column carries the sensitivity
    # S, not a score: fusion fires when the SMALLER of the two normalized
    # margins (sensor and camera) is strictly greater than S. 0 is the
    # corroboration default — both modalities must be past their own cutoff.
    "fusion": {
        "score_threshold": 0.0,
    },
}

SETTING_KEYS = (
    "enabled",
    "auto_retrain",
    "min_train_samples",
    "retrain_every",
    "pvalue_threshold",
    "score_threshold",
)

detector_settings: Dict[str, Dict[str, Any]] = {}
detector_settings_lock = threading.Lock()


def get_setting(zone: str, detector_type: str, key: str):
    """The effective value of one runtime setting.

    A row the control page wrote wins; a NULL column (or no row at all) falls
    back to the built-in default.
    """
    with detector_settings_lock:
        row = detector_settings.get(f"{zone}:{detector_type}")
    if row is not None:
        value = row.get(key)
        if value is not None:
            return value
    return _SETTING_DEFAULTS.get(detector_type, {}).get(key)


def get_ckaad_setting(key: str):
    """CKAAD is one global model, so its settings all live under `shared`."""
    return get_setting("shared", "ckaad", key)


def get_ckaad_alert_threshold(zone: str, calibrated: float) -> float:
    """Effective absolute alert cutoff for one camera zone.

    CKAAD is a single shared model, but the raw score that separates a normal
    brew from a real fault is camera-specific, so a threshold set for `zone`
    wins. With none, the `shared` fallback applies to every zone; with neither,
    the model's own calibrated value is used. This is the one cutoff the alert
    gate, the frame-saving gate and `is_anomaly` all consult.
    """
    per_zone = get_setting(zone, "ckaad", "score_threshold")
    if per_zone is not None:
        return float(per_zone)
    shared = get_ckaad_setting("score_threshold")
    if shared is not None:
        return float(shared)
    return float(calibrated)


# How many decades below the p-value cutoff a flagged sensor reading can sit
# and still count as a full-strength corroboration. Two decades (e.g. p=5e-5
# against a 0.005 cutoff) is far past anything the detector calls ordinary.
FUSION_SENSOR_DECADES = 2.0


def sensor_margin(pvalue_threshold: float, max_score: float) -> float:
    """How far past its own cutoff an M2AD flag sits, normalized to [0, 1].

    `max_score` is `1 - p`, so `min_p = 1 - max_score` is the smallest
    p-value this run produced. The margin is the number of decades `min_p`
    falls below `pvalue_threshold`, scaled so `FUSION_SENSOR_DECADES` maps to
    1. A run at or above the cutoff, or a clean run (score 0), scores 0.
    """
    if max_score <= 0.0 or pvalue_threshold <= 0.0:
        return 0.0
    min_p = max(1.0 - float(max_score), 1e-12)
    if min_p >= pvalue_threshold:
        return 0.0
    decades = math.log10(float(pvalue_threshold) / min_p)
    return max(0.0, min(1.0, decades / FUSION_SENSOR_DECADES))


def ckaad_margin(score: float, threshold: Optional[float]) -> float:
    """How far past its own cutoff a CKAAD score sits, normalized to [0, 1].

    Uses the camera's *effective* per-zone cutoff, so the fusion gate follows
    the control page's threshold instead of an absolute score. At or below
    `threshold` the margin is 0; twice the cutoff saturates at 1.
    """
    if threshold is None or threshold <= 0.0:
        return 0.0
    return max(0.0, min(1.0, float(score) / float(threshold) - 1.0))


def fusion_should_fire(sensor_margin_value: float, camera_margin_value: float,
                       sensitivity: float) -> bool:
    """Whether both modalities corroborate at the given sensitivity.

    The decision uses the SMALLER margin, not a noisy-OR: noisy-OR is OR-like
    and would let a single strong modality fire, which is exactly what fusion
    is supposed to rule out. The comparison is strict, so S = 0 still requires
    both margins to be past zero.
    """
    return min(float(sensor_margin_value), float(camera_margin_value)) > float(sensitivity)


def get_fusion_sensitivity(zone: str) -> float:
    """The per-zone cross-modal sensitivity S."""
    value = get_setting(zone, "fusion", "score_threshold")
    return float(value) if value is not None else 0.0


def poll_detector_settings(conn) -> bool:
    """Mirror the `detector_settings` table into this process.

    Returns True when the read succeeded (with or without rows). Never raises:
    a settings read failing must not take the control-command poll down with it.
    """
    try:
        rows = _fetch_detector_settings(conn)
    except Exception as e:
        logger.error(f"Settings poll error: {e}", exc_info=True)
        try:
            conn.rollback()
        except Exception:
            pass
        return False

    # Release the read transaction for the same reason as poll_control_commands:
    # the loop reuses this connection, and an open read transaction pins locks.
    conn.rollback()

    parsed = {}
    for row in rows:
        key = f"{row['zone_name']}:{row['detector_type']}"
        parsed[key] = {k: row.get(k) for k in SETTING_KEYS}
    with detector_settings_lock:
        detector_settings.clear()
        detector_settings.update(parsed)

    for row in rows:
        _apply_setting_enabled(row)
    return True


def _fetch_detector_settings(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT zone_name, detector_type, enabled, auto_retrain,
                      min_train_samples, retrain_every, pvalue_threshold,
                      score_threshold
               FROM detector_settings"""
        )
        return cur.fetchall()


def _apply_setting_enabled(row) -> None:
    """Apply a settings row's `enabled` to the in-memory detector switches.

    CKAAD is stored once under `shared`, but `camera_loop` asks whether ckaad is
    enabled per camera zone, so a shared toggle is fanned out to every running
    zone as well as `shared` itself. Without that, disabling CKAAD from the
    control page changed a key nothing consulted and the model kept scoring.
    """
    enabled = row.get("enabled")
    if enabled is None:
        return
    zone = row["zone_name"]
    dtype = row["detector_type"]
    if dtype == "ckaad" and zone == "shared":
        with running_zones_lock:
            zones = sorted(running_zones)
        for z in zones:
            set_detector_enabled(z, "ckaad", bool(enabled))
        set_detector_enabled("shared", "ckaad", bool(enabled))
    else:
        set_detector_enabled(zone, dtype, bool(enabled))


def signal_train(zone: str, detector_type: str):
    key = f"{zone}:{detector_type}"
    with train_events_lock:
        if key not in train_events:
            train_events[key] = threading.Event()
        train_events[key].set()


def train_requested(zone: str, detector_type: str) -> bool:
    """Whether a Train press is outstanding for this detector.

    A request is durable: `signal_train` sets it and only `clear_train`, which a
    loop calls after a fit actually succeeds, takes it back. A press that lands
    before there is enough collected data therefore stays outstanding until the
    loop can honour it, instead of being spent on an empty read and lost.
    """
    with train_events_lock:
        ev = train_events.get(f"{zone}:{detector_type}")
        return bool(ev and ev.is_set())


def clear_train(zone: str, detector_type: str) -> None:
    with train_events_lock:
        ev = train_events.get(f"{zone}:{detector_type}")
        if ev:
            ev.clear()


def poll_control_commands(conn):
    try:
        rows = _fetch_pending_commands(conn)
        if not rows:
            # The SELECT opened a transaction implicitly. Left open, this
            # connection sits "idle in transaction" holding an ACCESS SHARE
            # lock on detector_control, which blocks the API's startup
            # `DROP TRIGGER` (ACCESS EXCLUSIVE) and hangs boot. End it here.
            conn.rollback()
            return False

        for row in rows:
            cmd_id = row["id"]
            zone = row["zone_name"]
            dtype = row["detector_type"]
            command = row["command"]

            if command == "train":
                _handle_train_command(zone, dtype)
            elif command in ("enable", "disable"):
                _handle_enable_disable_command(zone, dtype, command)
            elif command == "reset":
                _handle_reset_command(zone, dtype)

            _mark_command_executed(conn, cmd_id)

        return True
    except Exception as e:
        logger.error(f"Control poll error: {e}", exc_info=True)
        conn.rollback()
        return False


def _fetch_pending_commands(conn):
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT id, zone_name, detector_type, command
               FROM detector_control
               WHERE executed_at IS NULL
               ORDER BY issued_at ASC
               LIMIT 50"""
        )
        return cur.fetchall()


def _mark_command_executed(conn, cmd_id):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE detector_control SET executed_at = NOW() WHERE id = %s",
            (cmd_id,),
        )
    conn.commit()


def _handle_train_command(zone, dtype):
    if zone == "*" and dtype == "*":
        with train_events_lock:
            for key in list(train_events.keys()):
                train_events[key].set()
    elif zone == "*":
        with train_events_lock:
            for key in list(train_events.keys()):
                if key.endswith(f":{dtype}"):
                    train_events[key].set()
    elif dtype == "*":
        with train_events_lock:
            for key in list(train_events.keys()):
                if key.startswith(f"{zone}:"):
                    train_events[key].set()
    else:
        targets = _resolve_command_zones(zone)
        # A phantom zone is one no loop runs; drop the train_state it had
        # accumulated so the dashboard falls back to the running zone's state
        # and a Train press shows real progress instead of a "pending" that
        # never moves.
        if zone not in targets:
            with train_state_lock:
                train_state.pop(f"{zone}:{dtype}", None)
        for target in targets:
            signal_train(target, dtype)
            update_train_state(target, dtype, "pending", progress="0%", message="Queued")

    logger.info(f"Control: train signaled for {zone}:{dtype}")


def _handle_enable_disable_command(zone, dtype, command):
    enabled = command == "enable"
    if zone == "*" and dtype == "*":
        with detector_enabled_lock:
            for key in list(detector_enabled.keys()):
                detector_enabled[key] = enabled
    elif zone == "*":
        with detector_enabled_lock:
            for key in list(detector_enabled.keys()):
                if key.endswith(f":{dtype}"):
                    detector_enabled[key] = enabled
    elif dtype == "*":
        for target in _resolve_command_zones(zone):
            set_detector_enabled(target, "m2ad", enabled)
            set_detector_enabled(target, "ckaad", enabled)
            set_detector_enabled(target, "fusion", enabled)
        logger.info(f"Control: {'enabled' if enabled else 'disabled'} all detectors for {zone}")
    else:
        for target in _resolve_command_zones(zone):
            set_detector_enabled(target, dtype, enabled)

    logger.info(f"Control: {command} for {zone}:{dtype}")


def _handle_reset_command(zone, dtype):
    if zone == "*" and dtype == "*":
        with train_state_lock:
            for key in list(train_state.keys()):
                train_state[key] = {"status": "idle", "progress": "", "message": "Reset", "updated_at": time.time()}
    elif zone == "*":
        with train_state_lock:
            for key in list(train_state.keys()):
                if key.endswith(f":{dtype}"):
                    train_state[key] = {"status": "idle", "progress": "", "message": "Reset", "updated_at": time.time()}
    elif dtype == "*":
        with train_state_lock:
            for key in list(train_state.keys()):
                if key.startswith(f"{zone}:"):
                    train_state[key] = {"status": "idle", "progress": "", "message": "Reset", "updated_at": time.time()}
    else:
        targets = _resolve_command_zones(zone)
        if zone not in targets:
            with train_state_lock:
                train_state.pop(f"{zone}:{dtype}", None)
        for target in targets:
            update_train_state(target, dtype, "idle", progress="", message="Reset")
    logger.info(f"Control: reset training state for {zone}:{dtype}")


shutdown_event = threading.Event()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://anomalydb:anomalydb@postgres:5432/anomaly_db",
)
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_API_KEY = os.environ.get("GRAFANA_API_KEY", "")
# Where the RTSP capture loop writes frames and CKAAD reads them. The old name
# was `/tmp/mvtec_frames`, from the Kaggle MVTec stills that used to be the
# demo's "live" feed; the frames are the user's cameras now.
FRAME_DIR = os.environ.get("FRAME_DIR", "/tmp/anomaly_frames")
# The anomaly API as a *browser* reaches it: the alert panels link to the
# frame routes stored under this base. Inside the compose network the API is
# on port 8000, but the browser is on the user's machine, where the stack
# publishes it on 8001.
ANOMALY_API_PUBLIC_URL = os.environ.get(
    "ANOMALY_API_PUBLIC_URL", "http://localhost:8001"
).rstrip("/")


def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def get_zone_dashboard_uids(conn, zone_names: List[str]) -> Dict[str, Optional[str]]:
    if not zone_names:
        return {}
    result = {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT z.name, d.grafana_uid
               FROM zones z
               LEFT JOIN dashboard_definitions d ON d.zone_id = z.id
               WHERE z.name = ANY(%s)""",
            (zone_names,),
        )
        for row in cur.fetchall():
            result[row["name"]] = row.get("grafana_uid")
    return result


def fire_grafana_annotation(
    dashboard_uid: str,
    text: str,
    tags: List[str],
):
    if not GRAFANA_URL:
        return
    try:
        import requests
        from requests.auth import HTTPBasicAuth

        payload = {
            "dashboardUID": dashboard_uid,
            "text": text,
            "tags": tags,
            "time": int(time.time() * 1000),
        }
        headers = {"Content-Type": "application/json"}
        if GRAFANA_API_KEY:
            headers["Authorization"] = f"Bearer {GRAFANA_API_KEY}"
        auth = HTTPBasicAuth(
            os.environ.get("GRAFANA_USER", "admin"),
            os.environ.get("GRAFANA_PASSWORD", "admin"),
        )
        resp = requests.post(
            f"{GRAFANA_URL}/api/annotations",
            json=payload,
            headers=headers,
            auth=auth,
            timeout=5,
        )
        if resp.status_code not in (200, 201, 409):
            logger.warning(
                f"Annotation failed: {resp.status_code} {resp.text[:200]}"
            )
    except Exception as e:
        logger.warning(f"Failed to fire annotation: {e}")


def write_alerts(conn, alerts: List[Dict[str, Any]]):
    if not alerts:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO alerts (source_id, alert_type, severity, message, score, run_id)
               VALUES (%(source_id)s, %(alert_type)s, %(severity)s, %(message)s, %(score)s, %(run_id)s)""",
            alerts,
        )
    conn.commit()


SEVERITY_ORDER = ["low", "medium", "high", "critical"]


def compute_severity(score: float) -> str:
    if score >= 0.8:
        return "critical"
    elif score >= 0.6:
        return "high"
    elif score >= 0.3:
        return "medium"
    else:
        return "low"


def bump_severity(sev: str) -> str:
    idx = SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else 0
    return SEVERITY_ORDER[min(idx + 1, len(SEVERITY_ORDER) - 1)]
