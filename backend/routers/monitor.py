from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import DiscoveredSource, Lead, Strategy, SyncRun, User
from backend.schemas import AddCustomURLRequest, DiscoveredSourceOut, SyncRunOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/source-stats")
def source_stats(
    strategy_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Per-source health snapshot: last_run, total leads, with-email %, avg score, recent error."""
    from collections import defaultdict
    from sqlalchemy import func

    # Strategies the user owns
    strat_filter = [Strategy.user_id == current_user.id]
    if strategy_id:
        strat_filter.append(Strategy.id == strategy_id)
    user_strategy_ids = [s.id for s in db.query(Strategy.id).filter(*strat_filter).all()]
    if not user_strategy_ids:
        return []

    # Aggregate lead totals per source (portable across dialects)
    totals = (
        db.query(Lead.source, func.count(Lead.id), func.avg(Lead.intent_score))
        .filter(Lead.user_id == current_user.id)
        .group_by(Lead.source)
        .all()
    )
    by_source: dict[str, dict] = {}
    for src, total, avg_score in totals:
        by_source[src] = {
            "source": src,
            "total_leads": total,
            "with_email": 0,
            "verified_email": 0,
            "avg_score": float(avg_score) if avg_score else 0.0,
        }
    # Email counts
    email_q = (
        db.query(Lead.source, func.count(Lead.id))
        .filter(Lead.user_id == current_user.id, Lead.person_email.isnot(None))
        .group_by(Lead.source).all()
    )
    for src, cnt in email_q:
        if src in by_source:
            by_source[src]["with_email"] = cnt
    verified_q = (
        db.query(Lead.source, func.count(Lead.id))
        .filter(Lead.user_id == current_user.id, Lead.email_verified.is_(True))
        .group_by(Lead.source).all()
    )
    for src, cnt in verified_q:
        if src in by_source:
            by_source[src]["verified_email"] = cnt

    # Latest run per source
    runs = (
        db.query(SyncRun)
        .filter(SyncRun.strategy_id.in_(user_strategy_ids))
        .order_by(SyncRun.started_at.desc())
        .all()
    )
    by_src_run: dict[str, SyncRun] = {}
    for r in runs:
        if r.source not in by_src_run:
            by_src_run[r.source] = r

    # Merge run info into stats
    all_sources = set(by_source.keys()) | set(by_src_run.keys())
    out = []
    for src in sorted(all_sources):
        stats = by_source.get(src, {"source": src, "total_leads": 0, "with_email": 0, "avg_score": 0.0})
        r = by_src_run.get(src)
        stats["last_run_at"] = r.started_at.isoformat() if r else None
        stats["last_status"] = r.status if r else "never_run"
        stats["last_error"] = r.error if r else None
        stats["last_leads_found"] = r.leads_found if r else 0
        out.append(stats)
    return out


@router.get("/sync-runs", response_model=list[SyncRunOut])
def list_sync_runs(
    strategy_id: int | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        db.query(SyncRun)
        .join(Strategy)
        .filter(Strategy.user_id == current_user.id)
    )
    if strategy_id:
        q = q.filter(SyncRun.strategy_id == strategy_id)
    return q.order_by(desc(SyncRun.started_at)).limit(limit).all()


@router.get("/discovered-sources", response_model=list[DiscoveredSourceOut])
def list_discovered_sources(
    strategy_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        db.query(DiscoveredSource)
        .join(Strategy)
        .filter(Strategy.user_id == current_user.id)
    )
    if strategy_id:
        q = q.filter(DiscoveredSource.strategy_id == strategy_id)
    return q.order_by(desc(DiscoveredSource.success_rate)).all()


@router.patch("/discovered-sources/{source_id}/toggle", response_model=DiscoveredSourceOut)
def toggle_source(
    source_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ds = db.get(DiscoveredSource, source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Source not found.")
    strategy = db.get(Strategy, ds.strategy_id)
    if not strategy or strategy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden.")
    ds.status = "active" if ds.status != "active" else "pending"
    db.commit()
    db.refresh(ds)
    return ds


@router.delete("/discovered-sources/{source_id}", status_code=204)
def delete_source(
    source_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ds = db.get(DiscoveredSource, source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Source not found.")
    strategy = db.get(Strategy, ds.strategy_id)
    if not strategy or strategy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden.")
    db.delete(ds)
    db.commit()


@router.post("/discovered-sources/{source_id}/retest", response_model=DiscoveredSourceOut)
def retest_source(
    source_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ds = db.get(DiscoveredSource, source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Source not found.")
    strategy = db.get(Strategy, ds.strategy_id)
    if not strategy or strategy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden.")

    def _retest(source_id: int):
        from backend.database import SessionLocal
        from backend.pipeline.cron import _run_discovered_source
        _db = SessionLocal()
        try:
            _ds = _db.get(DiscoveredSource, source_id)
            _strategy = _db.get(Strategy, _ds.strategy_id)
            if _ds and _strategy:
                _run_discovered_source(_ds, _strategy, _db)
        finally:
            _db.close()

    background_tasks.add_task(_retest, source_id)
    return ds


@router.post("/discover", status_code=202)
def trigger_discovery(
    strategy_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    strategy = db.get(Strategy, strategy_id)
    if not strategy or strategy.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    def _discover(sid: int):
        from backend.database import SessionLocal
        from backend.pipeline.discoverer import discover_sources_for_strategy
        _db = SessionLocal()
        try:
            _s = _db.get(Strategy, sid)
            if _s:
                discover_sources_for_strategy(_s, _db)
        finally:
            _db.close()

    background_tasks.add_task(_discover, strategy_id)
    return {"detail": "Discovery triggered in background."}


@router.post("/add-custom-url", response_model=DiscoveredSourceOut)
def add_custom_url(
    body: AddCustomURLRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    strategy = db.get(Strategy, body.strategy_id)
    if not strategy or strategy.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    import httpx
    from backend.pipeline.universal_extractor import extract_leads_from_url
    from backend.models import DiscoveredSource

    try:
        r = httpx.get(body.url, timeout=10, headers={"User-Agent": "Mozilla/5.0 LeadHunt/1.0"})
        if r.status_code != 200 or len(r.text) < 300:
            raise HTTPException(status_code=422, detail="URL returned empty or error response.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch URL: {e}")

    leads = extract_leads_from_url(body.url, strategy)
    if not leads:
        raise HTTPException(status_code=422, detail="No leads found on that page.")

    ds = DiscoveredSource(
        strategy_id=strategy.id,
        name=body.url[:80],
        type="listing",
        url_pattern=body.url,
        access_method="scrape_html",
        status="active",
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds
