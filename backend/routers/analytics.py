from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import Lead, User
from backend.schemas import AnalyticsOut

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsOut)
def get_analytics(
    strategy_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Lead).filter(Lead.user_id == current_user.id)
    if strategy_id:
        q = q.filter(Lead.strategy_id == strategy_id)
    leads = q.all()

    total = len(leads)
    verified = sum(1 for l in leads if l.email_verified)
    contacted = sum(1 for l in leads if l.status == "contacted")
    avg_score = (sum(l.intent_score for l in leads) / total) if total else 0.0

    # leads by day (last 30 days). SQLite returns naive datetimes; normalize both sides.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).replace(tzinfo=None)
    by_day: dict[str, int] = defaultdict(int)
    for lead in leads:
        created = lead.created_at.replace(tzinfo=None) if lead.created_at.tzinfo else lead.created_at
        if created >= cutoff:
            day = created.date().isoformat()
            by_day[day] += 1

    # leads by source
    by_source: dict[str, int] = defaultdict(int)
    for lead in leads:
        by_source[lead.source] += 1

    # leads by score bucket
    buckets = {"0.0-0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.9": 0, "0.9-1.0": 0}
    for lead in leads:
        s = lead.intent_score
        if s < 0.3:
            buckets["0.0-0.3"] += 1
        elif s < 0.5:
            buckets["0.3-0.5"] += 1
        elif s < 0.7:
            buckets["0.5-0.7"] += 1
        elif s < 0.9:
            buckets["0.7-0.9"] += 1
        else:
            buckets["0.9-1.0"] += 1

    return AnalyticsOut(
        total_leads=total,
        verified_email_pct=round(verified / total * 100, 1) if total else 0.0,
        contacted_pct=round(contacted / total * 100, 1) if total else 0.0,
        avg_intent_score=round(avg_score, 3),
        leads_by_day=[{"date": k, "count": v} for k, v in sorted(by_day.items())],
        leads_by_source=[{"source": k, "count": v} for k, v in sorted(by_source.items(), key=lambda x: -x[1])],
        leads_by_score_bucket=[{"bucket": k, "count": v} for k, v in buckets.items()],
    )
