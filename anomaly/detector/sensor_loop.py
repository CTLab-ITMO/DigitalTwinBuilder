import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from detector.shared import (
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

logger = logging.getLogger("detector.sensor")

SENSOR_INTERVAL = float(os.environ.get("SENSOR_DETECT_INTERVAL", "30"))
MAX_READINGS = int(os.environ.get("SENSOR_MAX_READINGS", "5000"))
RETRAIN_EVERY = int(os.environ.get("SENSOR_RETRAIN_EVERY", "10"))
# One alert per sustained episode: M2AD over the threshold for an hour is one
# anomaly, not 120 rows in `alerts`.
SENSOR_ALERT_COOLDOWN = float(os.environ.get("SENSOR_ALERT_COOLDOWN_S", "300"))

# Readings per channel needed before anything can be aligned at all.
MIN_READINGS = 10
# M2AD's sliding window yields `length - window_size` samples, and its `area`
# error rolls a `score_window` (10) window with `min_periods=5` — fewer errors
# than that and the GMM is fitted on NaNs. The fit side needs more than the bare
# `min_periods`: with only five training windows every p-value comes out
# identical, the GMM's `gamma` shape collapses to 0 and every score is NaN
# (measured over 25 seeds, five windows is always degenerate and nine never is).
# Capping the window by both sides is what lets a fresh stack train on ~20
# readings instead of the ~500 a fixed `window_size = min(100, ...)` demanded.
SCORE_WINDOW = 10
MIN_ERROR_SAMPLES = SCORE_WINDOW // 2  # area_errors' rolling min_periods
MIN_FIT_SAMPLES = 9
MIN_WINDOW = 2
MAX_WINDOW = 100
TEST_FRACTION = 0.2


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
    if min_len < MIN_READINGS:
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


def _split_for_training(n_total: int) -> Optional[Tuple[int, int]]:
    """`(n_train, window_size)` sized to the readings available.

    The test split is everything after `n_train`. `sliding_window_sequences`
    turns `length` rows into `length - window_size` samples, so the window is
    capped to leave `MIN_FIT_SAMPLES` windows to fit on and `MIN_ERROR_SAMPLES`
    to score; the extra `- 1` on each cap is headroom, not slack the fit needs.
    The old fixed `window_size = min(100, ...)` with a `test_n > window_size`
    gate could not open below ~500 readings, so a fresh stack never trained at
    all.
    """
    test_n = max(MIN_WINDOW + MIN_ERROR_SAMPLES + 1, int(n_total * TEST_FRACTION))
    n_train = n_total - test_n
    window_size = min(
        MAX_WINDOW,
        n_train - MIN_FIT_SAMPLES - 1,
        test_n - MIN_ERROR_SAMPLES - 1,
    )
    if window_size < MIN_WINDOW:
        return None
    return n_train, window_size


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

            # A Train press is durable and optional. Read, never consumed here:
            # it stays outstanding until a fit succeeds, so one press that lands
            # before there is data is honoured later. And the loop trains on its
            # own as soon as there is enough, so a press is a re-train trigger
            # rather than a prerequisite.
            retrain_requested = _m2ad_train_requested(zone_name, conn)

            try:
                channel_data = _fetch_sensor_readings(conn, channel_ids)
                aligned = _align_and_pivot(channel_data)
                if aligned is None:
                    update_train_state(
                        zone_name, "m2ad", "idle",
                        message=f"Collecting readings (need >= {MIN_READINGS} per channel; "
                                f"training starts on its own)",
                    )
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                normalized, raw_array, _ = aligned
                n_total = normalized.shape[0]
                split = _split_for_training(n_total)
                if split is None:
                    update_train_state(
                        zone_name, "m2ad", "idle",
                        message=f"Collecting readings ({n_total} so far; training starts on its own)",
                    )
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                n_train, window_size = split
                train_data = normalized[:n_train]
                test_data = normalized[n_train:]
                raw_test = raw_array[n_train:]

                detector = _train_m2ad_if_needed(
                    detector, zone_name, channel_ids, train_data,
                    retrain_requested, run_count, window_size
                )
                if detector is None:
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                results = detector.detect_batch(test_data)
                if not results:
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                scores = [r.anomaly_score if hasattr(r, 'anomaly_score') else float(r.score) for r in results]
                if not all(np.isfinite(s) for s in scores):
                    # `area_errors` standardises by the error's own std and
                    # rolls with `min_periods = SCORE_WINDOW // 2`, so a detect
                    # slice shorter than that is all-NaN and a zero-variance
                    # error divides by zero — either way the scores are NaN.
                    # NaN fails the `> 0.3` count and `max_score <= 0.3` is
                    # False, so an alert carrying a NaN score would be written
                    # every interval. A score that is not a number is not an
                    # anomaly: it becomes 0 so no alert is written. The split's
                    # test-size floor keeps the short-slice case away; this is
                    # the backstop.
                    logger.warning(
                        f"[{zone_name}] M2AD produced non-finite scores "
                        f"(degenerate fit); treating them as 0"
                    )
                    scores = [s if np.isfinite(s) else 0.0 for s in scores]
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


def _m2ad_train_requested(zone_name: str, conn) -> bool:
    """Whether M2AD has an outstanding Train press.

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
                   WHERE zone_name = %s AND detector_type = 'm2ad'
                   AND command = 'train' AND executed_at IS NULL
                   ORDER BY issued_at ASC""",
                (zone_name,)
            )
            pending = cur.fetchall()
            for row in pending:
                cur.execute(
                    "UPDATE detector_control SET executed_at = NOW() WHERE id = %s",
                    (row["id"],)
                )
            if pending:
                conn.commit()
                signal_train(zone_name, "m2ad")
                logger.info(f"[{zone_name}] Adopted {len(pending)} pending M2AD train command(s)")
    except Exception:
        conn.rollback()
    return train_requested(zone_name, "m2ad")


def _train_m2ad_if_needed(detector, zone_name, channel_ids, train_data,
                          retrain_requested, run_count, window_size):
    from detection.sensor.anomaly import M2AD
    if not (detector is None or retrain_requested
            or (run_count > 0 and run_count % RETRAIN_EVERY == 0)):
        return detector

    n_timesteps = train_data.shape[0]
    logger.info(f"[{zone_name}] Training M2AD on collected readings "
                f"({n_timesteps} rows x {len(channel_ids)} cols, window {window_size})")
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

    if not new_detector.fit(train_data, progress_callback=_m2ad_progress):
        # `M2AD.fit` swallows its own exception and returns False. Reporting
        # "complete" here would score for the rest of the run with an untrained
        # model and would spend a Train press nobody honoured, so the request
        # stays outstanding and the next iteration retries.
        logger.error(f"[{zone_name}] M2AD training failed; will retry")
        update_train_state(zone_name, "m2ad", "error", progress="",
                           message="M2AD training failed; retrying")
        return None

    elapsed = time.time() - train_t0
    clear_train(zone_name, "m2ad")
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
    alert_key = f"sensor:{zone_name}"
    if max_score <= 0.3:
        # The episode is over; release the cooldown so the next one alerts at
        # once rather than waiting out the previous episode's window.
        clear_alert(alert_key)
        return
    if not alert_due(alert_key, SENSOR_ALERT_COOLDOWN):
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
