from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import Strategy, User
from backend.pipeline.icp_translator import translate_icp
from backend.schemas import StrategyCreate, StrategyOut, StrategyUpdate

log = logging.getLogger(__name__)
router = APIRouter(prefix="/strategies", tags=["strategies"])


def _run_discovery(strategy_id: int) -> None:
    """Background job — discovery is slow, do it after the response."""
    from backend.database import SessionLocal
    from backend.pipeline.discoverer import discover_sources_for_strategy
    db = SessionLocal()
    try:
        strategy = db.get(Strategy, strategy_id)
        if strategy:
            discover_sources_for_strategy(strategy, db)
    except Exception as e:
        log.error(f"Discovery failed for strategy {strategy_id}: {e}")
    finally:
        db.close()


@router.get("", response_model=list[StrategyOut])
def list_strategies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(Strategy).filter(Strategy.user_id == current_user.id).all()


@router.post("", response_model=StrategyOut, status_code=201)
def create_strategy(
    body: StrategyCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    strategy = Strategy(user_id=current_user.id, **body.model_dump())
    db.add(strategy)
    db.commit()
    db.refresh(strategy)

    # Run ICP translator synchronously — user sees parsed params immediately
    try:
        translate_icp(strategy, db)
        db.refresh(strategy)
    except Exception as e:
        log.warning(f"ICP translation failed for new strategy {strategy.id}: {e}")

    # Discovery is slow; defer to background
    background_tasks.add_task(_run_discovery, strategy.id)
    return strategy


@router.get("/{strategy_id}", response_model=StrategyOut)
def get_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return s


@router.put("/{strategy_id}", response_model=StrategyOut)
def update_strategy(
    strategy_id: int,
    body: StrategyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)

    # Re-translate ICP on every update — inputs likely changed
    try:
        translate_icp(s, db)
        db.refresh(s)
    except Exception as e:
        log.warning(f"ICP translation failed for updated strategy {s.id}: {e}")

    return s


@router.post("/{strategy_id}/sync-now", status_code=202)
def sync_now(
    strategy_id: int,
    background_tasks: BackgroundTasks,
    sources: list[str] | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run base sources for this strategy in the background. Returns immediately."""
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    def _run(sid: int, src: list[str] | None) -> None:
        from backend.pipeline.cron import sync_strategy
        try:
            result = sync_strategy(sid, source_names=src, per_source_limit=20)
            log.info(f"sync_now completed: {result}")
        except Exception as e:
            log.error(f"sync_now failed for strategy {sid}: {e}")

    background_tasks.add_task(_run, strategy_id, sources)
    return {"detail": "Sync started in background. Refresh /leads in 30-60s to see results."}


@router.post("/{strategy_id}/analyze", response_model=StrategyOut)
def analyze_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicit "Analyze with AI" — re-runs ICP translator on the current strategy."""
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    try:
        translate_icp(s, db)
        db.refresh(s)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ICP translation failed: {e}")
    return s


@router.delete("/{strategy_id}", status_code=204)
def delete_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    db.delete(s)
    db.commit()


@router.post("/{strategy_id}/toggle-active", response_model=StrategyOut)
def toggle_active(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    s.is_active = not s.is_active
    db.commit()
    db.refresh(s)
    return s
