from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import Lead, User
from backend.schemas import AnalyticsOut

router = APIRouter(prefix="/analytics", tags=["analytics"])

_BUCKETS = ["0.0-0.3", "0.3-0.5", "0.5-0.7", "0.7-0.9", "0.9-1.0"]


@router.get("", response_model=AnalyticsOut)
def get_analytics(
    strategy_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All metrics computed in SQL (counts / avg / group-by) — no longer loads
    every lead row into Python, so it scales to large accounts."""
    filters = [Lead.user_id == current_user.id]
    if strategy_id:
        filters.append(Lead.strategy_id == strategy_id)

    total = db.query(func.count(Lead.id)).filter(*filters).scalar() or 0
    if total == 0:
        return AnalyticsOut(
            total_leads=0, verified_email_pct=0.0, contacted_pct=0.0, avg_intent_score=0.0,
            leads_by_day=[], leads_by_source=[],
            leads_by_score_bucket=[{"bucket": b, "count": 0} for b in _BUCKETS],
        )

    verified = db.query(func.count(Lead.id)).filter(*filters, Lead.email_verified.is_(True)).scalar() or 0
    contacted = db.query(func.count(Lead.id)).filter(*filters, Lead.status == "contacted").scalar() or 0
    avg_score = db.query(func.avg(Lead.intent_score)).filter(*filters).scalar() or 0.0

    # leads by day (last 30 days) — func.date() works on both SQLite and Postgres
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).replace(tzinfo=None)
    day_col = func.date(Lead.created_at)
    by_day = (
        db.query(day_col.label("d"), func.count(Lead.id))
        .filter(*filters, Lead.created_at >= cutoff)
        .group_by(day_col).order_by(day_col).all()
    )

    by_source = (
        db.query(Lead.source, func.count(Lead.id))
        .filter(*filters).group_by(Lead.source)
        .order_by(func.count(Lead.id).desc()).all()
    )

    bucket_col = case(
        (Lead.intent_score < 0.3, "0.0-0.3"),
        (Lead.intent_score < 0.5, "0.3-0.5"),
        (Lead.intent_score < 0.7, "0.5-0.7"),
        (Lead.intent_score < 0.9, "0.7-0.9"),
        else_="0.9-1.0",
    )
    bucket_counts = dict(
        db.query(bucket_col, func.count(Lead.id)).filter(*filters).group_by(bucket_col).all()
    )

    return AnalyticsOut(
        total_leads=total,
        verified_email_pct=round(verified / total * 100, 1),
        contacted_pct=round(contacted / total * 100, 1),
        avg_intent_score=round(float(avg_score), 3),
        leads_by_day=[{"date": str(d), "count": c} for d, c in by_day],
        leads_by_source=[{"source": s, "count": c} for s, c in by_source],
        leads_by_score_bucket=[{"bucket": b, "count": bucket_counts.get(b, 0)} for b in _BUCKETS],
    )
