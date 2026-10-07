import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from detector.shared import (
    alert_active,
    alert_due,
    clear_alert,
    clear_train,
    compute_severity,
    fusion_lock,
    fusion_state,
    get_db_connection,
    get_setting,
    is_detector_enabled,
    sensor_margin,
    shutdown_event,
    signal_train,
    train_requested,
    update_train_samples,
    update_train_state,
    write_alerts,
)

logger = logging.getLogger("detector.sensor")

SENSOR_INTERVAL = float(os.environ.get("SENSOR_DETECT_INTERVAL", "30"))
MAX_READINGS = int(os.environ.get("SENSOR_MAX_READINGS", "5000"))
RETRAIN_EVERY = int(os.environ.get("SENSOR_RETRAIN_EVERY", "10"))
# Readings before the first fit. The window capping below technically lets a fit
# open at ~20 readings, but an LSTM autoencoder + GMM fitted on a hundred-odd
# samples is not stable: measured over seeds, a fit at 120 readings flagged 0-6
# samples on the same held-out data, while every fit at >= 160 was clean. So the
# first fit waits for a floor that actually contains a signal to learn. A Train
# press is still honoured once the floor is met; this only gates the automatic
# first fit.
MIN_TRAIN_READINGS = int(os.environ.get("SENSOR_MIN_TRAIN_READINGS", "150"))
# One alert per sustained episode: M2AD over the threshold for an hour is one
# anomaly, not 120 rows in `alerts`.
SENSOR_ALERT_COOLDOWN = float(os.environ.get("SENSOR_ALERT_COOLDOWN_S", "300"))

# A periodic refit is held off while an anomaly episode is open, so a fault is
# not fitted as normal. Manual Train and the first fit bypass the gate. The skip
# cannot last forever: after this many consecutive skipped boundaries the refit
# runs regardless, so a stuck flag (or a genuinely sustained fault) does not
# freeze the model indefinitely. When such a forced refit does run, the
# flagged-reading exclusion below drops the rows it already caught — unless
# doing so would starve the fit, in which case the slice is trained on in full
# and the still-flagged rows are learned after all.
MAX_RETRAIN_SKIPS = int(os.environ.get("SENSOR_MAX_RETRAIN_SKIPS", "6"))

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
# p-value cutoff for `is_anomaly`. The library default (0.01) left `area` with
# almost no dynamic range on this data, so the cutoff had been raised to 0.05.
# Measured live at 0.05 the loop flagged ~6.5% of scored timesteps, and those
# flags are ordinary brew dynamics (tank draining, then the level reset) rather
# than faults. Walk-forward refits showed no cutoff that cleanly separates
# normal from fault — normal p-values reach down to ~0.0003 — so this is a
# pragmatic tightening, not a calibrated operating point. Replaying real
# telemetry through the live pipeline put the clean baseline's floor at ~0.019
# (brewing/refill transients), while the injected demo faults reach
# p <= 0.0035; 0.005 sits below the baseline floor with ~4x margin and still
# keeps every injected fault.
SENSOR_PVALUE_THRESHOLD = float(os.environ.get("SENSOR_PVALUE_THRESHOLD", "0.005"))


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


def _has_variation(raw: np.ndarray) -> bool:
    """Whether any channel differs across these readings.

    A flat window is not something to fit or score. `_normalize_data` maps a
    zero-std column to all-zeros, and M2AD's `area` error standardises that
    residue and rolls a centered window over it, so the samples at the window
    boundary come out extreme and `threshold=0.1` flags them on every idle
    pass — the "everything is anomalous" reading on a machine that is simply
    sitting still. With no variation there is no signal to judge, so the loop
    reports idle instead of an anomaly it cannot justify.
    """
    return raw.size > 0 and bool(np.any(np.ptp(raw, axis=0) > 0))


def _report_idle(zone_name: str, message: str) -> None:
    """Report idle and close any open episode.

    Skipping the score leaves `_write_m2ad_alerts_if_needed` unrun, so an
    episode that was already open would keep its cooldown armed and its fused
    score live. An idle window is the episode ending: release the alert and
    zero the sensor's contribution to fusion.
    """
    update_train_state(zone_name, "m2ad", "idle", message=message)
    clear_alert(f"sensor:{zone_name}")
    _update_fusion_sensor_state(zone_name, 0.0, 0, 0.0)


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
    # Anomalous readings flagged by the previous pass, and consecutive periodic
    # boundaries skipped because one was open. Both feed the retrain gate below.
    last_anomaly_count = 0
    retrain_skips = 0

    conn = get_db_connection()

    try:
        while not shutdown_event.is_set():
            loop_start = time.time()

            if not is_detector_enabled(zone_name, "m2ad"):
                shutdown_event.wait(timeout=SENSOR_INTERVAL)
                continue

            # Runtime knobs from the control page, re-read every pass so a
            # change lands without a restart. `get_setting` falls back to the
            # module defaults (the env-var values) when nothing is configured.
            min_train = max(
                MIN_READINGS,
                int(get_setting(zone_name, "m2ad", "min_train_samples") or MIN_TRAIN_READINGS),
            )
            retrain_every = max(1, int(get_setting(zone_name, "m2ad", "retrain_every")))
            auto_retrain = bool(get_setting(zone_name, "m2ad", "auto_retrain"))
            pvalue_threshold = float(get_setting(zone_name, "m2ad", "pvalue_threshold"))

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
                    message = (f"Collecting readings (need >= {MIN_READINGS} per channel; "
                               f"training starts on its own)")
                    logger.info(f"[{zone_name}] M2AD {message}")
                    update_train_samples(zone_name, "m2ad", 0, min_train, SENSOR_INTERVAL)
                    update_train_state(zone_name, "m2ad", "idle", message=message)
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                normalized, raw_array, timestamps = aligned
                if not _has_variation(raw_array):
                    _report_idle(
                        zone_name,
                        "No variation in readings yet (all channels constant); "
                        "nothing to fit or score",
                    )
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                n_total = normalized.shape[0]
                # Report the live count so the control page can show the user
                # how much data a min_train_samples would actually cover.
                update_train_samples(zone_name, "m2ad", n_total, min_train, SENSOR_INTERVAL)
                split = _split_for_training(n_total)
                if split is None:
                    message = f"Collecting readings ({n_total} so far; training starts on its own)"
                    logger.info(f"[{zone_name}] M2AD {message}")
                    update_train_state(zone_name, "m2ad", "idle", message=message)
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                n_train, window_size = split
                train_data = normalized[:n_train]
                train_ts = timestamps[:n_train]
                test_data = normalized[n_train:]
                raw_test = raw_array[n_train:]
                if not _has_variation(raw_test):
                    _report_idle(
                        zone_name,
                        "Scoring window has no variation (machine idle); "
                        "skipping score to avoid false anomalies",
                    )
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                if detector is None and n_total < min_train:
                    message = (f"Collecting readings ({n_total}/{min_train}; "
                               f"training starts on its own)")
                    logger.info(f"[{zone_name}] M2AD {message}")
                    update_train_state(zone_name, "m2ad", "idle", message=message)
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                # Hold the periodic refit off while an anomaly episode is open,
                # so a live fault is not fitted as normal. Manual Train and the
                # first fit ignore this. After MAX_RETRAIN_SKIPS consecutive
                # boundaries the refit runs anyway (the flagged-row exclusion
                # still keeps the fault itself out of the fit). Auto-retrain off
                # closes this path entirely; manual Train still works.
                periodic_due = (
                    auto_retrain and run_count > 0 and run_count % retrain_every == 0
                )
                anomalies_open = (
                    last_anomaly_count > 0 or alert_active(f"sensor:{zone_name}")
                )
                if periodic_due and anomalies_open and retrain_skips < MAX_RETRAIN_SKIPS:
                    periodic_ok = False
                    retrain_skips += 1
                    logger.info(
                        f"[{zone_name}] periodic retrain deferred: anomaly episode open "
                        f"(flagged={last_anomaly_count}, skip {retrain_skips}/{MAX_RETRAIN_SKIPS})"
                    )
                else:
                    periodic_ok = True
                    if periodic_due:
                        if anomalies_open:
                            logger.warning(
                                f"[{zone_name}] periodic retrain force-run after "
                                f"{retrain_skips} deferred boundaries despite an open episode"
                            )
                        retrain_skips = 0

                detector = _train_m2ad_if_needed(
                    detector, zone_name, channel_ids, train_data, train_ts,
                    retrain_requested, run_count, window_size, periodic_ok, conn,
                    retrain_every=retrain_every, pvalue_threshold=pvalue_threshold,
                )
                if detector is None:
                    shutdown_event.wait(timeout=SENSOR_INTERVAL)
                    continue

                # The cutoff is read live so a change applies without a refit.
                detector.threshold = pvalue_threshold

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
                    # A NaN `max_score` would still print and be stored, and
                    # `compute_severity(NaN)` is meaningless, so the score that
                    # feeds severity and logs is zeroed. The detector's own
                    # `is_anomaly` is already False for a NaN p-value, so the
                    # anomaly count needs no sanitizing. The split's test-size
                    # floor keeps the short-slice case away; this is the
                    # backstop.
                    logger.warning(
                        f"[{zone_name}] M2AD produced non-finite scores "
                        f"(degenerate fit); treating them as 0"
                    )
                    scores = [s if np.isfinite(s) else 0.0 for s in scores]
                max_score = float(np.max(scores)) if scores else 0.0
                # `anomaly_score` is `1 - p` (higher is worse); `is_anomaly` is
                # `p < threshold` (0.01). Counting `score > 0.3` here counted
                # `p < 0.7` — a seven-times looser bar than the detector's own
                # verdict — so the alert gate fired on ordinary variation even
                # when nothing was flagged. The alert now follows the detector:
                # how many samples it actually called anomalous.
                anomaly_count = sum(1 for r in results if getattr(r, "is_anomaly", False))
                # Feeds the next iteration's retrain gate: a fault flagged now
                # holds the periodic refit off before it can age into training.
                last_anomaly_count = anomaly_count
                mean_score = float(np.mean(scores)) if scores else 0.0
                run_id = f"{run_id_base}_{int(time.time())}"

                _store_m2ad_results(
                    conn, results, raw_test, timestamps[n_train:],
                    channel_ids, zone_name, run_id, mean_score,
                )
                conn.commit()

                run_count += 1
                logger.info(
                    f"[{zone_name}] Detection #{run_count}: "
                    f"max_score={max_score:.3f}, anomalies={anomaly_count}/{len(scores)}")

                _write_m2ad_alerts_if_needed(conn, zone_name, max_score, anomaly_count, run_id, scores)
                _update_fusion_sensor_state(zone_name, max_score, anomaly_count, pvalue_threshold)

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
            # Always end the transaction. Committing only when a command was
            # found left an empty read parked "idle in transaction" holding an
            # ACCESS SHARE lock on detector_control, which blocks the API's
            # startup DROP TRIGGER (ACCESS EXCLUSIVE) and hangs the boot.
            conn.commit()
            if pending:
                signal_train(zone_name, "m2ad")
                logger.info(f"[{zone_name}] Adopted {len(pending)} pending M2AD train command(s)")
    except Exception:
        conn.rollback()
    return train_requested(zone_name, "m2ad")


def _flagged_timestamps(conn, zone_name, since) -> set:
    """Reading timestamps already flagged as anomalous for this zone.

    A flagged reading is evidence of a fault, not a normal sample, so it must
    not be fitted as baseline. This is the other half of the injection problem:
    a fault sits in the scored slice while it is live (and a refit then still
    sees pre-fault training data), but once it ages out of the scored 20% into
    the training 80% a later periodic refit would learn "fault = normal" — and
    detection of that fault silently degrades from then on. Dropping the flagged
    timestamps keeps a caught fault out of the baseline regardless of age.

    Only faults the detector actually caught can be excluded; a fault that was
    never flagged (too subtle, or already baked in) cannot be identified here.
    """
    if since is None:
        return set()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT timestamp FROM sensor_anomaly_results
                   WHERE detector = 'm2ad' AND details->>'zone' = %s
                   AND timestamp >= %s""",
                (zone_name, since),
            )
            return {row[0] for row in cur.fetchall()}
    except Exception as e:
        # A failed lookup must not take the training slice down with it; fall
        # back to training on the full slice (the previous behaviour).
        conn.rollback()
        logger.warning(f"[{zone_name}] could not load flagged timestamps ({e}); "
                       f"training on all rows this round")
        return set()


def _drop_flagged_rows(conn, zone_name, train_data, train_ts, window_size):
    """The training slice with already-flagged readings removed.

    `train_ts[i]` is the timestamp of `train_data[i]`. Rows whose timestamp was
    flagged are dropped so the fault never becomes baseline. The window was
    sized to the *full* slice, so if the mask would starve the fit (fewer rows
    than the window plus the minimum fit windows) the exclusion is skipped this
    round rather than failing the fit outright.
    """
    if train_data.shape[0] == 0 or not train_ts:
        return train_data
    flagged = _flagged_timestamps(conn, zone_name, train_ts[0])
    if not flagged:
        return train_data
    keep = np.array([ts not in flagged for ts in train_ts], dtype=bool)
    n_drop = int((~keep).sum())
    if n_drop == 0:
        return train_data
    if int(keep.sum()) < window_size + MIN_FIT_SAMPLES + 1:
        logger.warning(
            f"[{zone_name}] {n_drop} flagged reading(s) in the training slice, "
            f"but dropping them would leave too few rows to fit; keeping them "
            f"this round"
        )
        return train_data
    logger.info(f"[{zone_name}] excluding {n_drop} flagged reading(s) from the training slice")
    return train_data[keep]


def _train_m2ad_if_needed(detector, zone_name, channel_ids, train_data, train_ts,
                          retrain_requested, run_count, window_size, periodic_ok, conn,
                          retrain_every: Optional[int] = None,
                          pvalue_threshold: Optional[float] = None):
    from detection.sensor.anomaly import M2AD
    # `retrain_every`/`pvalue_threshold` are the runtime values the loop read
    # from the settings table; their defaults keep the module constants for
    # callers (tests, one-off fits) that do not pass them.
    retrain_every = retrain_every or RETRAIN_EVERY
    threshold = SENSOR_PVALUE_THRESHOLD if pvalue_threshold is None else pvalue_threshold
    # The first fit and a manual Train press always proceed. Only the periodic
    # boundary is gated, and only while an anomaly episode is open.
    periodic_due = periodic_ok and run_count > 0 and run_count % retrain_every == 0
    if not (detector is None or retrain_requested or periodic_due):
        return detector

    train_data = _drop_flagged_rows(conn, zone_name, train_data, train_ts, window_size)

    n_timesteps = train_data.shape[0]
    logger.info(f"[{zone_name}] Training M2AD on collected readings "
                f"({n_timesteps} rows x {len(channel_ids)} cols, window {window_size})")
    update_train_state(zone_name, "m2ad", "training", progress="0%", message="M2AD training on collected readings...")
    new_detector = M2AD(
        f"m2ad_{zone_name}",
        # Every channel is a scored sensor, not a covariate. Without this the
        # library's fallback with more than five columns keeps only the first
        # as a scored sensor and treats the rest as covariates: the scaler is
        # fitted on that one column, the other seven pass through unscaled, and
        # the resulting reconstruction error is dominated by that channel's
        # sharp transitions — a false anomaly on the first scored sample of
        # almost every run.
        sensors=channel_ids,
        window_size=window_size,
        epochs=min(30, max(5, n_timesteps // 50)),
        tolerance=5,
        gamma_thresh=1.0,
        error_name="area",
        # p-value cutoff for `is_anomaly`; the runtime value if one is set, the
        # module default (see SENSOR_PVALUE_THRESHOLD) otherwise.
        threshold=threshold,
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


def _store_m2ad_results(conn, results, test_data, timestamps, channel_ids,
                        zone_name, run_id, mean_score):
    """Persist one row per flagged timestep, attributed to its top channel.

    A flag is one multivariate verdict on one timestep, not one fault on every
    channel: the fused p-value is the same for all eight columns, so writing a
    row per channel exploded each detection into eight identically-scored rows
    (and the dashboard showed all eight channels "critical" at the same
    instant). The row is attributed to the channel with the lowest per-sensor
    p-value — the one that actually moved — so the stored `source_id` and
    `value` point at the evidence for the flag.

    The loop re-fetches and re-scores the same trailing window every interval,
    so the flagged timesteps overlap from run to run. The reading's own
    `timestamp` is stored (not `now()`) and timesteps already present are
    skipped, so a persistent flag is one row per reading rather than one row
    per 30s re-scan.
    """
    import json
    n_sensors = len(channel_ids)

    flagged = []
    for i, r in enumerate(results):
        if not getattr(r, 'is_anomaly', False):
            continue
        details = getattr(r, 'details', None) or {}
        sensor_pvalues = details.get("sensor_pvalues") or {}
        # Attribute to the most anomalous channel; fall back to the first only
        # if the detector could not report per-sensor p-values.
        top_channel = min(sensor_pvalues, key=sensor_pvalues.get) if sensor_pvalues else None
        if top_channel not in channel_ids:
            top_channel = channel_ids[0]
        col_idx = channel_ids.index(top_channel)
        ts = timestamps[i] if i < len(timestamps) else None
        value = float(test_data[i, col_idx]) if i < test_data.shape[0] else None
        flagged.append((top_channel, ts, value, float(r.anomaly_score), sensor_pvalues))

    if not flagged:
        return

    ts_values = [ts for _, ts, _, _, _ in flagged if ts is not None]
    existing = set()
    if ts_values:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT timestamp FROM sensor_anomaly_results
                   WHERE source_id = ANY(%s) AND timestamp >= %s AND timestamp <= %s""",
                (list(channel_ids), min(ts_values), max(ts_values)),
            )
            existing = {row[0] for row in cur.fetchall()}

    with conn.cursor() as cur:
        for top_channel, ts, value, score, sensor_pvalues in flagged:
            if ts is not None and ts in existing:
                continue
            existing.add(ts)
            cur.execute(
                """INSERT INTO sensor_anomaly_results
                   (source_id, detector, run_id, timestamp, anomaly_score, is_anomaly, value, details)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    top_channel, "m2ad", run_id,
                    ts if ts is not None else datetime.now(timezone.utc),
                    float(score), True, value,
                    json.dumps({
                        "zone": zone_name,
                        "severity": compute_severity(float(score)),
                        "mean_score": float(mean_score),
                        "n_channels": n_sensors,
                        "sensor_pvalues": sensor_pvalues,
                    }),
                ),
            )


def _write_m2ad_alerts_if_needed(conn, zone_name, max_score, anomaly_count, run_id, scores):
    alert_key = f"sensor:{zone_name}"
    if anomaly_count == 0:
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


def _update_fusion_sensor_state(zone_name, max_score, anomaly_count, pvalue_threshold):
    """Publish the sensor's contribution to the fusion loop.

    `max_score` is `1 - p` (higher is worse). Fusion needs a margin over the
    sensor's OWN cutoff, not a raw score: `sensor_margin` reports how many
    decades the run's smallest p-value falls below `pvalue_threshold`, so the
    camera side and the sensor side are on the same 0..1 scale. A clean run
    contributes margin 0. The raw `max_score` is kept alongside it for the
    alert message and logs.
    """
    margin = sensor_margin(pvalue_threshold, max_score) if anomaly_count > 0 else 0.0
    with fusion_lock:
        if zone_name not in fusion_state:
            fusion_state[zone_name] = {
                "sensor_max_score": 0.0,
                "camera_max_score": 0.0,
                "sensor_anomaly_count": 0,
                "sensor_margin": 0.0,
                "camera_margin": 0.0,
            }
        fusion_state[zone_name]["sensor_max_score"] = (
            float(max_score) if anomaly_count > 0 else 0.0
        )
        fusion_state[zone_name]["sensor_margin"] = float(margin)
        fusion_state[zone_name]["sensor_anomaly_count"] = int(anomaly_count)
