"""Read-only views of the sensor results.

Detection is not driven from here: `anomaly-detector` polls the user's Modbus
sensors into `sensor_readings` and M2AD scores them, so this API only reports
what the detector wrote.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SensorAnomalyResult, Alert

router = APIRouter()


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
