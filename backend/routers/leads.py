from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import Lead, Strategy, User
from backend.schemas import LeadOut, LeadStatusUpdate, OutreachResponse

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
        "person_email", "email_verified", "email_source",
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
            "email_source": lead.email_source or "",
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
        "person_github_url": lead.person_github_url,
        "company_domain": lead.company_domain,
        "intent_score": lead.intent_score,
        "source": lead.source,
        "raw_data": lead.raw_data or {},
    }
    enriched = enrich(draft)
    if enriched.get("person_email"):
        lead.person_email = enriched["person_email"]
        lead.email_verified = enriched.get("email_verified", False)
        lead.email_source = enriched.get("email_source")
        db.commit()
        db.refresh(lead)
    return lead


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
