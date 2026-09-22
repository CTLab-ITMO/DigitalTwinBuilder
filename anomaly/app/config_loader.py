import json
import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Zone, RegisteredSource, DetectorConfig, DashboardDefinition
from app.grafana_client import GrafanaClient
from app.dashboard_templates import build_zone_dashboard

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")


async def load_config_from_file(
    config_path: str,
    db: AsyncSession,
    grafana: GrafanaClient,
) -> dict:
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = json.load(f)

    summary = {
        "zones_created": 0,
        "zones_updated": 0,
        "sources_registered": 0,
        "sources_updated": 0,
        "dashboards_generated": 0,
    }

    for zone_name, zone_data in raw.items():
        result = await db.execute(select(Zone).where(Zone.name == zone_name))
        zone = result.scalar_one_or_none()
        if zone:
            zone.description = zone_data.get("description", zone.description)
            summary["zones_updated"] += 1
        else:
            zone = Zone(
                name=zone_name,
                description=zone_data.get("description", f"Zone: {zone_name}"),
            )
            db.add(zone)
            await db.flush()
            summary["zones_created"] += 1

        await db.refresh(zone)

        sensors = zone_data.get("sensors", {})
        if isinstance(sensors, list):
            for item in sensors:
                await _upsert_source(
                    db, zone, item["id"], "sensor", item, summary
                )
        elif isinstance(sensors, dict):
            for src_id, src_info in sensors.items():
                await _upsert_source(
                    db, zone, src_id, "sensor", src_info, summary
                )

        cameras = zone_data.get("cameras", {})
        if isinstance(cameras, list):
            for item in cameras:
                await _upsert_source(
                    db, zone, item["id"], "camera", item, summary
                )
        elif isinstance(cameras, dict):
            for src_id, src_info in cameras.items():
                await _upsert_source(
                    db, zone, src_id, "camera", src_info, summary
                )

        await _ensure_zone_dashboard(zone, db, grafana)
        summary["dashboards_generated"] += 1

    await db.commit()
    return summary


async def _upsert_source(
    db: AsyncSession,
    zone: Zone,
    source_id: str,
    source_type: str,
    src_info: dict,
    summary: dict,
) -> None:
    result = await db.execute(
        select(RegisteredSource).where(RegisteredSource.source_id == source_id)
    )
    source = result.scalar_one_or_none()

    connection_info = {}
    for key in ("ip", "port", "protocol"):
        if key in src_info:
            connection_info[key] = src_info[key]

    metadata = {k: v for k, v in src_info.items() if k not in ("ip", "port", "protocol", "display_name", "detector")}

    if source:
        source.source_type = source_type
        source.zone_id = zone.id
        source.display_name = src_info.get("display_name", source_id)
        source.connection_info = connection_info or None
        source.metadata_json = metadata or None
        source.is_active = True
        summary["sources_updated"] += 1
    else:
        source = RegisteredSource(
            source_id=source_id,
            source_type=source_type,
            zone_id=zone.id,
            display_name=src_info.get("display_name", source_id),
            connection_info=connection_info or None,
            metadata_json=metadata or None,
            is_active=True,
        )
        db.add(source)
        await db.flush()
        summary["sources_registered"] += 1

    detector_info = src_info.get("detector", {})
    if detector_info:
        det_type = detector_info.get("type", "")
        if det_type:
            result = await db.execute(
                select(DetectorConfig).where(
                    DetectorConfig.source_id == source_id,
                    DetectorConfig.is_active == True,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.detector_type = det_type
                existing.parameters = detector_info.get("parameters", {})
            else:
                db.add(DetectorConfig(
                    source_id=source_id,
                    detector_type=det_type,
                    parameters=detector_info.get("parameters", {}),
                    is_active=True,
                ))


async def _ensure_zone_dashboard(
    zone: Zone,
    db: AsyncSession,
    grafana: GrafanaClient,
) -> None:
    result = await db.execute(
        select(RegisteredSource).where(
            RegisteredSource.zone_id == zone.id,
            RegisteredSource.is_active == True,
        )
    )
    sources = result.scalars().all()

    dashboard_json = build_zone_dashboard(zone, sources)
    uid = dashboard_json["uid"]

    url = await grafana.create_or_update_dashboard(dashboard_json)

    result = await db.execute(
        select(DashboardDefinition).where(DashboardDefinition.grafana_uid == uid)
    )
    dd = result.scalar_one_or_none()
    if dd:
        dd.title = dashboard_json["title"]
        dd.dashboard_url = url
        dd.version = DashboardDefinition.version + 1
    else:
        dd = DashboardDefinition(
            zone_id=zone.id,
            grafana_uid=uid,
            title=dashboard_json["title"],
            dashboard_url=url,
            version=1,
        )
        db.add(dd)
