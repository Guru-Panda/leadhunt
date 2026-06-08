from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from backend import credits as credits_svc
from backend.auth import get_current_user
from backend.config import settings
from backend.database import get_db
from backend.models import Lead, Strategy, User
from backend.schemas import LeadOut, LeadStatusUpdate, OutreachResponse, UnlockResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["leads"])


def _build_query(db: Session, user_id: int, **filters: Any):
    q = db.query(Lead).filter(Lead.user_id == user_id)

    if filters.get("sources"):
        q = q.filter(Lead.source.in_(filters["sources"]))
    if filters.get("has_email") is not None:
        if filters["has_email"]:
            q = q.filter(Lead.person_email.isnot(None))
        else:
            q = q.filter(Lead.person_email.is_(None))
    if filters.get("email_verified") is not None:
        q = q.filter(Lead.email_verified == filters["email_verified"])
    if filters.get("min_score") is not None:
        q = q.filter(Lead.intent_score >= filters["min_score"])
    if filters.get("statuses"):
        q = q.filter(Lead.status.in_(filters["statuses"]))
    if filters.get("search"):
        term = f"%{filters['search']}%"
        q = q.filter(
            or_(
                Lead.person_name.ilike(term),
                Lead.company_name.ilike(term),
                Lead.person_email.ilike(term),
            )
        )
    return q


@router.get("", response_model=list[LeadOut])
def list_leads(
    sources: list[str] | None = Query(default=None),
    has_email: bool | None = Query(default=None),
    email_verified: bool | None = Query(default=None),
    min_score: float | None = Query(default=None),
    statuses: list[str] | None = Query(default=None),
    search: str | None = Query(default=None),
    strategy_id: int | None = Query(default=None),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = _build_query(
        db, current_user.id,
        sources=sources, has_email=has_email, email_verified=email_verified,
        min_score=min_score, statuses=statuses, search=search,
    )
    if strategy_id:
        q = q.filter(Lead.strategy_id == strategy_id)
    # Emails-first: verified emails > any email > no email; then by score desc
    return q.order_by(
        Lead.email_verified.desc(),
        Lead.person_email.is_(None).asc(),
        Lead.intent_score.desc(),
        Lead.created_at.desc(),
    ).offset(skip).limit(limit).all()


@router.get("/export-csv")
def export_csv(
    sources: list[str] | None = Query(default=None),
    has_email: bool | None = Query(default=None),
    email_verified: bool | None = Query(default=None),
    min_score: float | None = Query(default=None),
    statuses: list[str] | None = Query(default=None),
    search: str | None = Query(default=None),
    strategy_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = _build_query(
        db, current_user.id,
        sources=sources, has_email=has_email, email_verified=email_verified,
        min_score=min_score, statuses=statuses, search=search,
    )
    if strategy_id:
        q = q.filter(Lead.strategy_id == strategy_id)
    leads = q.order_by(Lead.intent_score.desc()).all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "person_name", "person_title",
        "person_email", "email_verified", "email_confidence", "email_source",
        "person_phone", "phone_source",
        "company_name", "company_domain", "company_size", "company_industry",
        "person_location", "person_linkedin_url", "person_github_url", "person_twitter_url",
        "source", "source_url", "source_profile_url", "source_snippet",
        "intent_score", "intent_signals", "status", "created_at",
    ])
    writer.writeheader()
    for lead in leads:
        writer.writerow({
            "id": lead.id,
            "person_name": lead.person_name,
            "person_title": lead.person_title or "",
            "person_email": lead.person_email or "",
            "email_verified": lead.email_verified,
            "email_confidence": lead.email_confidence,
            "email_source": lead.email_source or "",
            "person_phone": lead.person_phone or "",
            "phone_source": lead.phone_source or "",
            "company_name": lead.company_name or "",
            "company_domain": lead.company_domain or "",
            "company_size": lead.company_size or "",
            "company_industry": lead.company_industry or "",
            "person_location": lead.person_location or "",
            "person_linkedin_url": lead.person_linkedin_url or "",
            "person_github_url": lead.person_github_url or "",
            "person_twitter_url": lead.person_twitter_url or "",
            "source": lead.source,
            "source_url": lead.source_url or "",
            "source_profile_url": lead.source_profile_url or "",
            "source_snippet": (lead.source_snippet or "").replace("\n", " ").replace("\r", " ")[:500],
            "intent_score": lead.intent_score,
            "intent_signals": ", ".join(lead.intent_signals or []),
            "status": lead.status,
            "created_at": lead.created_at.isoformat(),
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


# ── Literal-path routes FIRST (FastAPI matches in declaration order — without
# this, `/leads/{lead_id}` would catch `/leads/unwanted-count` first)

# A lead is "approved" if the user positively engaged with it: thumbs-up
# (feedback==1) OR a forward-moving status (qualified / contacted / liked / won).
# Shared with the learning loop so the definition stays in one place.
from backend.pipeline.learning import _APPROVE_STATUSES


def _purge_query(db: Session, user_id: int, strategy_id: int, scope: str):
    """Leads eligible for deletion under the given scope.

    - "unwanted"   → only leads the user actively rejected (feedback==-1 / rejected).
    - "unapproved" → EVERYTHING the user hasn't approved (incl. untouched 'new',
                     ignored, and rejected) — used by a fresh refresh that clears
                     the board except for leads you've kept.
    """
    base = db.query(Lead).filter(Lead.user_id == user_id, Lead.strategy_id == strategy_id)
    if scope == "unapproved":
        approve_statuses = list(_APPROVE_STATUSES)
        # coalesce() so NULL feedback / status don't fall into SQL three-valued
        # logic and silently survive the delete.
        return base.filter(
            and_(
                func.coalesce(Lead.feedback, 0) != 1,
                func.coalesce(Lead.status, "new").notin_(approve_statuses),
            )
        )
    return base.filter(or_(Lead.feedback == -1, Lead.status == "rejected"))


@router.get("/unwanted-count")
def unwanted_count(
    strategy_id: int = Query(...),
    scope: str = Query(default="unwanted"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Count leads that would be purged by /leads/purge with the same scope."""
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    count = _purge_query(db, current_user.id, strategy_id, scope).count()
    return {"count": count}


@router.delete("/purge", status_code=200)
def purge_unwanted(
    strategy_id: int = Query(...),
    scope: str = Query(default="unwanted"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete leads for this strategy under `scope`.

    - scope="unwanted" (default): removes disliked/rejected leads only; keeps
      liked, contacted, qualified, ignored, and untouched 'new'.
    - scope="unapproved": removes everything EXCEPT approved leads (feedback==1
      or status qualified/contacted/liked/won) — clears the board for a fresh hunt.
    """
    s = db.get(Strategy, strategy_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    q = _purge_query(db, current_user.id, strategy_id, scope)
    deleted = q.delete(synchronize_session=False)
    db.commit()
    log.info(f"Purged {deleted} leads from strategy {strategy_id} (scope={scope})")
    return {"deleted": deleted}


# ── Parametric routes AFTER literal ones

@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return lead


@router.patch("/{lead_id}/status", response_model=LeadOut)
def update_lead_status(
    lead_id: int,
    body: LeadStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")
    lead.status = body.status
    if body.feedback is not None:
        lead.feedback = body.feedback
    db.commit()
    db.refresh(lead)

    # Learn from this approve/reject so future hunts drift toward what the user keeps.
    try:
        strategy = db.get(Strategy, lead.strategy_id)
        if strategy:
            from backend.pipeline.learning import update_learning_profile
            update_learning_profile(strategy, db)
    except Exception as e:
        log.warning(f"learning profile update failed for strategy {lead.strategy_id}: {e}")

    return lead


@router.post("/{lead_id}/re-enrich", response_model=LeadOut)
def re_enrich_lead(
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run the email enrichment chain on an existing lead.

    Useful after adding a Hunter.io key, or when the company website / patterns
    might have improved since first crawl.
    """
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")

    from backend.enrichment.email import enrich_lead as enrich

    # Build a draft from the persisted lead, clear the email so the chain re-runs
    draft = {
        "person_name": lead.person_name,
        "person_email": None,  # reset so chain re-runs
        "person_phone": lead.person_phone,
        "person_linkedin_url": lead.person_linkedin_url,
        "person_github_url": lead.person_github_url,
        "company_name": lead.company_name,
        "company_domain": lead.company_domain,
        "intent_score": lead.intent_score,
        "source": lead.source,
        "raw_data": lead.raw_data or {},
    }
    enriched = enrich(draft, allow_premium=False)  # free tier — paid reveal is /unlock
    changed = False
    if enriched.get("person_email"):
        lead.person_email = enriched["person_email"]
        lead.email_verified = enriched.get("email_verified", False)
        lead.email_source = enriched.get("email_source")
        lead.email_confidence = enriched.get("email_confidence", 0.0)
        changed = True
    if enriched.get("person_phone") and not lead.person_phone:
        lead.person_phone = enriched["person_phone"]
        lead.phone_source = enriched.get("phone_source")
        changed = True
    if changed:
        db.commit()
        db.refresh(lead)
    return lead


@router.post("/{lead_id}/unlock", response_model=UnlockResponse)
def unlock_lead(
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Spend credits to reveal a verified contact (premium enrichment: Apollo
    match / Hunter find+verify). Free to browse; this is the paid action.

    Test mode (BILLING_ENABLED=False): runs the full flow, charges 0, records the
    would-be cost in the ledger. Only charges when a contact is actually found.
    """
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")

    cost = settings.CREDIT_COST_UNLOCK
    if lead.is_unlocked:
        return UnlockResponse(lead=lead, charged=0, credits_remaining=current_user.credits or 0,
                              billing_enabled=settings.BILLING_ENABLED)

    # Don't spend our paid API quota on a user who can't pay for the result.
    if settings.BILLING_ENABLED and (current_user.credits or 0) < cost:
        raise HTTPException(status_code=402,
                            detail=f"Need {cost} credits to unlock — you have {current_user.credits or 0}.")

    from backend.enrichment.email import enrich_lead

    draft = {
        "person_name": lead.person_name,
        "person_email": None,  # force premium re-find
        "person_phone": lead.person_phone,
        "person_linkedin_url": lead.person_linkedin_url,
        "person_github_url": lead.person_github_url,
        "company_name": lead.company_name,
        "company_domain": lead.company_domain,
        "source": lead.source,
        "raw_data": lead.raw_data or {},
    }
    enriched = enrich_lead(draft, allow_premium=True)
    improved = bool(enriched.get("person_email") or enriched.get("person_phone"))

    charged = 0
    if improved:
        charged = credits_svc.charge(db, current_user, cost, "unlock_contact", lead.id)
        if enriched.get("person_email"):
            lead.person_email = enriched["person_email"]
            lead.email_verified = enriched.get("email_verified", lead.email_verified)
            lead.email_source = enriched.get("email_source") or lead.email_source
            lead.email_confidence = enriched.get("email_confidence", lead.email_confidence)
        if enriched.get("person_phone") and not lead.person_phone:
            lead.person_phone = enriched["person_phone"]
            lead.phone_source = enriched.get("phone_source")
        lead.is_unlocked = True
        db.commit()
        db.refresh(lead)

    return UnlockResponse(
        lead=lead, charged=charged,
        credits_remaining=current_user.credits or 0,
        billing_enabled=settings.BILLING_ENABLED,
    )


@router.post("/{lead_id}/outreach", response_model=OutreachResponse)
def generate_outreach(
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead or lead.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found.")
    strategy = db.get(Strategy, lead.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    from backend.pipeline.outreach import generate_outreach as gen
    template = gen(lead, strategy)
    lead.outreach_template = template
    db.commit()
    return OutreachResponse(outreach_template=template)
