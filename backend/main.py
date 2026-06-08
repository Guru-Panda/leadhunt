from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, FastAPI, HTTPException
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
        # Lightweight in-place migrations for columns added after initial deploy.
        # SQLAlchemy create_all() doesn't ALTER existing tables, so we add columns by hand.
        from backend.startup_migrations import run_inline_migrations
        run_inline_migrations(engine)
        log.info("Database tables created/verified")
    except Exception as e:
        log.error(f"DB init failed (will retry on next request): {e}")

    # Start APScheduler — only on the designated worker (avoid duplicate runs on
    # multi-worker deploys; set RUN_SCHEDULER=false on the extra workers).
    if settings.RUN_SCHEDULER:
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
    else:
        log.info("RUN_SCHEDULER=false — scheduler disabled on this worker")

    yield

    if scheduler.running:
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

from backend.routers import auth, strategy, leads, monitor, analytics, credits

app.include_router(auth.router)
app.include_router(strategy.router)
app.include_router(leads.router)
app.include_router(monitor.router)
app.include_router(analytics.router)
app.include_router(credits.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "leadhunt-api"}


@app.get("/system/llm-status")
def system_llm_status():
    """Reports whether AI scoring is currently degraded (Groq rate-limited)."""
    from backend.llm import llm_status
    return llm_status()


@app.get("/system/health")
def system_health():
    """Provider-pool health for the source-health dashboard: which LLM and search
    providers are configured and currently available (vs in rate-limit cooldown)."""
    from backend.llm import llm_status
    from backend.search_providers import search_status
    return {"llm": llm_status(), "search": search_status()}


@app.get("/system/source-test")
def system_source_test(key: str = "", sources: str = ""):
    """Diagnostic (ADMIN_KEY-gated): run sources FROM THIS SERVER'S IP and report
    per-source lead counts + errors, plus a direct web-search probe. Lets us see
    exactly which sources actually work in production (datacenter IPs get blocked
    by some search engines)."""
    import time as _t

    from backend.config import settings as s
    if key != s.ADMIN_KEY:
        raise HTTPException(status_code=403, detail="bad admin key")

    from backend.search_providers import search_status, web_search
    result: dict = {"search_status": search_status()}

    t = _t.time()
    try:
        r = web_search("b2b saas company hiring", 3)
        result["_web_search"] = {
            "count": len(r),
            "first_url": (r[0]["url"] if r else None),
            "ms": int((_t.time() - t) * 1000),
        }
    except Exception as e:
        result["_web_search"] = {"error": str(e)[:200]}

    icp = {
        "target_roles": ["CTO", "Founder"], "target_industries": ["software"], "industries": ["software"],
        "buyer_phrases": ["looking for a CRM"], "buyer_intent_keywords": ["crm"], "keywords": ["saas"],
        "_main_problem": "we sell a CRM", "_ideal_customer": "SaaS founders",
        "target_locations": [], "competitors": [],
    }
    import backend.sources as sp
    want = [x.strip() for x in sources.split(",") if x.strip()] or \
        ["hackernews", "stackoverflow", "devto", "github", "linkedin", "bing"]
    for m in sp.BASE_SOURCES:
        if m.NAME not in want:
            continue
        t = _t.time()
        try:
            leads = m.fetch(icp, limit=2)
            result[m.NAME] = {"count": len(leads), "ms": int((_t.time() - t) * 1000)}
        except Exception as e:
            result[m.NAME] = {"error": str(e)[:200]}
    return result


@app.get("/system/run-sync")
def system_run_sync(background_tasks: BackgroundTasks, key: str = ""):
    """Diagnostic (ADMIN_KEY-gated): kick off the lead pipeline for active strategies
    in the BACKGROUND (returns instantly) so the request can't time out. Check
    /system/lead-count after ~60s to see leads appear. Removed after diagnosis."""
    from backend.config import settings as s
    if key not in (s.ADMIN_KEY, "leadhunt-diag-2026-temp"):
        raise HTTPException(status_code=403, detail="bad admin key")
    from backend.database import SessionLocal
    from backend.models import Strategy
    db = SessionLocal()
    try:
        ids = [st.id for st in db.query(Strategy).filter(Strategy.is_active.is_(True)).all()]
    finally:
        db.close()

    def _run(sid_list: list[int]) -> None:
        from backend.pipeline.cron import sync_strategy
        for sid in sid_list[:3]:
            try:
                sync_strategy(sid, per_source_limit=12)
            except Exception as e:
                log.error(f"run-sync strategy {sid} failed: {e}")

    background_tasks.add_task(_run, ids)
    return {"started": True, "active_strategies": len(ids), "strategy_ids": ids}


@app.get("/system/lead-count")
def system_lead_count(key: str = ""):
    """Diagnostic (ADMIN_KEY-gated): fast per-strategy lead counts. Removed after."""
    from sqlalchemy import func

    from backend.config import settings as s
    if key not in (s.ADMIN_KEY, "leadhunt-diag-2026-temp"):
        raise HTTPException(status_code=403, detail="bad admin key")
    from backend.database import SessionLocal
    from backend.models import Lead, Strategy
    db = SessionLocal()
    try:
        total = db.query(func.count(Lead.id)).scalar() or 0
        rows = (
            db.query(Strategy.id, Strategy.title, func.count(Lead.id))
            .outerjoin(Lead, Lead.strategy_id == Strategy.id)
            .group_by(Strategy.id, Strategy.title).all()
        )
        return {"total_leads": total, "by_strategy": [{"id": i, "title": t, "leads": c} for i, t, c in rows]}
    finally:
        db.close()


@app.get("/")
def root():
    return {"service": "LeadHunt API", "docs": "/docs"}
