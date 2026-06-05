from __future__ import annotations

import logging
import os
import secrets
from pydantic_settings import BaseSettings

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Auth — dev defaults so the app boots with zero config
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database — SQLite default for local dev, Postgres on Railway
    DATABASE_URL: str = "sqlite:///./leadhunt.db"
    ADMIN_KEY: str = "dev-admin-key-change-me"

    # LLM / Sources — all optional (modules degrade gracefully)
    GROQ_API_KEY: str = ""
    # Extra free LLM providers for the failover pool (all OpenAI-compatible).
    # Add any you have free keys for; the pool rotates across whatever is set so a
    # single daily quota can't take the app down.
    GEMINI_API_KEY: str = ""       # Google AI Studio — ~1,500 req/day free
    CEREBRAS_API_KEY: str = ""     # cerebras.ai — free, very fast
    OPENROUTER_API_KEY: str = ""   # openrouter.ai — many :free models
    TOGETHER_API_KEY: str = ""     # together.ai — free tier
    GITHUB_TOKEN: str = ""
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    PRODUCTHUNT_TOKEN: str = ""
    GOOGLE_CSE_ID: str = ""
    GOOGLE_API_KEY: str = ""
    # Web-search pool (failover). All optional — keyless DuckDuckGo/Mojeek work now.
    TAVILY_API_KEY: str = ""       # tavily.com — agent-native, ~1,000 searches/mo free
    BRAVE_SEARCH_API_KEY: str = ""  # brave.com/search/api — ~2,000 queries/mo free
    # Opportunity engine (events). Optional — web search covers events keylessly.
    TICKETMASTER_API_KEY: str = ""  # developer.ticketmaster.com — ~5,000 calls/day free
    HUNTER_API_KEY: str = ""
    STACKOVERFLOW_KEY: str = ""  # optional — raises SO API from 300 to 10,000 req/day
    COMPANIES_HOUSE_KEY: str = ""  # free signup at developer.company-information.service.gov.uk
    APOLLO_API_KEY: str = ""  # apollo.io — 275M contacts, verified emails. Free: 50 exports/mo
    # Apollo People Match (enrich) — unlocks the REAL email/phone behind a search
    # result's `email_not_unlocked@…` placeholder. Each call consumes an Apollo
    # credit, so it's budget-capped per process. Set ENABLED=false to never spend.
    APOLLO_UNLOCK_ENABLED: bool = True
    APOLLO_UNLOCK_BUDGET: int = 25  # max match/unlock calls per process run

    # Email delivery — four tiers, tried in order:
    # 1. Brevo (HTTPS, 300/day free, sender-email verification only — RECOMMENDED if no domain)
    # 2. Resend (HTTPS, 100/day free, needs domain verification for arbitrary recipients)
    # 3. Gmail SMTP (works locally; Railway blocks ports 587/465 on Hobby tier)
    # 4. Dev mode (no creds → OTP surfaced in API response + console)
    BREVO_API_KEY: str = ""
    RESEND_API_KEY: str = ""
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "LeadHunt <onboarding@resend.dev>"

    # Credits / billing — pay-per-use model.
    # BILLING_ENABLED=False (default) = TEST MODE: unlocks are free but the ledger
    # still records what each action WOULD cost, so the whole flow is testable for
    # free. Flip to True to actually charge credits.
    BILLING_ENABLED: bool = False
    FREE_STARTER_CREDITS: int = 100   # granted to each new account
    CREDIT_COST_UNLOCK: int = 2       # credits to unlock a verified contact
    CREDIT_COST_EXPORT: int = 1       # credits per CSV export

    # App
    FRONTEND_URL: str = "http://localhost:5173"
    SYNC_INTERVAL_HOURS: int = 1
    # Set to false on EXTRA workers in a multi-worker deploy so the hourly sync +
    # retention cleanup run on exactly one process (otherwise every gunicorn worker
    # starts its own scheduler → duplicate syncs and duplicate deletes).
    RUN_SCHEDULER: bool = True
    LEAD_RETENTION_DAYS: int = 90
    DEV_MODE: bool = False  # SECURITY: must stay False in prod — when True the OTP is returned in API responses (account-takeover risk). Set DEV_MODE=true locally only.

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Warn (don't fail) about features that won't work without keys
def _check_optional_features() -> None:
    missing: list[str] = []
    if "SECRET_KEY" not in os.environ:
        log.warning(
            "[LeadHunt] SECRET_KEY not set in env — using an ephemeral random key. "
            "All sessions reset on restart and tokens fail across multiple workers. "
            "Set SECRET_KEY in production."
        )
    if settings.DEV_MODE:
        log.warning(
            "[LeadHunt] DEV_MODE is ON — OTP codes are returned in API responses. "
            "NEVER enable this in production."
        )
    if not settings.GROQ_API_KEY:
        missing.append("GROQ_API_KEY (ICP translator, scorer, discoverer disabled)")
    if not (settings.BREVO_API_KEY or settings.RESEND_API_KEY or (settings.SMTP_USER and settings.SMTP_PASSWORD)):
        missing.append("BREVO_API_KEY or RESEND_API_KEY or SMTP_USER/SMTP_PASSWORD (OTP emails logged to console)")
    if not settings.GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN (GitHub source disabled)")
    if not (settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID):
        missing.append("GOOGLE_API_KEY + GOOGLE_CSE_ID (Google CSE source disabled — LinkedIn profiles via Google won't work)")
    if missing:
        log.warning(
            "[LeadHunt] Booted in DEV mode. Missing optional env vars:\n  - "
            + "\n  - ".join(missing)
        )


_check_optional_features()
