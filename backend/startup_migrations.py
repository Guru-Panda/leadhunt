"""Lightweight in-place schema migrations applied on every backend boot.

SQLAlchemy's `create_all()` only creates tables that don't exist — it never
alters columns. Whenever we add a column after the first deploy, list it here
so existing prod databases pick it up on the next restart.

Each migration is idempotent: it checks if the column exists first, then ALTERs.
Safe to run on every boot. Works against both Postgres and SQLite.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


# (table, column, sqlite_ddl, postgres_ddl) — sqlite is generally fine with simple TEXT for all string types
_MIGRATIONS: list[tuple[str, str, str, str]] = [
    ("leadhunt_users", "full_name",       "TEXT",        "VARCHAR(120)"),
    ("leadhunt_users", "role",            "TEXT",        "VARCHAR(120)"),
    ("leadhunt_users", "location",        "TEXT",        "VARCHAR(120)"),
    ("leadhunt_users", "bio",             "TEXT",        "TEXT"),
    ("leadhunt_users", "company_website", "TEXT",        "VARCHAR(255)"),
    # Lead.email_source (added in Day 7) — also retroactively ensured
    ("leadhunt_leads", "email_source",    "TEXT",        "VARCHAR(50)"),
    # Lead provenance (added in Day 4)
    ("leadhunt_leads", "source_url",         "TEXT",     "VARCHAR(500)"),
    ("leadhunt_leads", "source_profile_url", "TEXT",     "VARCHAR(500)"),
    ("leadhunt_leads", "source_snippet",     "TEXT",     "TEXT"),
    # Contact-quality columns (graded confidence + phone)
    ("leadhunt_leads", "email_confidence",   "REAL",     "DOUBLE PRECISION DEFAULT 0.0"),
    ("leadhunt_leads", "person_phone",       "TEXT",     "VARCHAR(50)"),
    ("leadhunt_leads", "phone_source",       "TEXT",     "VARCHAR(50)"),
    # Columns the models define but were missing here — without these an existing
    # prod Postgres (created before they were added) raises UndefinedColumn on
    # any query selecting them (LeadOut, CSV export, source_stats).
    ("leadhunt_users", "company_name",       "TEXT",     "VARCHAR(255)"),
    ("leadhunt_users", "employee_count",     "TEXT",     "VARCHAR(50)"),
    ("leadhunt_leads", "company_domain",     "TEXT",     "VARCHAR(255)"),
    ("leadhunt_leads", "company_size",       "TEXT",     "VARCHAR(50)"),
    ("leadhunt_leads", "company_industry",   "TEXT",     "VARCHAR(255)"),
    ("leadhunt_leads", "email_verified",     "INTEGER",  "BOOLEAN DEFAULT FALSE"),
    # Credits / pay-per-use (Phase 1). Keep the DEFAULT in the SQLite DDL too, so
    # existing rows are backfilled instead of left NULL.
    ("leadhunt_users", "credits",            "INTEGER DEFAULT 100",  "INTEGER DEFAULT 100"),
    ("leadhunt_leads", "is_unlocked",        "INTEGER DEFAULT 0",    "BOOLEAN DEFAULT FALSE"),
    # Competitor switch-intent (Phase 2)
    ("leadhunt_strategies", "competitors",   "TEXT",                 "JSONB"),
]


def run_inline_migrations(engine: Engine) -> None:
    dialect = engine.dialect.name
    inspector = inspect(engine)
    added = 0
    with engine.begin() as conn:
        for table, column, sqlite_ddl, pg_ddl in _MIGRATIONS:
            # Skip if table doesn't exist yet (create_all will handle it)
            if table not in inspector.get_table_names():
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            if column in existing_cols:
                continue
            ddl_type = sqlite_ddl if dialect == "sqlite" else pg_ddl
            stmt = text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
            try:
                conn.execute(stmt)
                added += 1
                log.info(f"Migration: added {table}.{column} ({ddl_type})")
            except Exception as e:
                log.warning(f"Migration skipped for {table}.{column}: {e}")
    if added:
        log.info(f"Inline migrations: applied {added} schema change(s)")
