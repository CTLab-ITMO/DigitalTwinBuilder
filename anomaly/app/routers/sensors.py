import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SensorReading, SensorAnomalyResult, Alert
from app.annotations import fire_annotation
_M2AD = None
_MTGFlowDetector = None


def _get_detection_classes():
    global _M2AD, _MTGFlowDetector
    if _M2AD is None:
        from detection.sensor.anomaly import M2AD as M, MTGFlowDetector as Mt
        _M2AD, _MTGFlowDetector = M, Mt
    return _M2AD, _MTGFlowDetector


logger = logging.getLogger(__name__)

router = APIRouter()


class SeedResponse(BaseModel):
    run_id: str
    channels_loaded: int
    total_rows: int
    datasets: List[str]


class DetectResponse(BaseModel):
    run_id: str
    detector: str
    channel_id: str
    n_anomalies: int
    n_total: int
    anomaly_ratio: float


class SensorResultResponse(BaseModel):
    id: int
    channel_id: str
    detector: str
    run_id: str
    timestamp: datetime
    anomaly_score: Optional[float] = None
    is_anomaly: Optional[bool] = None


class AlertResponse(BaseModel):
    id: int
    source_id: Optional[str] = None
    alert_type: Optional[str] = None
    severity: Optional[str] = None
    message: Optional[str] = None
    score: Optional[float] = None
    run_id: Optional[str] = None
    timestamp: Optional[datetime] = None


def _load_smap_msl_datasets():
    import kagglehub
    import ast
    import pandas as pd

    path = kagglehub.dataset_download("patrickfleith/nasa-anomaly-detection-dataset-smap-msl")
    labels = pd.read_csv(os.path.join(path, "labeled_anomalies.csv"))

    channels = []
    for chan_id in labels["chan_id"].unique():
        if "P-" in chan_id:
            dataset_name = "SMAP"
        elif "M-" in chan_id:
            dataset_name = "MSL"
        else:
            continue

        train_path = os.path.join(path, "data", "data", "train", f"{chan_id}.npy")
        test_path = os.path.join(path, "data", "data", "test", f"{chan_id}.npy")
        if not os.path.exists(train_path) or not os.path.exists(test_path):
            continue

        train_data = np.load(train_path, allow_pickle=True)
        test_data = np.load(test_path, allow_pickle=True)

        channel_label = labels[labels["chan_id"] == chan_id]
        anomaly_indices = set()
        if len(channel_label) > 0:
            anomaly_sequences = ast.literal_eval(channel_label.iloc[0]["anomaly_sequences"])
            for seq in anomaly_sequences:
                anomaly_indices.update(range(seq[0], seq[1]))

        ground_truth = np.array(
            ["anomaly" if i in anomaly_indices else "normal" for i in range(len(test_data))]
        )

        channels.append({
            "dataset": dataset_name,
            "chan_id": chan_id,
            "train_data": train_data,
            "test_data": test_data,
            "ground_truth": ground_truth,
        })

    return channels


def _load_smd_dataset():
    import kagglehub

    path = kagglehub.dataset_download("mgusat/smd-onmiad")
    base = os.path.join(path, "ServerMachineDataset")

    channels = []
    for fname in sorted(os.listdir(os.path.join(base, "train"))):
        if not fname.endswith(".txt"):
            continue
        chan_id = fname.replace(".txt", "")

        train_path = os.path.join(base, "train", fname)
        test_path = os.path.join(base, "test", fname)
        label_path = os.path.join(base, "test_label", fname)

        if not os.path.exists(train_path) or not os.path.exists(test_path):
            continue

        train_data = np.loadtxt(train_path, delimiter=",")
        test_data = np.loadtxt(test_path, delimiter=",")

        if train_data.ndim == 1:
            train_data = train_data.reshape(-1, 1)
        if test_data.ndim == 1:
            test_data = test_data.reshape(-1, 1)

        if os.path.exists(label_path):
            gt = np.loadtxt(label_path, dtype=str)
            if gt.ndim == 0:
                gt = gt.reshape(1)
            ground_truth = np.array(["anomaly" if v == "1" else "normal" for v in gt])
        else:
            ground_truth = np.array(["normal"] * len(test_data))

        channels.append({
            "dataset": "SMD",
            "chan_id": chan_id,
            "train_data": train_data,
            "test_data": test_data,
            "ground_truth": ground_truth,
        })

    return channels


def _insert_sensor_readings(session: AsyncSession, channel: dict, run_id: str) -> int:
    rows = []
    now = datetime.now(timezone.utc)

    train = channel["train_data"]
    if train.ndim == 1:
        train = train.reshape(-1, 1)
    for i in range(len(train)):
        for fi in range(train.shape[1]):
            rows.append({
                "channel_id": channel["chan_id"],
                "dataset": channel["dataset"],
                "timestamp": now,
                "value": float(train[i, fi]),
                "feature_index": fi,
                "ground_truth": None,
            })

    test = channel["test_data"]
    gt = channel["ground_truth"]
    if test.ndim == 1:
        test = test.reshape(-1, 1)
    for i in range(len(test)):
        for fi in range(test.shape[1]):
            rows.append({
                "channel_id": channel["chan_id"],
                "dataset": channel["dataset"],
                "timestamp": now,
                "value": float(test[i, fi]),
                "feature_index": fi,
                "ground_truth": bool(gt[i] == "anomaly") if i < len(gt) else False,
            })

    if rows:
        session.execute(insert(SensorReading), rows)
    return len(rows)


@router.post("/seed")
async def seed_sensors(db: AsyncSession = Depends(get_db)):
    run_id = str(uuid.uuid4())
    total_rows = 0
    datasets_seen = set()

    try:
        smap_msl = _load_smap_msl_datasets()
        smd = _load_smd_dataset()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load datasets: {e}")

    for ch in smap_msl + smd:
        n = _insert_sensor_readings(db, ch, run_id)
        total_rows += n
        datasets_seen.add(ch["dataset"])

    await db.commit()

    return SeedResponse(
        run_id=run_id,
        channels_loaded=len(smap_msl) + len(smd),
        total_rows=total_rows,
        datasets=sorted(datasets_seen),
    )


@router.post("/detect/{detector_name}")
async def detect_sensors(
    detector_name: str,
    channel_id: str = Query(..., description="Channel ID to run detection on"),
    run_id: Optional[str] = Query(None, description="Optional run ID to group results"),
    db: AsyncSession = Depends(get_db),
):
    readings = await _fetch_sensor_readings(db, channel_id)
    if not readings:
        raise HTTPException(status_code=404, detail=f"No data found for channel {channel_id}")

    feature_map = {}
    for r in readings:
        fi = r.feature_index or 0
        if fi not in feature_map:
            feature_map[fi] = []
        feature_map[fi].append(r.value)

    n_features = len(feature_map)
    if n_features == 0:
        raise HTTPException(status_code=400, detail="Empty sensor data")

    data_array, train_data, test_data = _readings_to_array(feature_map)
    if len(train_data) < 10:
        train_data = data_array
        test_data = data_array

    detector = _init_sensor_detector(detector_name)
    logger.info(f"Training {detector_name} on {len(train_data)} samples for channel {channel_id}")
    if not detector.fit(train_data):
        raise HTTPException(status_code=500, detail=f"Detector {detector_name} failed to train")

    results = _run_sensor_inference(detector, test_data, detector_name)

    run_id = run_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    n_anomalies, anomaly_rows, alert_rows = _build_result_rows(
        results, detector_name, run_id, now, len(data_array) - len(test_data), channel_id, db
    )

    if anomaly_rows:
        await db.execute(insert(SensorAnomalyResult), anomaly_rows)
    if alert_rows:
        await db.execute(insert(Alert), alert_rows)

    await db.commit()

    return DetectResponse(
        run_id=run_id,
        detector=detector_name.lower(),
        channel_id=channel_id,
        n_anomalies=n_anomalies,
        n_total=len(results),
        anomaly_ratio=n_anomalies / len(results) if results else 0.0,
    )


async def _fetch_sensor_readings(db: AsyncSession, channel_id: str):
    result = await db.execute(
        select(SensorReading)
        .where(SensorReading.channel_id == channel_id)
        .order_by(SensorReading.id)
    )
    return result.scalars().all()


def _readings_to_array(feature_map: dict):
    sorted_features = sorted(feature_map.keys())
    n_timesteps = len(feature_map[sorted_features[0]])
    n_features = len(feature_map)
    data_array = np.zeros((n_timesteps, n_features))
    for col_idx, fi in enumerate(sorted_features):
        data_array[:, col_idx] = np.array(feature_map[fi])
    train_size = int(len(data_array) * 0.8)
    return data_array, data_array[:train_size], data_array[train_size:]


def _init_sensor_detector(detector_name: str):
    detector_name_lower = detector_name.lower()
    try:
        M2AD, MTGFlowDetector = _get_detection_classes()
        if detector_name_lower == "m2ad":
            return M2AD("m2ad", window_size=100, epochs=30, tolerance=5,
                        gamma_thresh=1.0, error_name="area", threshold=0.1)
        elif detector_name_lower == "mtgflow":
            return MTGFlowDetector("mtgflow", window_size=60, epochs=20, threshold=0.5)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown detector: {detector_name}. Use: m2ad, mtgflow",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize detector: {e}")


def _run_sensor_inference(detector, test_data, detector_name):
    logger.info(f"Running detection for {detector_name} on {len(test_data)} samples")
    if hasattr(detector, "detect_batch") and hasattr(detector, "window_size"):
        return detector.detect_batch(test_data)
    results = []
    for i in range(len(test_data)):
        sample = test_data[i]
        r = detector.detect(sample)
        results.append(r)
        detector.update(sample, is_normal=not r.is_anomaly)
    return results


async def _build_result_rows(results, detector_name, run_id, now, train_offset, channel_id, db):
    n_anomalies = 0
    anomaly_rows = []
    alert_rows = []

    for i, res in enumerate(results):
        ts = now
        is_anomaly = res.is_anomaly
        if is_anomaly:
            n_anomalies += 1

        anomaly_rows.append({
            "channel_id": channel_id,
            "detector": detector_name.lower(),
            "run_id": run_id,
            "timestamp": ts,
            "anomaly_score": res.anomaly_score,
            "is_anomaly": is_anomaly,
            "details": res.details,
        })

        if is_anomaly:
            severity = "low"
            if res.anomaly_score >= 0.8:
                severity = "critical"
            elif res.anomaly_score >= 0.6:
                severity = "high"
            elif res.anomaly_score >= 0.3:
                severity = "medium"

            alert_rows.append({
                "source_id": channel_id,
                "alert_type": "anomaly",
                "severity": severity,
                "message": f"{detector_name}: anomaly detected at point {train_offset + i} "
                f"(score={res.anomaly_score:.4f}, type={res.anomaly_type})",
                "score": res.anomaly_score,
                "run_id": run_id,
                "timestamp": ts,
            })

            fire_annotation(
                source_id=channel_id,
                score=res.anomaly_score,
                severity=severity,
                detector_name=detector_name,
                message=f"{detector_name}: anomaly at point {train_offset + i} (score={res.anomaly_score:.4f})",
                db=db,
            )

    return n_anomalies, anomaly_rows, alert_rows


@router.get("/results")
async def get_sensor_results(
    channel_id: Optional[str] = Query(None),
    detector: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SensorAnomalyResult).order_by(SensorAnomalyResult.id.desc()).limit(limit)

    if channel_id:
        stmt = stmt.where(SensorAnomalyResult.source_id == channel_id)
    if detector:
        stmt = stmt.where(SensorAnomalyResult.detector == detector)
    if run_id:
        stmt = stmt.where(SensorAnomalyResult.run_id == run_id)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        SensorResultResponse(
            id=r.id,
            channel_id=r.source_id,
            detector=r.detector,
            run_id=r.run_id,
            timestamp=r.timestamp,
            anomaly_score=r.anomaly_score,
            is_anomaly=r.is_anomaly,
        )
        for r in rows
    ]


@router.get("/alerts")
async def get_sensor_alerts(
    source_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Alert).order_by(Alert.timestamp.desc()).limit(limit)

    if source_id:
        stmt = stmt.where(Alert.source_id == source_id)
    if severity:
        stmt = stmt.where(Alert.severity == severity)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        AlertResponse(
            id=r.id,
            source_id=r.source_id,
            alert_type=r.alert_type,
            severity=r.severity,
            message=r.message,
            score=r.score,
            run_id=r.run_id,
            timestamp=r.timestamp,
        )
        for r in rows
    ]
