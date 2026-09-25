import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

from detector.shared import (
    ANOMALY_API_PUBLIC_URL,
    FRAME_DIR,
    alert_due,
    clear_alert,
    clear_train,
    compute_severity,
    fusion_lock,
    fusion_state,
    get_db_connection,
    is_detector_enabled,
    shutdown_event,
    signal_train,
    train_requested,
    update_train_state,
    write_alerts,
)

logger = logging.getLogger("detector.camera")

CAMERA_INTERVAL = float(os.environ.get("CAMERA_DETECT_INTERVAL", "15"))
RETRAIN_EVERY = int(os.environ.get("CAMERA_RETRAIN_EVERY", "50"))
# CKAAD needs a handful of normal frames to fit a backbone on. They used to be
# the Kaggle MVTec stills; now the capture loop fills the directory in real
# time, so this is also how long the loop waits before it has anything to train.
MIN_TRAINING_FRAMES = 10

# The capture loop writes one frame per camera per `CAMERA_CAPTURE_INTERVAL_S`,
# so a newest frame older than a few intervals means that stream stopped — the
# directory only advances on a successful grab. Scoring the last frame a dead
# camera ever sent would report on a camera that is no longer there.
CAPTURE_INTERVAL = float(os.environ.get("CAMERA_CAPTURE_INTERVAL_S", "15"))
FRAME_MAX_AGE = float(os.environ.get("CAMERA_FRAME_MAX_AGE_S", str(3 * CAPTURE_INTERVAL)))

# One alert per sustained episode: CKAAD above the threshold for an hour is one
# anomaly, not 240 rows in `alerts`.
CAMERA_ALERT_COOLDOWN = float(os.environ.get("CAMERA_ALERT_COOLDOWN_S", "300"))

# A rolling max that only ever rises never forgets a single bad frame: one
# spike keeps the fused camera score high for the rest of the run. Each interval
# the previous value decays, so a spike fades over a handful of intervals while
# a genuinely sustained anomaly stays above the threshold.
ROLLING_MAX_DECAY = float(os.environ.get("CAMERA_ROLLING_MAX_DECAY", "0.5"))

def _load_collected_training_images(
    all_cameras: List[Dict[str, Any]]
) -> List[np.ndarray]:
    all_images = []
    for cam in all_cameras:
        cam_id = cam["id"]
        cam_dir = os.path.join(FRAME_DIR, cam_id)
        if not os.path.isdir(cam_dir):
            logger.debug(f"[{cam_id}] No collected frames dir: {cam_dir}")
            continue

        png_files = sorted(Path(cam_dir).glob("*.png"))
        if not png_files:
            logger.warning(f"[{cam_id}] No collected frames found in {cam_dir}")
            continue

        cam_images = 0
        for p in png_files:
            try:
                img = Image.open(p).convert("RGB")
                img_resized = img.resize((256, 256), Image.LANCZOS)
                all_images.append(np.array(img_resized))
                cam_images += 1
            except Exception as e:
                logger.warning(f"[{cam_id}] Failed to load collected frame {p}: {e}")

        logger.info(f"  Loaded {cam_images} collected training frames from '{cam_id}'")

    logger.info(
        f"Total: {len(all_images)} collected training frames across {len(all_cameras)} cameras"
    )
    return all_images


def _load_live_frame(camera_id: str) -> Optional[np.ndarray]:
    """The newest frame the capture loop wrote for this camera, if it is fresh.

    Newest, not a random one: the files are named with a millisecond timestamp
    in capture order, and scoring a random frame from up to fifty minutes of
    history would report on the past rather than on what the camera sees now.

    Newest *and* recent: the capture loop only writes on a successful grab, so
    when a stream dies the newest file stops advancing. Without an age check the
    loop would keep scoring that last frame, and the fused score would keep
    saying "camera anomaly" for a camera that has been offline for hours. A
    frame older than `FRAME_MAX_AGE` is treated as no frame at all; the caller
    skips the camera and the dead stream is logged.
    """
    frame_dir = os.path.join(FRAME_DIR, camera_id)
    if not os.path.isdir(frame_dir):
        logger.debug(f"[{camera_id}] Frame dir not found: {frame_dir}")
        return None

    png_files = list(Path(frame_dir).glob("*.png"))
    if not png_files:
        logger.debug(f"[{camera_id}] No PNGs in {frame_dir}")
        return None

    p = max(png_files, key=lambda path: path.name)
    age = _frame_age_seconds(p)
    if age is not None and age > FRAME_MAX_AGE:
        logger.warning(
            f"[{camera_id}] newest frame is {age:.0f}s old (> {FRAME_MAX_AGE:.0f}s); "
            f"the stream looks dead, skipping this camera"
        )
        return None

    try:
        img = Image.open(p).convert("RGB")
        img_resized = img.resize((256, 256), Image.LANCZOS)
        return np.array(img_resized)
    except Exception as e:
        logger.warning(f"[{camera_id}] Failed to load frame {p}: {e}")
        return None


def _frame_age_seconds(path: Path) -> Optional[float]:
    """How long ago the frame was captured, from its name, then its mtime.

    The name is a millisecond epoch stamp written by the capture loop, which is
    the capture time itself rather than whatever the filesystem last touched.
    A file that is not named that way falls back to mtime; if neither reads,
    None leaves the caller's check to the frame's own contents.
    """
    try:
        return max(0.0, time.time() - int(path.stem) / 1000.0)
    except (ValueError, OSError):
        try:
            return max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return None


def _init_ckaad_model(training_images: List[np.ndarray], progress_callback=None):
    from detection.camera.anomaly import CKAADAnomalyDetector

    logger.info(
        f"Initializing CKAAD model on {len(training_images)} images "
        f"(device: {'cuda' if __import__('torch').cuda.is_available() else 'cpu'})"
    )

    detector = CKAADAnomalyDetector(
        detector_id="ckaad_shared",
        backbone="resnet18",
        layers=[1, 2, 3],
        image_size=128,
        epochs=20,
        topk=50,
        sigma=4,
    )

    logger.info("Training CKAAD model (this may take several minutes)...")
    if not detector.fit(list(training_images), progress_callback=progress_callback):
        logger.error("CKAAD initial training failed")
        return None
    return detector


def _wait_for_training_frames(all_cameras: List[Dict[str, Any]]) -> bool:
    """Block until the capture loop has produced enough frames, or shut down.

    Frames arrive from the cameras themselves, one per camera per capture
    interval, so a stack started against a live stream has none at startup —
    roughly ten capture intervals before there is enough to train on. Exiting
    instead, which is what the Kaggle-seeded frames allowed, would disable
    camera detection for the whole run before anyone could press Train. The
    sensor loop already waits for its readings this way.

    The images themselves are not returned: `_ensure_ckaad_trained` reloads the
    directory at fit time, so a retrain trains on the frames that exist then
    rather than on the startup snapshot.
    """
    while not shutdown_event.is_set():
        images = _load_collected_training_images(all_cameras)
        if len(images) >= MIN_TRAINING_FRAMES:
            return True
        logger.info(
            f"Collected {len(images)} frames so far ({MIN_TRAINING_FRAMES} needed "
            f"for CKAAD); waiting for the capture loop"
        )
        shutdown_event.wait(timeout=CAMERA_INTERVAL)
    return False


def camera_detection_loop(all_cameras: List[Dict[str, Any]]):
    logger.info(
        f"Camera detection loop started ({len(all_cameras)} cameras, "
        f"shared CKAAD model)"
    )

    if not _wait_for_training_frames(all_cameras):
        logger.info("Camera detection loop stopping; no frames to train on")
        return

    ckaad = None
    conn = get_db_connection()
    run_count = 0
    detection_counters: Dict[str, int] = {c["id"]: 0 for c in all_cameras}
    rolling_max_scores: Dict[str, float] = {c["id"]: 0.0 for c in all_cameras}

    try:
        while not shutdown_event.is_set():
            loop_start = time.time()

            if not _any_zone_ckaad_enabled(all_cameras):
                shutdown_event.wait(timeout=CAMERA_INTERVAL)
                continue

            # A Train press and the periodic re-train are the same operation;
            # the periodic one is just a press nobody made. Both go through
            # `_ensure_ckaad_trained`, which reloads the frames and owns the
            # fit/state bookkeeping — there is no second copy of it to drift.
            periodic_retrain = run_count > 0 and run_count % RETRAIN_EVERY == 0
            ckaad = _ensure_ckaad_trained(conn, ckaad, all_cameras, periodic_retrain)
            if ckaad is not None:
                _run_camera_inferences(conn, all_cameras, ckaad, detection_counters, rolling_max_scores)
                _update_camera_fusion_state(all_cameras, rolling_max_scores)

                run_count += 1
                if run_count % 10 == 0:
                    logger.info(
                        f"Camera detection: {run_count} runs, "
                        f"scores: {', '.join(f'{k}={v:.2f}' for k, v in rolling_max_scores.items())}"
                    )

            elapsed = time.time() - loop_start
            sleep_time = max(1, CAMERA_INTERVAL - elapsed)
            if sleep_time > 0:
                shutdown_event.wait(timeout=sleep_time)

    finally:
        conn.close()
        logger.info("Camera detection loop stopped")


def _any_zone_ckaad_enabled(all_cameras):
    zones_for_cameras = sorted(set(c["zone"] for c in all_cameras))
    return any(is_detector_enabled(z, "ckaad") for z in zones_for_cameras)


def _adopt_pending_ckaad_train(conn) -> bool:
    """Whether CKAAD has an outstanding Train press.

    Any `detector_control` row the control thread has not picked up is adopted
    here so a queued press is honoured even if that thread is behind. The row is
    marked executed on delivery, but the request it carried lives on in the
    durable flag until a fit succeeds — that is what makes one press enough.
    """
    from psycopg2.extras import RealDictCursor
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id FROM detector_control
                   WHERE zone_name = 'shared' AND detector_type = 'ckaad'
                   AND command = 'train' AND executed_at IS NULL
                   ORDER BY issued_at ASC"""
            )
            pending = cur.fetchall()
            for row in pending:
                cur.execute(
                    "UPDATE detector_control SET executed_at = NOW() WHERE id = %s",
                    (row["id"],)
                )
            if pending:
                conn.commit()
                signal_train("shared", "ckaad")
                logger.info(f"Adopted {len(pending)} pending CKAAD train command(s)")
    except Exception:
        conn.rollback()
    return train_requested("shared", "ckaad")


def _ensure_ckaad_trained(conn, ckaad, all_cameras, force=False):
    """The CKAAD model, trained when there is none, a Train is outstanding, or
    the periodic re-train is due (`force`).

    The frames arrive from the capture loop, so the first fit happens on its own
    once `_wait_for_training_frames` has enough — a press is a re-train trigger
    rather than a prerequisite. It is also durable: read, not consumed, and
    cleared only once a fit actually succeeds, so a press that lands before the
    frames are in is honoured later instead of lost.

    The frames are re-read from disk here, at fit time. Training every re-train
    on the snapshot taken at startup would teach CKAAD the plant as it looked
    when the stack came up and never let it follow a slow drift.

    Returns None only when there is no usable model yet (the first fit failed);
    the caller waits an interval and the next iteration retries. A failed
    re-train keeps the previous model scoring.
    """
    retrain_requested = _adopt_pending_ckaad_train(conn)
    if ckaad is not None and not retrain_requested and not force:
        return ckaad

    training_images = _load_collected_training_images(all_cameras)
    if len(training_images) < MIN_TRAINING_FRAMES:
        logger.warning(
            f"Only {len(training_images)} frames available ({MIN_TRAINING_FRAMES} "
            f"needed); keeping the current CKAAD model and retrying later"
        )
        return ckaad

    logger.info("Training/re-training CKAAD model...")
    update_train_state("shared", "ckaad", "training", progress="0%",
                       message="Retraining CKAAD..." if ckaad is not None
                       else "Starting CKAAD training...")
    train_t0 = time.time()

    def _progress(epoch, total):
        pct = int(epoch / total * 100)
        elapsed = time.time() - train_t0
        update_train_state("shared", "ckaad", "training", progress=f"{pct}%",
                           message=f"CKAAD epoch {epoch}/{total} ({elapsed:.0f}s)")

    try:
        if ckaad is None:
            trained = _init_ckaad_model(training_images, progress_callback=_progress)
        else:
            # `CKAAD.fit` swallows its own exception and returns False; a failed
            # re-train keeps the previous model scoring and the press pending.
            trained = ckaad if ckaad.fit(list(training_images), progress_callback=_progress) else None
    except Exception as e:
        logger.error(f"CKAAD training failed: {e}")
        trained = None

    if trained is None:
        logger.error("CKAAD training failed; will retry")
        update_train_state("shared", "ckaad", "error", progress="",
                           message="CKAAD training failed; retrying")
        return ckaad

    clear_train("shared", "ckaad")
    elapsed = time.time() - train_t0
    update_train_state("shared", "ckaad", "complete", progress="100%",
                       message=f"CKAAD ready ({elapsed:.1f}s)")
    logger.info(f"CKAAD training complete in {elapsed:.1f}s")
    return trained


def _run_camera_inferences(conn, all_cameras, ckaad, detection_counters, rolling_max_scores):
    for cam in all_cameras:
        cam_id = cam["id"]
        cam_category = cam["category"]
        zone_name = cam["zone"]

        if shutdown_event.is_set():
            break

        if not is_detector_enabled(zone_name, "ckaad"):
            continue

        try:
            frame = _load_live_frame(cam_id)
            if frame is None:
                continue

            result = ckaad.detect(frame)
            score = result.anomaly_score if result else 0.0

            # Decay first, then fold in this frame: the value the fusion loop
            # reads falls back to zero over a few intervals after a spike
            # instead of pinning the zone at "camera anomaly" for the rest of
            # the run.
            rolling_max_scores[cam_id] = max(
                rolling_max_scores[cam_id] * ROLLING_MAX_DECAY, score
            )
            detection_counters[cam_id] += 1

            image_url, heatmap_url = _save_ckaad_anomaly_frame(score, ckaad, result, frame, zone_name, cam_id)

            run_id = f"ckaad_{int(time.time())}"
            _store_ckaad_result(conn, cam_id, cam_category, ckaad, score, run_id,
                                detection_counters[cam_id], image_url, heatmap_url, rolling_max_scores[cam_id])

            alert_key = f"camera:{cam_id}"
            if score > ckaad.threshold * 0.8:
                if alert_due(alert_key, CAMERA_ALERT_COOLDOWN):
                    severity = compute_severity(score)
                    alerts = [
                        {
                            "source_id": cam_id,
                            "alert_type": "camera_anomaly",
                            "severity": severity,
                            "message": (
                                f"[{cam_id}] CKAAD anomaly: score={score:.3f} "
                                f"(threshold={ckaad.threshold:.3f})"),
                            "score": float(score),
                            "run_id": run_id,
                        }
                    ]
                    write_alerts(conn, alerts)
            else:
                clear_alert(alert_key)

        except Exception as e:
            logger.error(f"[{cam_id}] Detection error: {e}", exc_info=True)
            conn.rollback()


def _save_ckaad_anomaly_frame(score, ckaad, result, frame, zone_name, cam_id):
    """The frame's snapshot URL, and the overlay URL when a heatmap was drawn.

    The snapshot is always the camera's own frame; the heatmap is the coloured
    composite the API builds from the sidecar PNG. They are separate fields
    because they are separate pictures — the old code folded the overlay into
    `image_url` and returned `heatmap_url` as a constant `""`, so a consumer
    that asked for the heatmap got nothing and one that asked for the snapshot
    got an overlay.
    """
    from PIL import Image
    image_url = ""
    heatmap_url = ""
    if score <= ckaad.threshold * 0.8:
        return image_url, heatmap_url

    ts = int(time.time())
    anomaly_frames_dir = Path("/anomaly_frames") / zone_name / cam_id
    anomaly_frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        frame_path = anomaly_frames_dir / f"{ts}.png"
        Image.fromarray(frame).save(str(frame_path))
        image_url = f"{ANOMALY_API_PUBLIC_URL}/images/anomaly/{zone_name}/{cam_id}/{ts}"
        amap = (result.details or {}).get("anomaly_map")
        if amap is not None:
            heatmap_raw = (amap * 255).clip(0, 255).astype(np.uint8)
            heatmap_img = Image.fromarray(heatmap_raw, mode="L").resize(
                (frame.shape[1], frame.shape[0]), Image.BILINEAR
            )
            heatmap_img.save(str(anomaly_frames_dir / f"{ts}_heatmap.png"))
            heatmap_url = f"{ANOMALY_API_PUBLIC_URL}/images/anomaly/{zone_name}/{cam_id}/{ts}/overlay"
    except Exception:
        logger.exception("Failed to save anomaly frame")
    return image_url, heatmap_url


def _store_ckaad_result(conn, cam_id, cam_category, ckaad, score, run_id, counter, image_url, heatmap_url, rolling_max):
    if score <= 0.05 and counter % 10 != 0:
        return
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO image_detection_results
               (source_id, category, detector, run_id, timestamp, image_name,
                is_anomaly, anomaly_score, details)
               VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s)""",
            (
                cam_id,
                cam_category,
                "ckaad",
                run_id,
                f"{cam_id}_frame_{int(time.time())}.png",
                bool(score > ckaad.threshold),
                float(score),
                json.dumps({
                    "camera_id": cam_id,
                    "threshold": float(ckaad.threshold),
                    "rolling_max": float(rolling_max),
                    "anomaly_image_url": image_url,
                    "heatmap_url": heatmap_url,
                }),
            ),
        )
    conn.commit()


def _update_camera_fusion_state(all_cameras, rolling_max_scores):
    zone_max_scores: Dict[str, float] = {}
    for cam in all_cameras:
        zone = cam["zone"]
        cam_id = cam["id"]
        zone_max_scores[zone] = max(
            zone_max_scores.get(zone, 0.0),
            rolling_max_scores.get(cam_id, 0.0),
        )

    with fusion_lock:
        for zone, max_score in zone_max_scores.items():
            if zone not in fusion_state:
                fusion_state[zone] = {
                    "sensor_max_score": 0.0,
                    "camera_max_score": 0.0,
                    "sensor_anomaly_count": 0,
                }
            fusion_state[zone]["camera_max_score"] = float(max_score)
