import json
import logging
import os
import time
from typing import Optional

from detector.shared import (
    bump_severity,
    check_and_clear_train,
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
                    sensor_anomaly_count = state["sensor_anomaly_count"]

                if sensor_score == 0.0 and camera_score == 0.0:
                    shutdown_event.wait(timeout=FUSION_INTERVAL)
                    continue

                SENSOR_THRESH = 0.3
                CAMERA_THRESH = 0.3

                if sensor_score > SENSOR_THRESH and camera_score > CAMERA_THRESH:
                    combined_score = 1.0 - (1.0 - sensor_score) * (1.0 - camera_score)
                    severity = bump_severity(compute_severity(combined_score))
                    alert_type = "cross_modal"
                elif sensor_score > SENSOR_THRESH:
                    combined_score = sensor_score
                    severity = compute_severity(sensor_score)
                    alert_type = "sensor_anomaly"
                elif camera_score > CAMERA_THRESH:
                    combined_score = camera_score
                    severity = compute_severity(camera_score)
                    alert_type = "camera_anomaly"
                else:
                    combined_score = max(sensor_score, camera_score)
                    severity = "low"
                    alert_type = "fused"

                logger.info(
                    f"[{zone_name}] Fused: sensor={sensor_score:.3f}, "
                    f"camera={camera_score:.3f}, "
                    f"type={alert_type}, score={combined_score:.3f} ({severity})"
                )

                run_id = f"fused_{zone_name}_{int(time.time())}"
                alert_details = {
                    "sensor_max_score": float(sensor_score),
                    "camera_max_score": float(camera_score),
                    "combined_score": float(combined_score),
                    "sensor_anomaly_count": int(sensor_anomaly_count),
                }

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
