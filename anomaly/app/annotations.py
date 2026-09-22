import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.grafana_client import GrafanaClient
from app.models import RegisteredSource, DashboardDefinition

logger = logging.getLogger(__name__)


async def _lookup_zone_dashboard_uid(source_id: str, db: AsyncSession) -> str | None:
    result = await db.execute(
        select(DashboardDefinition.grafana_uid)
        .join(RegisteredSource, RegisteredSource.zone_id == DashboardDefinition.zone_id)
        .where(
            RegisteredSource.source_id == source_id,
            RegisteredSource.is_active == True,
        )
    )
    row = result.scalar_one_or_none()
    return row


async def _create_annotation_async(
    source_id: str,
    score: float,
    severity: str,
    detector_name: str,
    message: str,
    db: AsyncSession,
) -> None:
    try:
        uid = await _lookup_zone_dashboard_uid(source_id, db)
        if not uid:
            return

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        grafana = GrafanaClient()
        await grafana.create_annotation(
            dashboard_uid=uid,
            time_ms=now_ms,
            tags=["anomaly", severity, source_id, detector_name],
            text=message,
        )
    except Exception as exc:
        logger.debug("Failed to create Grafana annotation: %s", exc)


def fire_annotation(
    source_id: str,
    score: float,
    severity: str,
    detector_name: str,
    message: str,
    db: AsyncSession,
) -> None:
    asyncio.create_task(
        _create_annotation_async(source_id, score, severity, detector_name, message, db)
    )
