"""RTSP ingestion: the user's cameras -> `FRAME_DIR`.

`camera_loop` runs CKAAD inference on frames from `FRAME_DIR/<camera_id>/` and
`_load_live_frame` takes the newest one. This loop is what puts them there: for
every camera the session config gives an `rtsp_url`, it grabs a frame and
writes it as a PNG. It replaces the Kaggle MVTec stills, which were the demo's
"live" feed.

A camera that is down logs and is skipped; the other cameras are unaffected.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from detector.shared import FRAME_DIR, shutdown_event

logger = logging.getLogger("detector.capture")

CAPTURE_INTERVAL = float(os.environ.get("CAMERA_CAPTURE_INTERVAL_S", "15"))
# Frames are kept for CKAAD training, but the loop writes one per interval
# forever, so the directory is capped: at the 15s default 200 frames is about
# fifty minutes per camera. Without a cap the volume grows without bound.
FRAME_RETENTION = int(os.environ.get("CAMERA_FRAME_RETENTION", "200"))


def grab_frame(url: str) -> Optional[np.ndarray]:
    """One BGR frame from the stream, or None when it cannot be read.

    A fresh capture per grab on purpose: a long-lived one goes stale when the
    camera drops or the stream stalls, and cv2 keeps returning the last frame
    it buffered. A stale frame scored as if it were live is worse than a
    missed one, and the re-open cost is paid once per interval.
    """
    capture = cv2.VideoCapture(url)
    try:
        if not capture.isOpened():
            return None
        ok, frame = capture.read()
        if not ok or frame is None:
            return None
        return frame
    finally:
        capture.release()


def write_frame(camera_id: str, frame: np.ndarray) -> str:
    """Write the frame into this camera's directory and prune old ones.

    The name carries a millisecond timestamp so a directory listing sorts into
    capture order; `camera_loop` relies on that to take the newest frame.
    """
    directory = os.path.join(FRAME_DIR, camera_id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{int(time.time() * 1000)}.png")
    cv2.imwrite(path, frame)
    _prune(directory)
    return path


def _prune(directory: str) -> None:
    if FRAME_RETENTION <= 0:
        return
    names = sorted(n for n in os.listdir(directory) if n.endswith(".png"))
    for name in names[:-FRAME_RETENTION]:
        try:
            os.remove(os.path.join(directory, name))
        except OSError as exc:
            logger.warning("Could not remove old frame %s: %s", name, exc)


def capture_loop(cameras: List[Dict[str, Any]]) -> None:
    """Capture from every camera that has a stream, once per CAPTURE_INTERVAL."""
    targets = [cam for cam in cameras if cam.get("rtsp_url")]
    for cam in cameras:
        if not cam.get("rtsp_url"):
            logger.warning(
                "[%s] no rtsp_url in the session config (the interview recorded no "
                "camera ip), so it is not captured", cam.get("id"),
            )
    if not targets:
        logger.info("No cameras with a stream in the config; capture loop not started")
        return

    logger.info(
        "RTSP capture loop started (%d cameras, every %.0fs)", len(targets), CAPTURE_INTERVAL
    )
    while not shutdown_event.is_set():
        started = time.time()
        for cam in targets:
            if shutdown_event.is_set():
                break
            frame = grab_frame(cam["rtsp_url"])
            if frame is None:
                logger.warning("[%s] could not read a frame from %s", cam["id"], cam["rtsp_url"])
                continue
            try:
                write_frame(cam["id"], frame)
            except Exception as exc:
                logger.warning("[%s] could not store a frame: %s", cam["id"], exc)

        remaining = CAPTURE_INTERVAL - (time.time() - started)
        if remaining > 0:
            shutdown_event.wait(timeout=remaining)
