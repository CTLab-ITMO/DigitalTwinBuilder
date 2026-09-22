import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

from detector.shared import (
    fusion_lock,
    fusion_state,
    get_db_connection,
    get_train_state_snapshot,
    shutdown_event,
    poll_control_commands,
    detector_enabled,
    detector_enabled_lock,
    train_events,
    train_events_lock,
    signal_train,
    is_detector_enabled,
    set_detector_enabled,
)

from detector.sensor_loop import sensor_detection_loop
from detector.camera_loop import camera_detection_loop
from detector.fusion_loop import fusion_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("detector")

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config/config.json")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def main():
    logger.info("=" * 60)
    logger.info("Anomaly Detection Service starting...")
    logger.info(f"Config: {CONFIG_PATH}")
    logger.info("=" * 60)

    config = load_config()
    zones = config
    logger.info(f"Loaded {len(zones)} zones from config")

    if not zones:
        logger.error("No zones found in config, exiting")
        sys.exit(1)

    zone_sensors: Dict[str, List[str]] = {}
    zone_cameras: Dict[str, List[Dict]] = {}
    for zone_name, zone_data in zones.items():
        sensors_raw = zone_data.get("sensors", [])
        if isinstance(sensors_raw, list):
            zone_sensors[zone_name] = [s["id"] for s in sensors_raw]
        else:
            zone_sensors[zone_name] = list(sensors_raw.keys())

        cameras_raw = zone_data.get("cameras", [])
        zone_cameras[zone_name] = []
        if isinstance(cameras_raw, list):
            for c in cameras_raw:
                camera_data = {
                    "id": c["id"],
                    "category": c.get("category", c["id"]),
                }
                zone_cameras[zone_name].append(camera_data)
        elif isinstance(cameras_raw, dict):
            for cam_id, cam_info in cameras_raw.items():
                camera_data = {
                    "id": cam_id,
                    "category": cam_info.get("category", cam_id),
                }
                zone_cameras[zone_name].append(camera_data)

    for z, sensors in zone_sensors.items():
        logger.info(f"  Zone '{z}': {len(sensors)} sensors, {len(zone_cameras[z])} cameras")
        logger.info(f"    Sensors: {', '.join(sensors)}")
        logger.info(f"    Cameras: {', '.join(c['id'] for c in zone_cameras[z])}")

    for zone_name in zones:
        for dtype in ("m2ad", "fusion"):
            set_detector_enabled(zone_name, dtype, True)
        set_detector_enabled(zone_name, "ckaad", True)

    threads = []

    def control_poll_loop():
        logger.info("Control polling thread started")
        conn = get_db_connection()
        try:
            while not shutdown_event.is_set():
                try:
                    poll_control_commands(conn)
                except Exception:
                    logger.exception("Control poll iteration error")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                shutdown_event.wait(timeout=5)
        finally:
            conn.close()

    t = threading.Thread(target=control_poll_loop, daemon=True, name="control-poll")
    t.start()
    threads.append(t)
    logger.info("Started control polling thread")

    def status_http_server():
        import json
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class StatusHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    state = get_train_state_snapshot()
                    self.wfile.write(json.dumps(state).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("0.0.0.0", 9100), StatusHandler)
        while not shutdown_event.is_set():
            server.timeout = 1.0
            server.handle_request()

    t = threading.Thread(target=status_http_server, daemon=True, name="status-http")
    t.start()
    threads.append(t)
    logger.info("Started status HTTP server on port 9100")

    for zone_name in zones:
        t = threading.Thread(
            target=sensor_detection_loop,
            args=(zone_name, zone_sensors[zone_name]),
            daemon=True,
            name=f"sensor-{zone_name}",
        )
        t.start()
        threads.append(t)
        logger.info(f"Started sensor detection thread for '{zone_name}'")

    all_cameras = []
    for zone_name, cams in zone_cameras.items():
        for cam in cams:
            cam["zone"] = zone_name
            all_cameras.append(cam)
    if all_cameras:
        t = threading.Thread(
            target=camera_detection_loop,
            args=(all_cameras,),
            daemon=True,
            name="camera-detection",
        )
        t.start()
        threads.append(t)
        logger.info(f"Started camera detection thread ({len(all_cameras)} cameras)")

    for zone_name in zones:
        t = threading.Thread(
            target=fusion_loop,
            args=(zone_name,),
            daemon=True,
            name=f"fusion-{zone_name}",
        )
        t.start()
        threads.append(t)
        logger.info(f"Started fusion thread for '{zone_name}'")

    logger.info(f"All {len(threads)} threads started. Waiting for shutdown signal...")

    shutdown_event.wait()
    logger.info("Shutdown signal received, exiting.")
    sys.exit(0)


if __name__ == "__main__":
    main()
