import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app.models import Base
from app.routers import sensors, images, admin
from app.grafana_client import GrafanaClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")

    try:
        grafana = GrafanaClient()
        if await grafana.health_check():
            logger.info("Grafana reachable at %s", grafana.base_url)
        else:
            logger.warning("Grafana not reachable at %s", grafana.base_url)
    except Exception as exc:
        logger.warning("Grafana connectivity check failed: %s", exc)

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
