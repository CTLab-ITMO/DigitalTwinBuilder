import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import engine, async_session
from app.models import Base
from app.routers import sensors, images, admin
from app.grafana_client import GrafanaClient
from app.config_loader import load_config_from_file, DEFAULT_CONFIG_PATH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# `init.sql` only runs on a brand-new Postgres volume, so the fix that lets
# CKAAD's 'shared' pseudo-zone through the detector_control zone check has to be
# re-applied here for a stack that already has data. Every statement is
# idempotent, so this is safe on every boot. Run one at a time: asyncpg's
# prepared-statement path rejects multiple commands in a single execute.
#
# The `DROP TRIGGER` takes an ACCESS EXCLUSIVE lock on detector_control, so a
# detector connection parked "idle in transaction" on that table would block
# startup indefinitely -- and startup never reaches the config load, leaving no
# zone dashboard. `lock_timeout` bounds the wait; on timeout the whole migration
# transaction rolls back and boot continues with the trigger as it already was.
_DETECTOR_CONTROL_TRIGGER_MIGRATION = [
    "SET LOCAL lock_timeout = '3000ms'",
    """
    CREATE OR REPLACE FUNCTION check_detector_control_zone()
    RETURNS trigger AS $$
    BEGIN
        IF NEW.zone_name NOT IN ('*', '', 'shared')
           AND NOT EXISTS (SELECT 1 FROM zones WHERE name = NEW.zone_name) THEN
            RAISE EXCEPTION 'zone_name % is not a valid zone name (use * for all)', NEW.zone_name;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_detector_control_zone ON detector_control",
    """
    CREATE TRIGGER trg_detector_control_zone
        BEFORE INSERT OR UPDATE ON detector_control
        FOR EACH ROW
        EXECUTE FUNCTION check_detector_control_zone()
    """,
]

# `create_all` only creates missing tables, so a `detector_settings` that
# predates the per-zone score threshold needs the column added in place. Like
# the trigger migration above, `ADD COLUMN` takes an ACCESS EXCLUSIVE lock that
# a detector connection parked "idle in transaction" can hold off startup, so
# bound the wait and continue with the column absent on timeout.
_DETECTOR_SETTINGS_COLUMN_MIGRATION = [
    "SET LOCAL lock_timeout = '3000ms'",
    "ALTER TABLE detector_settings ADD COLUMN IF NOT EXISTS score_threshold DOUBLE PRECISION",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")

    try:
        async with engine.begin() as conn:
            for stmt in _DETECTOR_CONTROL_TRIGGER_MIGRATION:
                await conn.execute(text(stmt))
        logger.info("detector_control zone trigger relaxed for the 'shared' pseudo-zone.")
    except Exception as exc:
        logger.warning("detector_control trigger migration failed: %s", exc)

    try:
        async with engine.begin() as conn:
            for stmt in _DETECTOR_SETTINGS_COLUMN_MIGRATION:
                await conn.execute(text(stmt))
        logger.info("detector_settings score_threshold column ensured.")
    except Exception as exc:
        logger.warning("detector_settings column migration failed: %s", exc)

    try:
        grafana = GrafanaClient()
        if await grafana.health_check():
            logger.info("Grafana reachable at %s", grafana.base_url)
        else:
            logger.warning("Grafana not reachable at %s", grafana.base_url)
    except Exception as exc:
        logger.warning("Grafana connectivity check failed: %s", exc)

    # The session's config is written into this volume by the `config-sync`
    # sidecar before this container starts, so a fresh `docker compose up`
    # registers the session's zone and sources and provisions its dashboard.
    # Logged, never fatal: a stack with no config still serves the API.
    config_path = os.path.abspath(DEFAULT_CONFIG_PATH)
    if os.path.exists(config_path):
        try:
            async with async_session() as db:
                summary = await load_config_from_file(config_path, db, GrafanaClient())
            logger.info("Loaded config from %s: %s", config_path, summary)
        except Exception as exc:
            logger.warning("Config load from %s failed: %s", config_path, exc)
    else:
        logger.info("No config at %s; nothing to load on startup", config_path)

    yield
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(title="Anomaly Detection API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sensors.router, prefix="/sensors", tags=["sensors"])
app.include_router(images.router, prefix="/images", tags=["images"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "anomaly-detection-api"}
