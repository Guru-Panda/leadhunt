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
    GITHUB_TOKEN: str = ""
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    PRODUCTHUNT_TOKEN: str = ""
    GOOGLE_CSE_ID: str = ""
    GOOGLE_API_KEY: str = ""
    HUNTER_API_KEY: str = ""
    STACKOVERFLOW_KEY: str = ""  # optional — raises SO API from 300 to 10,000 req/day
    COMPANIES_HOUSE_KEY: str = ""  # free signup at developer.company-information.service.gov.uk
    APOLLO_API_KEY: str = ""  # apollo.io — 275M contacts, verified emails. Free: 50 exports/mo

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

    # App
    FRONTEND_URL: str = "http://localhost:5173"
    SYNC_INTERVAL_HOURS: int = 1
    LEAD_RETENTION_DAYS: int = 90
    DEV_MODE: bool = True  # when true, signup response includes the OTP code

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Warn (don't fail) about features that won't work without keys
def _check_optional_features() -> None:
    missing: list[str] = []
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
