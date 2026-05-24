from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

# Cross-database JSON: JSONB on Postgres, plain JSON on SQLite
JSONType = JSONB().with_variant(JSON(), "sqlite")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "leadhunt_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employee_count: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    strategies: Mapped[list[Strategy]] = relationship("Strategy", back_populates="user")
    leads: Mapped[list[Lead]] = relationship("Lead", back_populates="user")


class EmailOTP(Base):
    __tablename__ = "leadhunt_email_otps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    otp_code: Mapped[str] = mapped_column(String(6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    @staticmethod
    def generate_code() -> str:
        return "".join(random.choices(string.digits, k=6))


class Strategy(Base):
    __tablename__ = "leadhunt_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("leadhunt_users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    main_problem: Mapped[str] = mapped_column(Text, nullable=False)
    ideal_customer: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    buyer_phrases: Mapped[list[str]] = mapped_column(JSONType, default=list)
    target_locations: Mapped[list[str]] = mapped_column(JSONType, default=list)
    target_company_size: Mapped[list[str]] = mapped_column(JSONType, default=list)
    target_roles: Mapped[list[str]] = mapped_column(JSONType, default=list)
    target_industries: Mapped[list[str]] = mapped_column(JSONType, default=list)
    raw_icp_params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    intent_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    user: Mapped[User] = relationship("User", back_populates="strategies")
    leads: Mapped[list[Lead]] = relationship("Lead", back_populates="strategy")
    discovered_sources: Mapped[list[DiscoveredSource]] = relationship("DiscoveredSource", back_populates="strategy")
    sync_runs: Mapped[list[SyncRun]] = relationship("SyncRun", back_populates="strategy")


class DiscoveredSource(Base):
    __tablename__ = "leadhunt_discovered_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("leadhunt_strategies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    url_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    access_method: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    leads_found_total: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    strategy: Mapped[Strategy] = relationship("Strategy", back_populates="discovered_sources")


class Lead(Base):
    __tablename__ = "leadhunt_leads"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_lead_user_source_ext"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("leadhunt_users.id"), nullable=False)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("leadhunt_strategies.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    person_name: Mapped[str] = mapped_column(String(255), nullable=False)
    person_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    person_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    person_linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    person_github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    person_twitter_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    person_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_source: Mapped[str | None] = mapped_column(String(50), nullable=True)         # how the email was found: source_text | company_site | github_commit | whois | pattern_guess | hunter
    # Provenance — clickable links back to where this lead came from
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)          # the post/comment/listing that matched
    source_profile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # the person's profile on that platform
    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)             # quoted text that triggered the match
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company_industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    intent_signals: Mapped[list[str]] = mapped_column(JSONType, default=list)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    outreach_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    user: Mapped[User] = relationship("User", back_populates="leads")
    strategy: Mapped[Strategy] = relationship("Strategy", back_populates="leads")


class SyncRun(Base):
    __tablename__ = "leadhunt_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("leadhunt_strategies.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running")
    leads_found: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    strategy: Mapped[Strategy] = relationship("Strategy", back_populates="sync_runs")
