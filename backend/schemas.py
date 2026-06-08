from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp_code: str
    password: str | None = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str | None = None

class OTPLoginRequest(BaseModel):
    email: EmailStr

class PasswordResetRequest(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str

    def validate_password(self) -> bool:
        return len(self.new_password) >= 8

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class UserOut(BaseModel):
    id: int
    email: str
    is_verified: bool
    full_name: str | None = None
    role: str | None = None
    location: str | None = None
    bio: str | None = None
    company_name: str | None = None
    company_website: str | None = None
    employee_count: str | None = None
    credits: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    location: str | None = None
    bio: str | None = None
    company_name: str | None = None
    company_website: str | None = None
    employee_count: str | None = None


# ── Strategy ──────────────────────────────────────────────────────────────────

class StrategyCreate(BaseModel):
    title: str
    main_problem: str
    ideal_customer: str
    keywords: list[str] = []
    buyer_phrases: list[str] = []
    target_locations: list[str] = []
    target_company_size: list[str] = []
    competitors: list[str] = []
    target_websites: list[str] = []
    event_keywords: list[str] = []
    webinars_enabled: bool = True
    events_enabled: bool = True
    intent_threshold: float = 0.5

    @field_validator("intent_threshold")
    @classmethod
    def clamp_threshold(cls, v: float) -> float:
        return max(0.3, min(0.9, v))

    @field_validator("target_websites")
    @classmethod
    def clean_websites(cls, v: list[str]) -> list[str]:
        """Normalise to bare domains (strip scheme / path / www / trailing slash)."""
        out: list[str] = []
        for raw in v or []:
            d = (raw or "").strip().lower()
            if not d:
                continue
            d = d.split("://", 1)[-1].split("/", 1)[0]
            if d.startswith("www."):
                d = d[4:]
            if d and d not in out:
                out.append(d)
        return out

class StrategyUpdate(StrategyCreate):
    pass

class StrategyOut(BaseModel):
    id: int
    user_id: int
    title: str
    main_problem: str
    ideal_customer: str
    keywords: list[str]
    buyer_phrases: list[str]
    target_locations: list[str]
    target_company_size: list[str]
    target_roles: list[str]
    target_industries: list[str]
    competitors: list[str] | None = None
    target_websites: list[str] = []
    event_keywords: list[str] = []
    webinars_enabled: bool = True
    events_enabled: bool = True
    learning_profile: dict[str, Any] = {}
    raw_icp_params: dict[str, Any]
    intent_threshold: float
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Lead ──────────────────────────────────────────────────────────────────────

class LeadOut(BaseModel):
    id: int
    user_id: int
    strategy_id: int
    source: str
    external_id: str
    person_name: str
    person_title: str | None
    person_location: str | None
    person_linkedin_url: str | None
    person_github_url: str | None
    person_twitter_url: str | None
    person_email: str | None
    email_verified: bool
    email_source: str | None
    email_confidence: float = 0.0
    person_phone: str | None = None
    phone_source: str | None = None
    is_unlocked: bool = False
    source_url: str | None
    source_profile_url: str | None
    source_snippet: str | None
    company_name: str | None
    company_domain: str | None
    company_size: str | None
    company_industry: str | None
    intent_score: float
    intent_signals: list[str]
    raw_data: dict[str, Any]
    outreach_template: str | None
    status: str
    feedback: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class LeadFilter(BaseModel):
    sources: list[str] | None = None
    has_email: bool | None = None
    email_verified: bool | None = None
    min_score: float | None = None
    statuses: list[str] | None = None
    search: str | None = None

class LeadStatusUpdate(BaseModel):
    status: str
    feedback: int | None = None

class OutreachResponse(BaseModel):
    outreach_template: str


# ── DiscoveredSource ──────────────────────────────────────────────────────────

class DiscoveredSourceOut(BaseModel):
    id: int
    strategy_id: int
    name: str
    type: str
    url_pattern: str
    access_method: str
    status: str
    leads_found_total: int
    runs: int
    success_rate: float
    last_run_at: datetime | None
    last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

class AddCustomURLRequest(BaseModel):
    url: str
    strategy_id: int


# ── SyncRun ───────────────────────────────────────────────────────────────────

class SyncRunOut(BaseModel):
    id: int
    strategy_id: int
    source: str
    status: str
    leads_found: int
    started_at: datetime
    finished_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}


# ── Analytics ─────────────────────────────────────────────────────────────────

class AnalyticsOut(BaseModel):
    total_leads: int
    verified_email_pct: float
    contacted_pct: float
    avg_intent_score: float
    leads_by_day: list[dict[str, Any]]
    leads_by_source: list[dict[str, Any]]
    leads_by_score_bucket: list[dict[str, Any]]


# ── Credits / billing ─────────────────────────────────────────────────────────

class CreditBalanceOut(BaseModel):
    credits: int
    billing_enabled: bool
    cost_unlock: int
    cost_export: int


class CreditTransactionOut(BaseModel):
    id: int
    amount: int
    action: str
    lead_id: int | None
    balance_after: int
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnlockResponse(BaseModel):
    lead: LeadOut
    charged: int
    credits_remaining: int
    billing_enabled: bool
