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
    COMPANIES_HOUSE_KEY: str = ""  # free signup at developer.company-information.service.gov.uk

    # Email delivery — three tiers, tried in order:
    # 1. Resend (HTTPS API, no port-blocking issues — RECOMMENDED on Railway)
    # 2. Gmail SMTP (works locally; Railway blocks ports 587/465 on Hobby tier)
    # 3. Dev mode (no creds → OTP surfaced in API response + console)
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
    if not settings.RESEND_API_KEY and (not settings.SMTP_USER or not settings.SMTP_PASSWORD):
        missing.append("RESEND_API_KEY or SMTP_USER/SMTP_PASSWORD (OTP emails will be logged to console instead)")
    if not settings.GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN (GitHub source disabled)")
    if missing:
        log.warning(
            "[LeadHunt] Booted in DEV mode. Missing optional env vars:\n  - "
            + "\n  - ".join(missing)
        )


_check_optional_features()
