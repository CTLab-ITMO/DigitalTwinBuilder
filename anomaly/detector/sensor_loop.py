import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from detector.shared import (
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

logger = logging.getLogger("detector.sensor")

SENSOR_INTERVAL = float(os.environ.get("SENSOR_DETECT_INTERVAL", "30"))
MAX_READINGS = int(os.environ.get("SENSOR_MAX_READINGS", "5000"))
RETRAIN_EVERY = int(os.environ.get("SENSOR_RETRAIN_EVERY", "10"))


def _fetch_sensor_readings(
    conn, channel_ids: List[str]
) -> Optional[Dict[str, List[Tuple[datetime, float]]]]:
    channel_map: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)

    with conn.cursor() as cur:
        for cid in channel_ids:
            cur.execute(
                """SELECT channel_id, timestamp, value
                   FROM sensor_readings
                   WHERE channel_id = %s
                   ORDER BY timestamp DESC
                   LIMIT %s""",
                (cid, MAX_READINGS),
            )
            for channel_id, ts, value in cur.fetchall():
                channel_map[cid].append((ts, value))

    result = {}
    for cid in channel_ids:
        entries = channel_map.get(cid, [])
        entries.sort(key=lambda x: x[0])
        result[cid] = entries
    return result


def _align_and_pivot(
    channel_data: Dict[str, List[Tuple[datetime, float]]],
) -> Optional[Tuple[np.ndarray, np.ndarray, List[datetime]]]:
    if not channel_data:
        return None

    lengths = [len(v) for v in channel_data.values()]
    min_len = min(lengths)
    if min_len < 10:
        return None

    n_channels = len(channel_data)
    raw_array = np.zeros((min_len, n_channels), dtype=np.float32)
    first_cid = list(channel_data.keys())[0]
    timestamps = [t for t, _ in channel_data[first_cid][-min_len:]]
    for col_idx, (cid, entries) in enumerate(channel_data.items()):
        raw_array[:, col_idx] = np.array([v for _, v in entries[-min_len:]], dtype=np.float32)

    normalized = _normalize_data(raw_array.copy())
    return normalized, raw_array, timestamps


def _normalize_data(data: np.ndarray) -> np.ndarray:
    means = np.nanmean(data, axis=0, keepdims=True)
    stds = np.nanstd(data, axis=0, keepdims=True)
    stds[stds == 0] = 1.0
    return (data - means) / stds


def sensor_detection_loop(zone_name: str, channel_ids: List[str]):
    from detection.sensor.anomaly import M2AD

    logger.info(f"[{zone_name}] Sensor detection loop started ({len(channel_ids)} channels)")

    detector: Optional[M2AD] = None
    run_count = 0
    run_id_base = f"detector_{zone_name}"

    conn = get_db_connection()

    try:
        while not shutdown_event.is_set():
            loop_start = time.time()

            if not is_detector_enabled(zone_name, "m2ad"):
                shutdown_event.wait(timeout=SENSOR_INTERVAL)
                continue

            force_retrain = _check_m2ad_train_signal(zone_name, conn)

            if detector is None and not force_retrain:
                update_train_state(zone_name, "m2ad", "idle", message="Awaiting Train button")
                shutdown_event.wait(timeout=5)
                continue

            try:
                channel_data = _fetch_sensor_readings(conn, channel_ids)
                aligned = _align_and_pivot(channel_data)
                if aligned is None:
                    logger.warning(
                        f"[{zone_name}] Not enough collected readings yet "
                        f"(need >= 10 per channel in sensor_readings)"
                    )
                    time.sleep(SENSOR_INTERVAL)
                    continue

                normalized, raw_array, _ = aligned
                n_total = normalized.shape[0]
                n_train = max(10, int(n_total * 0.8))
                train_data = normalized[:n_train]
                test_data = normalized[n_train:]
                raw_test = raw_array[n_train:]

                n_timesteps = train_data.shape[0]
                test_n = test_data.shape[0]
                window_size = min(100, max(10, n_timesteps // 2))
                if test_n <= window_size:
                    logger.warning(
                        f"[{zone_name}] Not enough collected readings for a test window "
                        f"({test_n} <= {window_size})"
                    )
                    time.sleep(SENSOR_INTERVAL)
                    continue

                detector = _train_m2ad_if_needed(
                    detector, zone_name, channel_ids, train_data,
                    force_retrain, run_count, window_size, n_timesteps
                )
                if detector is None:
                    time.sleep(SENSOR_INTERVAL)
                    continue

                results = detector.detect_batch(test_data)
                if not results:
                    time.sleep(SENSOR_INTERVAL)
                    continue

                scores = [r.anomaly_score if hasattr(r, 'anomaly_score') else float(r.score) for r in results]
                max_score = float(np.max(scores)) if scores else 0.0
                anomaly_count = sum(1 for s in scores if s > 0.3)
                mean_score = float(np.mean(scores)) if scores else 0.0
                run_id = f"{run_id_base}_{int(time.time())}"

                _store_m2ad_results(conn, results, raw_test, channel_ids, zone_name, run_id, mean_score)
                conn.commit()

                run_count += 1
                logger.info(
                    f"[{zone_name}] Detection #{run_count}: "
                    f"max_score={max_score:.3f}, anomalies={anomaly_count}/{len(scores)}")

                _write_m2ad_alerts_if_needed(conn, zone_name, max_score, anomaly_count, run_id, scores)
                _update_fusion_sensor_state(zone_name, max_score, anomaly_count)

            except Exception as e:
                logger.error(f"[{zone_name}] Detection error: {e}", exc_info=True)
                conn.rollback()

            elapsed = time.time() - loop_start
            sleep_time = max(1, SENSOR_INTERVAL - elapsed)
            if sleep_time > 0:
                shutdown_event.wait(timeout=sleep_time)

    finally:
        conn.close()
        logger.info(f"[{zone_name}] Sensor detection loop stopped")


def _check_m2ad_train_signal(zone_name: str, conn) -> bool:
    from psycopg2.extras import RealDictCursor
    force_retrain = check_and_clear_train(zone_name, "m2ad")
    if force_retrain:
        logger.info(f"[{zone_name}] Train signaled for M2AD")
        return True

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id FROM detector_control
                   WHERE zone_name = %s AND detector_type = 'm2ad'
                   AND command = 'train' AND executed_at IS NULL
                   ORDER BY issued_at ASC LIMIT 1""",
                (zone_name,)
            )
            pending = cur.fetchone()
            if pending:
                logger.info(f"[{zone_name}] Found pending train in DB, setting force_retrain")
                cur.execute(
                    "UPDATE detector_control SET executed_at = NOW() WHERE id = %s",
                    (pending["id"],)
                )
                conn.commit()
                return True
    except Exception:
        conn.rollback()
    return False


def _train_m2ad_if_needed(detector, zone_name, channel_ids, train_data,
                          force_retrain, run_count, window_size, n_timesteps):
    from detection.sensor.anomaly import M2AD
    if not (detector is None or force_retrain or (run_count > 0 and run_count % RETRAIN_EVERY == 0)):
        return detector

    n_sensors = len(channel_ids)
    logger.info(f"[{zone_name}] Training M2AD on collected readings ({n_timesteps} rows x {n_sensors} cols)")
    update_train_state(zone_name, "m2ad", "training", progress="0%", message="M2AD training on collected readings...")
    new_detector = M2AD(
        f"m2ad_{zone_name}",
        window_size=window_size,
        epochs=min(30, max(5, n_timesteps // 50)),
        tolerance=5,
        gamma_thresh=1.0,
        error_name="area",
        threshold=0.1,
    )

    train_t0 = time.time()

    def _m2ad_progress(epoch, total, zone_name=zone_name):
        pct = int(epoch / total * 100)
        elapsed = time.time() - train_t0
        update_train_state(zone_name, "m2ad", "training", progress=f"{pct}%",
                           message=f"M2AD epoch {epoch}/{total} ({elapsed:.0f}s)")

    new_detector.fit(train_data, progress_callback=_m2ad_progress)
    elapsed = time.time() - train_t0
    update_train_state(zone_name, "m2ad", "complete", progress="100%",
                       message=f"M2AD trained on collected readings ({elapsed:.1f}s)")
    logger.info(f"[{zone_name}] M2AD training complete in {elapsed:.1f}s on {n_timesteps} rows")
    return new_detector


def _store_m2ad_results(conn, results, test_data, channel_ids, zone_name, run_id, mean_score):
    import json
    n_sensors = len(channel_ids)
    with conn.cursor() as cur:
        for i in range(len(results)):
            r = results[i]
            score = r.anomaly_score if hasattr(r, 'anomaly_score') else float(r.score)
            is_anom = r.is_anomaly if hasattr(r, 'is_anomaly') else bool(score > 0.3)
            if not is_anom:
                continue
            ts_now = datetime.now(timezone.utc)
            for col_idx, cid in enumerate(channel_ids):
                sensor_val = float(test_data[i, col_idx]) if i < test_data.shape[0] else None
                cur.execute(
                    """INSERT INTO sensor_anomaly_results
                       (source_id, detector, run_id, timestamp, anomaly_score, is_anomaly, value, details)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        cid, "m2ad", run_id, ts_now,
                        float(score), True, sensor_val,
                        json.dumps({
                            "zone": zone_name,
                            "severity": compute_severity(float(score)),
                            "mean_score": float(mean_score),
                            "n_channels": n_sensors,
                        }),
                    ),
                )


def _write_m2ad_alerts_if_needed(conn, zone_name, max_score, anomaly_count, run_id, scores):
    if max_score <= 0.3:
        return
    severity = compute_severity(max_score)
    alerts = [
        {
            "source_id": zone_name,
            "alert_type": "sensor_anomaly",
            "severity": severity,
            "message": (
                f"[{zone_name}] M2AD detected {anomaly_count} anomalous "
                f"readings (max score: {max_score:.3f})"
            ),
            "score": float(max_score),
            "run_id": run_id,
        }
    ]
    write_alerts(conn, alerts)


def _update_fusion_sensor_state(zone_name, max_score, anomaly_count):
    with fusion_lock:
        if zone_name not in fusion_state:
            fusion_state[zone_name] = {
                "sensor_max_score": 0.0,
                "camera_max_score": 0.0,
                "sensor_anomaly_count": 0,
            }
        fusion_state[zone_name]["sensor_max_score"] = float(max_score)
        fusion_state[zone_name]["sensor_anomaly_count"] = int(anomaly_count)
