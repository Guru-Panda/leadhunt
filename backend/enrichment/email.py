from __future__ import annotations

import logging
import re
import smtplib

import dns.resolver
import httpx

from backend.enrichment.extractors import extract_emails_from_text, scrape_company_emails

log = logging.getLogger(__name__)

MAX_SMTP_VERIFIES_PER_LEAD = 5
SMTP_TIMEOUT = 5


def is_noreply(email: str) -> bool:
    prefix = email.split("@")[0].lower()
    return any(k in prefix for k in ["noreply", "no-reply", "notifications", "support", "info", "hello", "team"])


def smtp_verify(email: str) -> bool:
    """Best-effort SMTP RCPT check. Returns True only on explicit 250.

    NOTE: On many networks (Windows dev, cloud VMs, Railway) port 25 outbound
    is blocked. In that case this ALWAYS returns False and the lead falls
    through to the unverified pattern path.
    """
    try:
        domain = email.split("@")[1]
        records = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(records, key=lambda r: r.preference)[0].exchange).rstrip(".")
        with smtplib.SMTP(timeout=SMTP_TIMEOUT) as smtp:
            smtp.connect(mx_host, 25)
            smtp.helo("leadhunt.io")
            smtp.mail("")
            code, _ = smtp.rcpt(email)
            return code == 250
    except smtplib.SMTPRecipientsRefused:
        return False
    except Exception as e:
        log.debug(f"SMTP verify failed for {email}: {e}")
        return False


def _split_name(name: str) -> tuple[str | None, str | None]:
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p.isalpha() or "-" in p]
    if len(parts) >= 2:
        return parts[0].lower(), parts[-1].lower()
    if len(parts) == 1:
        return parts[0].lower(), None
    return None, None


def guess_email_patterns(name: str, domain: str) -> list[str]:
    """Return common email patterns ranked by likelihood (most common first)."""
    first, last = _split_name(name)
    if not first:
        return []
    if not last:
        return [f"{first}@{domain}"]
    f = first[0]
    # Order by industry frequency (RocketReach/Hunter benchmarks)
    return [
        f"{first}.{last}@{domain}",   # most common in startups
        f"{first}@{domain}",
        f"{f}{last}@{domain}",
        f"{first}{last}@{domain}",
        f"{first}_{last}@{domain}",
        f"{last}.{first}@{domain}",
        f"{last}{f}@{domain}",
    ]


def best_guess_email(name: str, domain: str) -> str | None:
    """Return the SINGLE most likely email pattern. No SMTP verify — caller
    should set email_verified=False so the UI shows it as unverified."""
    patterns = guess_email_patterns(name, domain)
    return patterns[0] if patterns else None


def scrape_github_commit_emails(github_url: str) -> list[str]:
    try:
        username = github_url.rstrip("/").split("/")[-1]
        r = httpx.get(
            f"https://api.github.com/users/{username}/events/public",
            timeout=10,
            headers={"User-Agent": "LeadHunt/1.0"},
        )
        if r.status_code != 200:
            return []
        emails: set[str] = set()
        for event in r.json():
            payload = event.get("payload", {})
            for commit in payload.get("commits", []):
                author = commit.get("author", {})
                email = author.get("email", "")
                if email and "@" in email and "noreply" not in email and "users.noreply.github.com" not in email:
                    emails.add(email)
        return list(emails)
    except Exception as e:
        log.debug(f"GitHub commit email scrape failed for {github_url}: {e}")
        return []


def hunter_quota_available() -> bool:
    from backend.config import settings
    return bool(settings.HUNTER_API_KEY)


def hunter_find(name: str, domain: str) -> str | None:
    from backend.config import settings
    if not settings.HUNTER_API_KEY:
        return None
    parts = (name or "").split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first, "last_name": last, "api_key": settings.HUNTER_API_KEY},
            timeout=10,
        )
        return r.json().get("data", {}).get("email")
    except Exception as e:
        log.debug(f"Hunter API failed: {e}")
        return None


def _pick_personal_email(emails: list[str], name: str | None) -> str | None:
    """Prefer an email that looks like it belongs to this person (first/last name in local part)."""
    if not emails or not name:
        return emails[0] if emails else None
    first, last = _split_name(name)
    for e in emails:
        local = e.split("@")[0].lower()
        if first and first in local:
            return e
        if last and last in local:
            return e
    return emails[0]


def enrich_lead(lead_draft: dict) -> dict:
    """Layered email discovery. Each path is short-circuit, ordered by signal strength:
      1. Email already on the lead (from source extraction) — verify if possible
      2. Scrape company website mailto links (great for SMB founders)
      3. GitHub commit emails (gold for OSS folk)
      4. Best-guess pattern (mark unverified) — last resort for outreach
      5. Hunter.io (if quota available, for high-intent leads)
    """
    verifies_done = 0
    name = lead_draft.get("person_name", "")
    domain = lead_draft.get("company_domain")

    # ── 1. Already have an email from the source (HN/Reddit text extraction)
    if lead_draft.get("person_email"):
        email = lead_draft["person_email"]
        if not is_noreply(email):
            lead_draft.setdefault("email_verified", False)
            lead_draft.setdefault("email_source", "source_text")
            return lead_draft

    # ── 2. Scrape the company's site (only if we have a real, source-set domain)
    if domain and "." in domain:
        company_emails = scrape_company_emails(domain)
        if company_emails:
            picked = _pick_personal_email(company_emails, name)
            if picked:
                lead_draft["person_email"] = picked
                lead_draft["email_verified"] = False
                lead_draft["email_source"] = "company_site"
                lead_draft.setdefault("raw_data", {})["all_company_emails"] = company_emails
                return lead_draft

    # ── 2b. WHOIS / RDAP registrant email
    if domain and "." in domain:
        from backend.sources.whois_rdap import lookup_domain
        whois_data = lookup_domain(domain)
        if whois_data and whois_data.get("email"):
            email = whois_data["email"]
            if "@" in email and not is_noreply(email):
                lead_draft["person_email"] = email
                lead_draft["email_verified"] = False
                lead_draft["email_source"] = "whois"
                lead_draft.setdefault("raw_data", {})["whois"] = whois_data
                return lead_draft

    # ── 3. GitHub commit emails (skip for HN/Reddit speculative URLs)
    is_speculative_github = lead_draft.get("source") in ("hackernews", "reddit")
    if lead_draft.get("person_github_url") and not is_speculative_github:
        commit_emails = scrape_github_commit_emails(lead_draft["person_github_url"])
        if commit_emails:
            picked = _pick_personal_email(commit_emails, name)
            if picked:
                lead_draft["person_email"] = picked
                lead_draft["email_verified"] = False
                lead_draft["email_source"] = "github_commit"
                return lead_draft

    # ── 4. Hunter.io BEFORE pattern guess (more reliable when available)
    if hunter_quota_available() and name and domain:
        email = hunter_find(name, domain)
        if email:
            lead_draft["person_email"] = email
            lead_draft["email_verified"] = True
            lead_draft["email_source"] = "hunter"
            return lead_draft

    # ── 5. Best-guess pattern — UNVERIFIED, last resort
    if name and domain:
        guess = best_guess_email(name, domain)
        if guess:
            lead_draft["person_email"] = guess
            lead_draft["email_verified"] = False
            lead_draft["email_source"] = "pattern_guess"
            return lead_draft

    return lead_draft
