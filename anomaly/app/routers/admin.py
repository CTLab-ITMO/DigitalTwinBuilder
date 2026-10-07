import asyncio
import json
import logging
import os
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Zone, RegisteredSource, DetectorConfig, DashboardDefinition,
    DetectorControl, DetectorSetting,
)
from app.grafana_client import GrafanaClient
from app.dashboard_templates import build_zone_dashboard
from app.control_page import CONTROL_PAGE_HTML
from app.config_loader import load_config_from_file, DEFAULT_CONFIG_PATH

logger = logging.getLogger(__name__)

router = APIRouter()

# The detector's status sidecar, reached over the compose network. The service
# is named `anomaly-detector`; the old `detector` host did not resolve, so every
# training-panel poll fell back to "idle" no matter what the detector reported.
DETECTOR_STATUS_URL = os.environ.get(
    "DETECTOR_STATUS_URL", "http://anomaly-detector:9100/status"
)

# The effective values shown when no row has been written. These mirror the
# detector's own defaults (detector/shared.py `_SETTING_DEFAULTS`): the API image
# does not copy the detector package, so the two small tables are kept in sync by
# hand. `pvalue_threshold` is M2AD-only — CKAAD's cutoff is a fitted percentile,
# not a p-value.
DETECTOR_SETTING_DEFAULTS: dict = {
    "m2ad": {
        "enabled": True,
        "auto_retrain": True,
        "min_train_samples": 150,
        "retrain_every": 10,
        "pvalue_threshold": 0.005,
        "score_threshold": None,
    },
    "ckaad": {
        "enabled": True,
        "auto_retrain": True,
        "min_train_samples": 200,
        "retrain_every": 50,
        "pvalue_threshold": None,
        # Absolute CKAAD score cutoff. NULL on the shared row means "use the
        # model's calibrated value"; a value there is the fallback for cameras
        # with no per-zone override of their own.
        "score_threshold": None,
    },
    "fusion": {
        # Cross-modal sensitivity S, carried in the `score_threshold` column.
        # Fusion fires when the smaller of the two normalized margins (sensor,
        # camera) is strictly greater than S; 0 means both must be past their
        # own cutoff.
        "score_threshold": 0.0,
    },
}

# The tunable columns, in the order the control page presents them.
SETTING_FIELDS = (
    "enabled",
    "auto_retrain",
    "min_train_samples",
    "retrain_every",
    "pvalue_threshold",
    "score_threshold",
)


class ZoneCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ZoneResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    sensor_count: int = 0
    camera_count: int = 0


class SourceCreate(BaseModel):
    source_id: str
    source_type: str
    zone_id: Optional[int] = None
    display_name: Optional[str] = None
    metadata: Optional[dict] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None
    connection_info: Optional[dict] = None
    detector_type: Optional[str] = None
    detector_parameters: Optional[dict] = None


class SourceResponse(BaseModel):
    id: int
    source_id: str
    source_type: str
    zone_id: Optional[int] = None
    display_name: Optional[str] = None
    is_active: bool
    connection_info: Optional[dict] = None


class DashboardResponse(BaseModel):
    id: int
    zone_id: int
    zone_name: str
    grafana_uid: str
    title: Optional[str] = None
    dashboard_url: Optional[str] = None
    version: int = 1


class GenerateResponse(BaseModel):
    regenerated: int
    zones: List[DashboardResponse]


async def _ensure_grafana_zone_dashboard(
    zone: Zone,
    db: AsyncSession,
    grafana: GrafanaClient,
) -> DashboardDefinition:
    result = await db.execute(
        select(RegisteredSource)
        .where(RegisteredSource.zone_id == zone.id, RegisteredSource.is_active == True)
    )
    sources = result.scalars().all()

    dashboard_json = build_zone_dashboard(zone, sources)
    uid = dashboard_json["uid"]

    existing_meta = await grafana.get_dashboard(uid)
    if existing_meta:
        dashboard_json["version"] = existing_meta["dashboard"]["version"]

    url = await grafana.create_or_update_dashboard(dashboard_json)

    result = await db.execute(
        select(DashboardDefinition).where(DashboardDefinition.grafana_uid == uid)
    )
    dd = result.scalar_one_or_none()

    if dd:
        dd.title = dashboard_json["title"]
        dd.dashboard_url = url
        dd.version = (dd.version or 0) + 1
    else:
        dd = DashboardDefinition(
            zone_id=zone.id,
            grafana_uid=uid,
            title=dashboard_json["title"],
            dashboard_url=url,
            version=1,
        )
        db.add(dd)

    await db.commit()
    await db.refresh(dd)
    return dd


@router.post("/zones", response_model=ZoneResponse)
async def create_zone(body: ZoneCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Zone).where(Zone.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Zone '{body.name}' already exists")

    zone = Zone(name=body.name, description=body.description)
    db.add(zone)
    await db.commit()
    await db.refresh(zone)

    return ZoneResponse(
        id=zone.id,
        name=zone.name,
        description=zone.description,
    )


@router.get("/zones", response_model=List[ZoneResponse])
async def list_zones(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Zone).order_by(Zone.name))
    zones = result.scalars().all()

    responses = []
    for zone in zones:
        src_result = await db.execute(
            select(
                sa_func.count().filter(RegisteredSource.source_type == "sensor").label("sensor_count"),
                sa_func.count().filter(RegisteredSource.source_type == "camera").label("camera_count"),
            ).where(
                RegisteredSource.zone_id == zone.id,
                RegisteredSource.is_active == True,
            )
        )
        counts = src_result.one()
        responses.append(ZoneResponse(
            id=zone.id,
            name=zone.name,
            description=zone.description,
            sensor_count=int(counts.sensor_count or 0),
            camera_count=int(counts.camera_count or 0),
        ))
    return responses


@router.post("/sources", response_model=SourceResponse)
async def register_source(body: SourceCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(RegisteredSource).where(RegisteredSource.source_id == body.source_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Source '{body.source_id}' already registered",
        )

    if body.source_type not in ("sensor", "camera"):
        raise HTTPException(status_code=400, detail="source_type must be 'sensor' or 'camera'")

    conn_info = body.connection_info or {}
    if body.ip:
        conn_info["ip"] = body.ip
    if body.port is not None:
        conn_info["port"] = body.port
    if body.protocol:
        conn_info["protocol"] = body.protocol

    source = RegisteredSource(
        source_id=body.source_id,
        source_type=body.source_type,
        zone_id=body.zone_id,
        display_name=body.display_name,
        metadata_json=body.metadata,
        connection_info=conn_info or None,
        is_active=True,
    )
    db.add(source)

    if body.detector_type:
        config = DetectorConfig(
            source_id=body.source_id,
            detector_type=body.detector_type,
            parameters=body.detector_parameters or {},
            is_active=True,
        )
        db.add(config)

    await db.commit()
    await db.refresh(source)

    return SourceResponse(
        id=source.id,
        source_id=source.source_id,
        source_type=source.source_type,
        zone_id=source.zone_id,
        display_name=source.display_name,
        is_active=source.is_active,
        connection_info=source.connection_info,
    )


async def deactivate_source(source_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RegisteredSource).where(RegisteredSource.source_id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")

    source.is_active = False
    await db.commit()

    return {"status": "deactivated", "source_id": source_id}


@router.get("/sources", response_model=List[SourceResponse])
async def list_sources(
    zone_id: Optional[int] = Query(None),
    source_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RegisteredSource).where(RegisteredSource.is_active == True)

    if zone_id is not None:
        stmt = stmt.where(RegisteredSource.zone_id == zone_id)
    if source_type is not None:
        stmt = stmt.where(RegisteredSource.source_type == source_type)

    stmt = stmt.order_by(RegisteredSource.source_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        SourceResponse(
            id=r.id,
            source_id=r.source_id,
            source_type=r.source_type,
            zone_id=r.zone_id,
            display_name=r.display_name,
            is_active=r.is_active,
            connection_info=r.connection_info,
        )
        for r in rows
    ]


@router.post("/dashboards/generate", response_model=GenerateResponse)
async def regenerate_dashboards(db: AsyncSession = Depends(get_db)):
    grafana = GrafanaClient()

    result = await db.execute(select(Zone).order_by(Zone.name))
    zones = result.scalars().all()

    if not zones:
        raise HTTPException(status_code=400, detail="No zones configured. Create a zone first.")

    created: list[DashboardResponse] = []
    for zone in zones:
        dd = await _ensure_grafana_zone_dashboard(zone, db, grafana)
        created.append(
            DashboardResponse(
                id=dd.id,
                zone_id=zone.id,
                zone_name=zone.name,
                grafana_uid=dd.grafana_uid,
                title=dd.title,
                dashboard_url=dd.dashboard_url,
                version=dd.version,
            )
        )

    return GenerateResponse(regenerated=len(created), zones=created)


@router.get("/dashboards", response_model=List[DashboardResponse])
async def list_dashboards(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DashboardDefinition, Zone.name)
        .join(Zone, DashboardDefinition.zone_id == Zone.id)
        .order_by(Zone.name)
    )
    rows = result.all()

    return [
        DashboardResponse(
            id=dd.id,
            zone_id=dd.zone_id,
            zone_name=zone_name,
            grafana_uid=dd.grafana_uid,
            title=dd.title,
            dashboard_url=dd.dashboard_url,
            version=dd.version,
        )
        for dd, zone_name in rows
    ]


class ConfigLoadResponse(BaseModel):
    message: str
    zones_created: int = 0
    zones_updated: int = 0
    sources_registered: int = 0
    sources_updated: int = 0
    dashboards_generated: int = 0


class DetectorCommand(BaseModel):
    zone_name: str = "*"
    detector_type: str = "*"


class DetectorControlCommand(BaseModel):
    zone_name: str = "*"
    detector_type: str = "*"
    command: str


@router.post("/detector/train")
async def issue_train(body: DetectorCommand, db: AsyncSession = Depends(get_db)):
    dc = DetectorControl(
        zone_name=body.zone_name,
        detector_type=body.detector_type,
        command="train",
    )
    db.add(dc)
    await db.commit()
    return {
        "status": "issued",
        "command": "train",
        "zone_name": body.zone_name,
        "detector_type": body.detector_type,
    }


@router.post("/detector/control")
async def issue_control(body: DetectorControlCommand, db: AsyncSession = Depends(get_db)):
    if body.command not in ("enable", "disable"):
        raise HTTPException(status_code=400, detail="command must be 'enable' or 'disable'")
    dc = DetectorControl(
        zone_name=body.zone_name,
        detector_type=body.detector_type,
        command=body.command,
    )
    db.add(dc)
    # Persist the choice in the settings table too, so it survives a detector
    # restart and the control page shows the same state the command produced.
    await _upsert_setting_enabled(
        db, body.zone_name, body.detector_type, body.command == "enable"
    )
    await db.commit()
    return {
        "status": "issued",
        "command": body.command,
        "zone_name": body.zone_name,
        "detector_type": body.detector_type,
    }


@router.post("/detector/reset")
async def issue_reset(body: DetectorCommand, db: AsyncSession = Depends(get_db)):
    dc = DetectorControl(
        zone_name=body.zone_name,
        detector_type=body.detector_type,
        command="reset",
    )
    db.add(dc)
    await db.commit()
    return {
        "status": "issued",
        "command": "reset",
        "zone_name": body.zone_name,
        "detector_type": body.detector_type,
    }


async def _fetch_detector_train_state() -> dict:
    """The detector's live train state, or `{"_error": ...}` when unreachable.

    Shared by `/detector/status` and the settings endpoint. Never raises: a
    detector that is down should leave the settings readable rather than 500.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for attempt in range(3):
                try:
                    resp = await client.get(DETECTOR_STATUS_URL)
                    if resp.status_code == 200:
                        return resp.json()
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    if attempt < 2:
                        await asyncio.sleep(1)
                        continue
                    logger.warning(f"Detector status unreachable after {attempt+1} attempts: {e}")
                    raise
    except Exception as e:
        logger.warning(f"Training state fetch failed: {type(e).__name__}: {e}")
        return {"_error": "detector status endpoint unreachable"}
    return {}


@router.get("/detector/status")
async def get_detector_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DetectorControl)
        .where(DetectorControl.executed_at.is_(None))
        .order_by(DetectorControl.issued_at.desc())
    )
    pending = result.scalars().all()

    latest_subq = (
        select(
            DetectorControl,
            sa_func.row_number().over(
                partition_by=[DetectorControl.zone_name, DetectorControl.detector_type],
                order_by=DetectorControl.issued_at.desc(),
            ).label("rn"),
        )
        .subquery()
    )
    result = await db.execute(
        select(DetectorControl)
        .select_from(latest_subq)
        .join(
            DetectorControl,
            DetectorControl.id == latest_subq.c.id,
        )
        .where(latest_subq.c.rn == 1)
        .order_by(DetectorControl.zone_name, DetectorControl.detector_type)
    )
    latest_cmds = result.scalars().all()

    train_state = await _fetch_detector_train_state()

    return {
        "pending_trains": sum(
            1 for c in pending if c.command == "train"
        ),
        "pending_controls": [
            {"id": c.id, "zone": c.zone_name, "type": c.detector_type, "command": c.command}
            for c in pending
        ],
        "latest_commands": [
            {
                "zone": c.zone_name,
                "type": c.detector_type,
                "command": c.command,
                "issued_at": c.issued_at.isoformat() if c.issued_at else None,
                "executed_at": c.executed_at.isoformat() if c.executed_at else None,
            }
            for c in latest_cmds
        ],
        "training_state": train_state,
    }


class DetectorSettingsUpdate(BaseModel):
    zone_name: str
    detector_type: str
    enabled: Optional[bool] = None
    auto_retrain: Optional[bool] = None
    min_train_samples: Optional[int] = None
    retrain_every: Optional[int] = None
    pvalue_threshold: Optional[float] = None
    # Per-zone absolute CKAAD cutoff, the `shared` fallback when the row is
    # `("shared", "ckaad")`, or the cross-modal sensitivity when the row is
    # `(zone, "fusion")`.
    score_threshold: Optional[float] = None


def _effective_settings(row: Optional[DetectorSetting], dtype: str) -> dict:
    """The defaults for a detector type, overridden by any set column.

    A NULL column means "unset" — not "false"/"zero" — so it falls through to
    the default; only a value someone actually wrote wins.
    """
    out = dict(DETECTOR_SETTING_DEFAULTS.get(dtype, {}))
    if row is not None:
        for field in SETTING_FIELDS:
            value = getattr(row, field)
            if value is not None:
                out[field] = value
    return out


async def _detector_setting_targets(db: AsyncSession, rows) -> list[tuple[str, str]]:
    """Every `(zone, detector_type)` the control page should show.

    The zones table is the M2AD list, each zone also gets a cross-modal
    `fusion` entry (its sensitivity), and CKAAD is the one global `shared`
    entry; rows are folded in too, so a setting written for a zone that has
    since been removed is still visible and editable rather than orphaned.

    A real-zone `ckaad` row is deliberately not a target: those rows exist only
    to carry a per-zone `score_threshold` (see `/detector/settings`'s
    `ckaad_zones`). Rendering them as cards would repeat the global CKAAD knobs
    once per camera zone and imply each copy were independent.
    """
    zones = (await db.execute(select(Zone.name).order_by(Zone.name))).scalars().all()
    targets = {(z, "m2ad") for z in zones}
    targets |= {(z, "fusion") for z in zones}
    targets.add(("shared", "ckaad"))
    for r in rows:
        if r.detector_type == "ckaad" and r.zone_name != "shared":
            continue
        targets.add((r.zone_name, r.detector_type))
    return sorted(targets)


async def _upsert_setting_enabled(
    db: AsyncSession, zone_name: str, detector_type: str, enabled: bool
) -> None:
    """Mirror an enable/disable command into the settings row.

    `/detector/control` writes a `detector_control` row that the detector
    applies immediately; the settings table is what makes the choice survive a
    detector restart. Keeping both in step means the settings poller re-asserts
    the same value instead of fighting the command.
    """
    if zone_name == "*" or detector_type == "*":
        return
    result = await db.execute(
        select(DetectorSetting).where(
            DetectorSetting.zone_name == zone_name,
            DetectorSetting.detector_type == detector_type,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        db.add(DetectorSetting(
            zone_name=zone_name, detector_type=detector_type, enabled=enabled,
        ))
    else:
        row.enabled = enabled


@router.get("/detector/settings")
async def get_detector_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DetectorSetting))
    rows = result.scalars().all()
    by_key = {(r.zone_name, r.detector_type): r for r in rows}

    train_state = await _fetch_detector_train_state()
    if "_error" in train_state:
        train_state = {}

    settings = []
    # One threshold override per real zone, for the CKAAD card's per-zone
    # subsection. The m2ad targets enumerate exactly the configured zones, in
    # name order; `None` means "no override, use the shared/calibrated value".
    ckaad_zones = []
    for zone_name, detector_type in await _detector_setting_targets(db, rows):
        item = {
            "zone_name": zone_name,
            "detector_type": detector_type,
            **_effective_settings(by_key.get((zone_name, detector_type)), detector_type),
        }
        item["training_state"] = train_state.get(f"{zone_name}:{detector_type}", {})
        settings.append(item)
        if detector_type == "m2ad":
            override = by_key.get((zone_name, "ckaad"))
            ckaad_zones.append({
                "zone_name": zone_name,
                "score_threshold": override.score_threshold if override else None,
            })

    return {
        "settings": settings,
        "defaults": DETECTOR_SETTING_DEFAULTS,
        "ckaad_zones": ckaad_zones,
    }


@router.put("/detector/settings")
async def update_detector_settings(
    body: DetectorSettingsUpdate, db: AsyncSession = Depends(get_db)
):
    if body.detector_type not in DETECTOR_SETTING_DEFAULTS:
        raise HTTPException(status_code=400, detail="unknown detector_type")
    if body.min_train_samples is not None and body.min_train_samples < 1:
        raise HTTPException(status_code=400, detail="min_train_samples must be >= 1")
    if body.retrain_every is not None and body.retrain_every < 1:
        raise HTTPException(status_code=400, detail="retrain_every must be >= 1")
    if body.pvalue_threshold is not None and body.pvalue_threshold <= 0:
        raise HTTPException(status_code=400, detail="pvalue_threshold must be > 0")
    if body.score_threshold is not None and body.score_threshold < 0:
        raise HTTPException(status_code=400, detail="score_threshold must be >= 0")
    # Fusion reuses `score_threshold` for the cross-modal sensitivity, which is
    # a normalized margin, so it is capped at 1 (the max any margin can reach).
    if (body.detector_type == "fusion" and body.score_threshold is not None
            and body.score_threshold > 1):
        raise HTTPException(status_code=400, detail="fusion sensitivity must be <= 1")

    result = await db.execute(
        select(DetectorSetting).where(
            DetectorSetting.zone_name == body.zone_name,
            DetectorSetting.detector_type == body.detector_type,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = DetectorSetting(zone_name=body.zone_name, detector_type=body.detector_type)
        db.add(row)

    for field in SETTING_FIELDS:
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
        elif field == "score_threshold" and field in body.model_fields_set:
            # An explicit `null` clears a per-zone override, reverting the zone
            # to the shared/calibrated cutoff. Only this field is nullable on
            # purpose; the others are "unset means leave as is".
            setattr(row, field, None)

    await db.commit()
    await db.refresh(row)

    return {
        "status": "saved",
        "zone_name": row.zone_name,
        "detector_type": row.detector_type,
        **_effective_settings(row, row.detector_type),
    }


@router.get("/control", response_class=HTMLResponse)
async def detector_control_page():
    return CONTROL_PAGE_HTML


@router.post("/config/load", response_model=ConfigLoadResponse)
async def load_config(
    path: Optional[str] = Query(None, description="Path to config.json"),
    db: AsyncSession = Depends(get_db),
):
    config_path = path or DEFAULT_CONFIG_PATH
    grafana = GrafanaClient()

    try:
        summary = await load_config_from_file(config_path, db, grafana)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in config file: {e}")

    return ConfigLoadResponse(
        message=f"Config loaded from {config_path}",
        **summary,
    )
