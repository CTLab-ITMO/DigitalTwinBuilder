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

from detector.camera_capture import capture_loop
from detector.camera_loop import camera_detection_loop
from detector.fusion_loop import fusion_loop
from detector.modbus_loop import modbus_poll_loop
from detector.sensor_loop import sensor_detection_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("detector")

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config/config.json")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _iter_sources(raw: Any) -> List[tuple]:
    """`(id, config)` pairs for a zone's sensors or cameras.

    The generated config writes them as a list of objects; the mapping form is
    accepted too, since the sample config and `config_loader` both allow it.
    """
    if isinstance(raw, dict):
        return list(raw.items())
    return [(item["id"], item) for item in raw]


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
    # The same entries again, this time as the addressing the ingestion loops
    # need: the detection loops above work off ids alone, but polling a device
    # takes its ip, register, unit id and type, and opening a stream takes its
    # rtsp_url. Both are carried in the session config the user generated.
    modbus_specs: List[Dict[str, Any]] = []
    for zone_name, zone_data in zones.items():
        sensors_raw = zone_data.get("sensors", [])
        if isinstance(sensors_raw, list):
            zone_sensors[zone_name] = [s["id"] for s in sensors_raw]
        else:
            zone_sensors[zone_name] = list(sensors_raw.keys())

        for sensor_id, sensor_info in _iter_sources(sensors_raw):
            modbus_specs.append({**sensor_info, "id": sensor_id, "zone": zone_name})

        cameras_raw = zone_data.get("cameras", [])
        zone_cameras[zone_name] = []
        for cam_id, cam_info in _iter_sources(cameras_raw):
            zone_cameras[zone_name].append({
                "id": cam_id,
                "category": cam_info.get("category", cam_id),
                "rtsp_url": cam_info.get("rtsp_url"),
            })

    for z, sensors in zone_sensors.items():
        logger.info(f"  Zone '{z}': {len(sensors)} sensors, {len(zone_cameras[z])} cameras")
        logger.info(f"    Sensors: {', '.join(sensors)}")
        logger.info(f"    Cameras: {', '.join(c['id'] for c in zone_cameras[z])}")

    pollable = 0
    for sensor in modbus_specs:
        if sensor.get("ip") and sensor.get("register") is not None:
            pollable += 1
        else:
            logger.warning(
                f"  Sensor '{sensor['id']}' has no ip/register in the config "
                f"(the interview recorded none), so it is not polled"
            )
    logger.info(
        f"Modbus: {pollable}/{len(modbus_specs)} sensors have an address to poll"
    )

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

    # The two ingestion loops go first: everything the detection loops score
    # comes out of the tables and directories these fill.
    t = threading.Thread(
        target=modbus_poll_loop,
        args=(modbus_specs,),
        daemon=True,
        name="modbus-poll",
    )
    t.start()
    threads.append(t)
    logger.info(f"Started Modbus polling thread ({len(modbus_specs)} sensors)")

    all_cameras = []
    for zone_name, cams in zone_cameras.items():
        for cam in cams:
            cam["zone"] = zone_name
            all_cameras.append(cam)
    t = threading.Thread(
        target=capture_loop,
        args=(all_cameras,),
        daemon=True,
        name="camera-capture",
    )
    t.start()
    threads.append(t)
    logger.info(f"Started RTSP capture thread ({len(all_cameras)} cameras)")

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
