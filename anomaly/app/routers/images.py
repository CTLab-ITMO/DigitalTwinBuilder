"""Read-only views of the camera results, plus the anomaly frames themselves.

Detection is not driven from here: `anomaly-detector` captures frames from the
user's RTSP streams and CKAAD scores them, so this API only reports what the
detector wrote. The `/anomaly/...` routes serve the frames the Grafana alerts
panel links to.
"""
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ImageDetectionResult

router = APIRouter()


class ImageResultResponse(BaseModel):
    id: int
    category: str
    detector: str
    run_id: str
    timestamp: datetime
    image_name: Optional[str] = None
    label: Optional[str] = None
    is_anomaly: Optional[bool] = None
    anomaly_score: Optional[float] = None
    auroc_image: Optional[float] = None
    auroc_pixel: Optional[float] = None
    pro_score: Optional[float] = None


@router.get("/results")
async def get_image_results(
    category: Optional[str] = Query(None),
    detector: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ImageDetectionResult).order_by(ImageDetectionResult.id.desc()).limit(limit)

    if category:
        stmt = stmt.where(ImageDetectionResult.source_id == category)
    if detector:
        stmt = stmt.where(ImageDetectionResult.detector == detector)
    if run_id:
        stmt = stmt.where(ImageDetectionResult.run_id == run_id)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        ImageResultResponse(
            id=r.id,
            category=r.source_id,
            detector=r.detector,
            run_id=r.run_id,
            timestamp=r.timestamp,
            image_name=r.image_name,
            label=r.label,
            is_anomaly=r.is_anomaly,
            anomaly_score=r.anomaly_score,
            auroc_image=r.auroc_image,
            auroc_pixel=r.auroc_pixel,
            pro_score=r.pro_score,
        )
        for r in rows
    ]


ANOMALY_FRAME_DIR = Path("/anomaly_frames")


@router.get("/anomaly/{zone_name}/{camera_id}/{timestamp}")
async def get_anomaly_frame(zone_name: str, camera_id: str, timestamp: int):
    path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}.png"
    if not path.exists():
        path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Anomaly frame not found")
    return FileResponse(str(path), media_type="image/png")


@router.get("/anomaly/{zone_name}/{camera_id}/{timestamp}/heatmap")
async def get_anomaly_heatmap(zone_name: str, camera_id: str, timestamp: int):
    path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}_heatmap.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Anomaly heatmap not found")
    return FileResponse(str(path), media_type="image/png")


@router.get("/anomaly/{zone_name}/{camera_id}/{timestamp}/overlay")
async def get_anomaly_overlay(zone_name: str, camera_id: str, timestamp: int):
    orig_path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}.png"
    heat_path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}_heatmap.png"
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="Anomaly frame not found")
    orig = Image.open(str(orig_path)).convert("RGBA")
    if heat_path.exists():
        heat = Image.open(str(heat_path)).convert("L").resize(orig.size, Image.BILINEAR)
        h = np.array(heat, dtype=np.float32) / 255.0
        r = np.clip((h - 0.35) * 4, 0, 1)
        g = np.clip(1 - np.abs(h - 0.5) * 3.5, 0, 1)
        b = np.clip((0.5 - h) * 3.5, 0, 1)
        alpha = np.clip(h * 0.75, 0, 1)
        overlay_arr = np.stack([
            (r * 255).clip(0, 255).astype(np.uint8),
            (g * 255).clip(0, 255).astype(np.uint8),
            (b * 255).clip(0, 255).astype(np.uint8),
            (alpha * 255).clip(0, 255).astype(np.uint8),
        ], axis=-1)
        overlay = Image.fromarray(overlay_arr, "RGBA")
        orig = Image.alpha_composite(orig, overlay)
    out = orig.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")
