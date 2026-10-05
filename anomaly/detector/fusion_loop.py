import json
import logging
import os
import time
from typing import Optional

from detector.shared import (
    alert_due,
    bump_severity,
    clear_alert,
    compute_severity,
    fusion_lock,
    fusion_state,
    get_db_connection,
    get_zone_dashboard_uids,
    is_detector_enabled,
    shutdown_event,
    write_alerts,
)

logger = logging.getLogger("detector.fusion")

FUSION_INTERVAL = float(os.environ.get("FUSION_INTERVAL", "30"))
# One alert per sustained episode: a fused score above the threshold for an
# hour is one anomaly, not 120 rows in `alerts`.
FUSION_ALERT_COOLDOWN = float(os.environ.get("FUSION_ALERT_COOLDOWN_S", "300"))


def fusion_loop(zone_name: str):
    logger.info(f"[{zone_name}] Fusion loop started")

    conn = get_db_connection()

    try:
        while not shutdown_event.is_set():
            loop_start = time.time()

            if not is_detector_enabled(zone_name, "fusion"):
                shutdown_event.wait(timeout=FUSION_INTERVAL)
                continue

            try:
                with fusion_lock:
                    state = fusion_state.get(zone_name)
                    if state is None:
                        fusion_state[zone_name] = {
                            "sensor_max_score": 0.0,
                            "camera_max_score": 0.0,
                            "sensor_anomaly_count": 0,
                        }
                        state = fusion_state[zone_name]

                    sensor_score = state["sensor_max_score"]
                    camera_score = state["camera_max_score"]

                if sensor_score == 0.0 and camera_score == 0.0:
                    shutdown_event.wait(timeout=FUSION_INTERVAL)
                    continue

                SENSOR_THRESH = 0.3
                CAMERA_THRESH = 0.3

                if sensor_score > SENSOR_THRESH and camera_score > CAMERA_THRESH:
                    combined_score = 1.0 - (1.0 - sensor_score) * (1.0 - camera_score)
                    severity = bump_severity(compute_severity(combined_score))
                    alert_type = "cross_modal"
                else:
                    # Fusion raises exactly one alert the per-modality loops
                    # cannot: the cross-modal verdict. A single modality firing
                    # is already written by that modality's own loop
                    # (`sensor_loop` / `camera_loop` each call `write_alerts`),
                    # so re-emitting it here doubled every event — and with the
                    # camera offline `camera_score` is always 0, so *every*
                    # sensor anomaly produced two `alerts` rows. Scores between
                    # zero and the threshold are ordinary. Either way, end any
                    # open fusion episode and let the owning loop alert.
                    clear_alert(f"fusion:{zone_name}")
                    logger.debug(
                        f"[{zone_name}] Not cross-modal: "
                        f"sensor={sensor_score:.3f}, camera={camera_score:.3f}"
                    )
                    shutdown_event.wait(timeout=FUSION_INTERVAL)
                    continue

                logger.info(
                    f"[{zone_name}] Fused: sensor={sensor_score:.3f}, "
                    f"camera={camera_score:.3f}, "
                    f"type={alert_type}, score={combined_score:.3f} ({severity})"
                )

                run_id = f"fused_{zone_name}_{int(time.time())}"

                if not alert_due(f"fusion:{zone_name}", FUSION_ALERT_COOLDOWN):
                    # Suppressed by the cooldown, not by a lack of signal: a
                    # sustained episode keeps the score above threshold for its
                    # whole duration. Wait out the interval here — this branch
                    # sits above the loop's own sleep, so a bare `continue`
                    # spun the loop at full speed and flooded the log with the
                    # `Fused:` line every few microseconds.
                    shutdown_event.wait(timeout=FUSION_INTERVAL)
                    continue

                alerts = [
                    {
                        "source_id": f"zone_{zone_name}",
                        "alert_type": alert_type,
                        "severity": severity,
                        "message": (
                            f"[{zone_name}] {alert_type}: {severity.upper()}"
                            f" (sensor={sensor_score:.2f}, camera={camera_score:.2f}, "
                            f"fused={combined_score:.2f})"
                        ),
                        "score": float(combined_score),
                        "run_id": run_id,
                    }
                ]
                write_alerts(conn, alerts)

            except Exception as e:
                logger.error(
                    f"[{zone_name}] Fusion error: {e}", exc_info=True
                )
                conn.rollback()

            elapsed = time.time() - loop_start
            sleep_time = max(1, FUSION_INTERVAL - elapsed)
            if sleep_time > 0:
                shutdown_event.wait(timeout=sleep_time)

    finally:
        conn.close()
        logger.info(f"[{zone_name}] Fusion loop stopped")
