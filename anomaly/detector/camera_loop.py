import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

from detector.shared import (
    FRAME_DIR,
    check_and_clear_train,
    compute_severity,
    fusion_lock,
    fusion_state,
    get_db_connection,
    is_detector_enabled,
    shutdown_event,
    update_train_state,
    write_alerts,
)

logger = logging.getLogger("detector.camera")

CAMERA_INTERVAL = float(os.environ.get("CAMERA_DETECT_INTERVAL", "15"))
RETRAIN_EVERY = int(os.environ.get("CAMERA_RETRAIN_EVERY", "50"))

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


def _load_live_frame(camera_id: str, camera_category: str) -> Optional[np.ndarray]:
    frame_dir = os.path.join(FRAME_DIR, camera_id)
    if not os.path.isdir(frame_dir):
        logger.debug(f"[{camera_id}] Frame dir not found: {frame_dir}")
        return None

    png_files = list(Path(frame_dir).glob("*.png"))
    if not png_files:
        logger.debug(f"[{camera_id}] No PNGs in {frame_dir}")
        return None

    try:
        p = random.choice(png_files)
        img = Image.open(p).convert("RGB")
        img_resized = img.resize((256, 256), Image.LANCZOS)
        return np.array(img_resized)
    except Exception as e:
        logger.warning(f"[{camera_id}] Failed to load frame {p}: {e}")
        return None


def _init_ckaad_model(training_images: List[np.ndarray]):
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
    update_train_state("shared", "ckaad", "training", progress="0%", message="Starting CKAAD training...")
    t0 = time.time()

    def _ckaad_progress(epoch, total):
        pct = int(epoch / total * 100)
        elapsed = time.time() - t0
        update_train_state("shared", "ckaad", "training", progress=f"{pct}%",
                           message=f"CKAAD epoch {epoch}/{total} ({elapsed:.0f}s)")

    detector.fit(list(training_images), progress_callback=_ckaad_progress)
    elapsed = time.time() - t0
    update_train_state("shared", "ckaad", "complete", progress="100%", message=f"CKAAD ready ({elapsed:.1f}s)")
    logger.info(f"CKAAD training complete in {elapsed:.1f}s")

    return detector


def camera_detection_loop(all_cameras: List[Dict[str, Any]]):
    logger.info(
        f"Camera detection loop started ({len(all_cameras)} cameras, "
        f"shared CKAAD model)"
    )

    training_images = _load_collected_training_images(all_cameras)
    if len(training_images) < 10:
        logger.error(f"Too few collected frames ({len(training_images)}) for CKAAD. Camera detection disabled.")
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

            ckaad = _check_ckaad_train_or_wait(conn, ckaad, training_images)
            if ckaad is None:
                continue

            ckaad = _retrain_ckaad_if_needed(conn, ckaad, training_images, run_count)
            if ckaad is None:
                continue

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


def _check_ckaad_train_or_wait(conn, ckaad, training_images):
    from psycopg2.extras import RealDictCursor
    force_retrain = check_and_clear_train("shared", "ckaad")

    if ckaad is None and not force_retrain:
        update_train_state("shared", "ckaad", "idle", message="Awaiting Train button")
        shutdown_event.wait(timeout=5)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT id FROM detector_control
                       WHERE zone_name = 'shared' AND detector_type = 'ckaad'
                       AND command = 'train' AND executed_at IS NULL
                       ORDER BY issued_at ASC LIMIT 1"""
                )
                pending = cur.fetchone()
                if pending:
                    logger.info("Found pending train in DB for CKAAD")
                    cur.execute(
                        "UPDATE detector_control SET executed_at = NOW() WHERE id = %s",
                        (pending["id"],)
                    )
                    force_retrain = True
            conn.commit()
        except Exception:
            conn.rollback()
        if not force_retrain:
            force_retrain = check_and_clear_train("shared", "ckaad")
        if not force_retrain:
            return None

    if force_retrain or ckaad is None:
        logger.info("Training/re-training CKAAD model...")
        update_train_state("shared", "ckaad", "training", progress="0%", message="Starting CKAAD training...")
        train_t0 = time.time()

        def _progress(epoch, total):
            pct = int(epoch / total * 100)
            elapsed = time.time() - train_t0
            update_train_state("shared", "ckaad", "training", progress=f"{pct}%",
                               message=f"CKAAD epoch {epoch}/{total} ({elapsed:.0f}s)")

        try:
            if ckaad is None:
                ckaad = _init_ckaad_model(training_images)
            ckaad.fit(list(training_images), progress_callback=_progress)
            elapsed = time.time() - train_t0
            update_train_state("shared", "ckaad", "complete", progress="100%",
                               message=f"CKAAD ready ({elapsed:.1f}s)")
            logger.info(f"CKAAD training complete in {elapsed:.1f}s")
        except Exception as e:
            logger.error(f"CKAAD training failed: {e}")
            update_train_state("shared", "ckaad", "error", message=str(e))
            return None

    return ckaad


def _retrain_ckaad_if_needed(conn, ckaad, training_images, run_count):
    if not (run_count > 0 and run_count % RETRAIN_EVERY == 0):
        return ckaad

    logger.info("Periodic CKAAD retraining...")
    update_train_state("shared", "ckaad", "training", progress="0%", message="Retraining CKAAD...")
    train_t0 = time.time()

    def _progress(epoch, total):
        pct = int(epoch / total * 100)
        elapsed = time.time() - train_t0
        update_train_state("shared", "ckaad", "training", progress=f"{pct}%",
                           message=f"CKAAD epoch {epoch}/{total} ({elapsed:.0f}s)")

    try:
        ckaad.fit(list(training_images), progress_callback=_progress)
        elapsed = time.time() - train_t0
        update_train_state("shared", "ckaad", "complete", progress="100%",
                           message=f"CKAAD ready ({elapsed:.1f}s)")
        logger.info(f"CKAAD retraining complete in {elapsed:.1f}s")
    except Exception as e:
        logger.error(f"CKAAD retraining failed: {e}")
        update_train_state("shared", "ckaad", "error", message=str(e))
    return ckaad


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
            frame = _load_live_frame(cam_id, cam_category)
            if frame is None:
                continue

            result = ckaad.detect(frame)
            score = result.anomaly_score if result else 0.0

            rolling_max_scores[cam_id] = max(rolling_max_scores[cam_id], score)
            detection_counters[cam_id] += 1

            image_url, heatmap_url = _save_ckaad_anomaly_frame(score, ckaad, result, frame, zone_name, cam_id)

            run_id = f"ckaad_{int(time.time())}"
            _store_ckaad_result(conn, cam_id, cam_category, ckaad, score, run_id,
                                detection_counters[cam_id], image_url, heatmap_url, rolling_max_scores[cam_id])

            if score > ckaad.threshold * 0.8:
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

        except Exception as e:
            logger.error(f"[{cam_id}] Detection error: {e}", exc_info=True)
            conn.rollback()


def _save_ckaad_anomaly_frame(score, ckaad, result, frame, zone_name, cam_id):
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
        image_url = f"http://localhost:8000/images/anomaly/{zone_name}/{cam_id}/{ts}"
        amap = (result.details or {}).get("anomaly_map")
        if amap is not None:
            heatmap_raw = (amap * 255).clip(0, 255).astype(np.uint8)
            heatmap_img = Image.fromarray(heatmap_raw, mode="L").resize(
                (frame.shape[1], frame.shape[0]), Image.BILINEAR
            )
            heatmap_img.save(str(anomaly_frames_dir / f"{ts}_heatmap.png"))
            image_url = f"http://localhost:8000/images/anomaly/{zone_name}/{cam_id}/{ts}/overlay"
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
