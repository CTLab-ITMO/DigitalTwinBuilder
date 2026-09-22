import logging
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

train_events: Dict[str, threading.Event] = {}
train_events_lock = threading.Lock()

train_state: Dict[str, Dict[str, Any]] = {}
train_state_lock = threading.Lock()


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


def is_detector_enabled(zone: str, detector_type: str) -> bool:
    with detector_enabled_lock:
        return detector_enabled.get(f"{zone}:{detector_type}", True)


def set_detector_enabled(zone: str, detector_type: str, enabled: bool):
    with detector_enabled_lock:
        detector_enabled[f"{zone}:{detector_type}"] = enabled


def signal_train(zone: str, detector_type: str):
    key = f"{zone}:{detector_type}"
    with train_events_lock:
        if key not in train_events:
            train_events[key] = threading.Event()
        train_events[key].set()


def check_and_clear_train(zone: str, detector_type: str) -> bool:
    key = f"{zone}:{detector_type}"
    with train_events_lock:
        ev = train_events.get(key)
        if ev and ev.is_set():
            ev.clear()
            return True
        return False


def poll_control_commands(conn):
    try:
        rows = _fetch_pending_commands(conn)
        if not rows:
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
        signal_train(zone, dtype)
        update_train_state(zone, dtype, "pending", progress="0%", message="Queued")

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
        set_detector_enabled(zone, "m2ad", enabled)
        set_detector_enabled(zone, "ckaad", enabled)
        set_detector_enabled(zone, "fusion", enabled)
        logger.info(f"Control: {'enabled' if enabled else 'disabled'} all detectors for {zone}")
    else:
        set_detector_enabled(zone, dtype, enabled)

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
        update_train_state(zone, dtype, "idle", progress="", message="Reset")
    logger.info(f"Control: reset training state for {zone}:{dtype}")


shutdown_event = threading.Event()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://anomalydb:anomalydb@postgres:5432/anomaly_db",
)
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_API_KEY = os.environ.get("GRAFANA_API_KEY", "")
FRAME_DIR = os.environ.get("FRAME_DIR", "/tmp/mvtec_frames")


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
        auth = HTTPBasicAuth("admin", "admin")
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
