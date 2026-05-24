from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB init — wrapped in try/except so a slow DB doesn't break /health
    try:
        from backend.database import engine, Base
        Base.metadata.create_all(bind=engine)
        log.info("Database tables created/verified")
    except Exception as e:
        log.error(f"DB init failed (will retry on next request): {e}")

    # Start APScheduler
    try:
        from backend.pipeline.cron import hourly_sync, daily_retention_cleanup
        scheduler.add_job(
            hourly_sync,
            "interval",
            hours=settings.SYNC_INTERVAL_HOURS,
            id="hourly_sync",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            daily_retention_cleanup,
            "cron",
            hour=3,
            minute=0,
            id="daily_cleanup",
            replace_existing=True,
        )
        scheduler.start()
        log.info(f"APScheduler started: sync every {settings.SYNC_INTERVAL_HOURS}h, cleanup daily at 03:00 UTC")
    except Exception as e:
        log.error(f"Scheduler start failed: {e}")

    yield

    scheduler.shutdown(wait=False)
    log.info("APScheduler shut down")


app = FastAPI(
    title="LeadHunt API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routers import auth, strategy, leads, monitor, analytics

app.include_router(auth.router)
app.include_router(strategy.router)
app.include_router(leads.router)
app.include_router(monitor.router)
app.include_router(analytics.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "leadhunt-api"}


@app.get("/")
def root():
    return {"service": "LeadHunt API", "docs": "/docs"}
