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
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np

from detector.shared import FRAME_DIR, shutdown_event

logger = logging.getLogger("detector.capture")

CAPTURE_INTERVAL = float(os.environ.get("CAMERA_CAPTURE_INTERVAL_S", "0.5"))
# Frames are kept for CKAAD training, but the loop writes one per interval
# forever, so the directory is capped: at the 0.5s default 200 frames is about
# 100 seconds per camera. Without a cap the volume grows without bound.
FRAME_RETENTION = int(os.environ.get("CAMERA_FRAME_RETENTION", "200"))

# Opening an RTSP stream costs ~2s (handshake + first keyframe), so a capture
# is opened once and held open rather than re-opened per grab. This bounds that
# handshake and is also how long a dropped camera is left before it is retried.
OPEN_TIMEOUT_MS = int(os.environ.get("CAMERA_OPEN_TIMEOUT_MS", "5000"))
RECONNECT_BACKOFF_S = float(os.environ.get("CAMERA_RECONNECT_BACKOFF_S", "5"))


def open_capture(url: str) -> Optional[cv2.VideoCapture]:
    """An open VideoCapture for the stream, or None when it cannot be opened.

    The open timeout goes through the params overload so a dead address fails
    fast instead of hanging on the default connect timeout; OpenCV builds that
    reject that overload fall back to the plain constructor.
    """
    try:
        cap = cv2.VideoCapture(
            url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS]
        )
    except (TypeError, cv2.error):
        cap = cv2.VideoCapture(url)
    if cap is None or not cap.isOpened():
        if cap is not None:
            cap.release()
        return None
    return cap


def read_frame(cap: cv2.VideoCapture) -> Optional[np.ndarray]:
    """The next frame from an open capture, or None when the stream has stalled.

    `grab` advances the decoder to a *new* frame instead of returning the one
    already buffered, so a stream that has stopped producing frames reports None
    here rather than silently replaying its last picture. That is the
    stale-frame problem the old per-grab re-open avoided, handled without paying
    the ~2s handshake on every frame.
    """
    if not cap.grab():
        return None
    ok, frame = cap.retrieve()
    if not ok or frame is None:
        return None
    return frame


def drain_stream(camera_id: str, url: str, on_frame: Callable[[np.ndarray], None]) -> None:
    """Hold one RTSP capture open and hand every frame to `on_frame`.

    The stream produces frames at its own rate (e.g. 15 fps) while the capture
    loop samples at CAPTURE_INTERVAL, so the frames must be consumed as they
    arrive: reading straight from the socket at the sample rate leaves the
    unconsumed frames queued in the decoder, and the frame that gets scored
    drifts further behind wall-clock every interval. Draining here keeps the
    sample current, and a stream that has stopped shows up as `on_frame` not
    being called rather than as a stale picture scored as if it were live.

    A stream that fails to open or read is released and retried on a fixed
    backoff, so a camera that is down does not spin.
    """
    cap = None
    try:
        while not shutdown_event.is_set():
            if cap is None:
                cap = open_capture(url)
                if cap is None:
                    logger.warning(
                        "[%s] could not open %s; retrying in %.0fs",
                        camera_id, url, RECONNECT_BACKOFF_S,
                    )
                    if shutdown_event.wait(timeout=RECONNECT_BACKOFF_S):
                        break
                    continue
                logger.info("[%s] connected to %s", camera_id, url)

            frame = read_frame(cap)
            if frame is None:
                logger.warning("[%s] stream stalled; reconnecting", camera_id)
                cap.release()
                cap = None
                if shutdown_event.wait(timeout=RECONNECT_BACKOFF_S):
                    break
                continue

            on_frame(frame)
    finally:
        if cap is not None:
            cap.release()


def write_frame(camera_id: str, frame: np.ndarray) -> str:
    """Write the frame into this camera's directory and prune old ones.

    The name carries a millisecond timestamp so a directory listing sorts into
    capture order; `camera_loop` relies on that to take the newest frame.
    """
    directory = os.path.join(FRAME_DIR, camera_id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{int(time.time() * 1000)}.png")
    # `camera_loop` reads the newest `*.png` here while this loop writes the
    # next one. A plain `imwrite` writes into the final name, so the reader can
    # open a half-written file and PIL reports "broken PNG file" (observed on
    # ~5% of reads). Write under a `.tmp` suffix the reader's `*.png` glob never
    # matches, then `os.replace` it into place: rename(2) is atomic within the
    # directory, so a reader only ever sees a complete frame.
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise OSError(f"cv2.imencode failed for {path}")
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(buf.tobytes())
    os.replace(tmp, path)
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


class _LatestFrame:
    """The newest frame a `drain_stream` thread has produced, with its time.

    The reader publishes on every frame; `capture_loop` samples at the capture
    interval, so this is the hand-off between the stream's frame rate and the
    rate frames are recorded at.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._ts = 0.0

    def publish(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame
            self._ts = time.time()

    def latest(self):
        with self._lock:
            return self._frame, self._ts


def capture_loop(cameras: List[Dict[str, Any]]) -> None:
    """Record the newest frame from every camera that has a stream, once per
    CAPTURE_INTERVAL.

    A per-camera thread keeps the stream drained (see `drain_stream`); this loop
    samples the newest frame each interval and writes it. The interval is
    therefore the rate frames are *recorded at*, not the rate the stream runs
    at, and can be set below the ~2s an RTSP handshake costs.

    A frame is written only when it is newer than the last one written:
    otherwise a stalled stream would keep stamping the same stale picture with a
    fresh mtime, and `camera_loop`'s freshness check would never see it go old.
    """
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
        "RTSP capture loop started (%d cameras, recording every %.2fs)",
        len(targets), CAPTURE_INTERVAL,
    )

    slots: Dict[str, _LatestFrame] = {}
    threads: List[threading.Thread] = []
    for cam in targets:
        slot = _LatestFrame()
        slots[cam["id"]] = slot
        thread = threading.Thread(
            target=drain_stream,
            args=(cam["id"], cam["rtsp_url"], slot.publish),
            name=f"capture-{cam['id']}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    last_written: Dict[str, float] = {}
    try:
        while not shutdown_event.is_set():
            started = time.time()
            for cam in targets:
                if shutdown_event.is_set():
                    break
                cam_id = cam["id"]
                frame, ts = slots[cam_id].latest()
                if frame is None or ts == last_written.get(cam_id):
                    continue  # not connected yet, or no new frame since last sample
                try:
                    write_frame(cam_id, frame)
                    last_written[cam_id] = ts
                except Exception as exc:
                    logger.warning("[%s] could not store a frame: %s", cam_id, exc)

            remaining = CAPTURE_INTERVAL - (time.time() - started)
            if remaining > 0:
                shutdown_event.wait(timeout=remaining)
    finally:
        for thread in threads:
            thread.join(timeout=5)
