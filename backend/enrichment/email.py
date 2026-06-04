from __future__ import annotations

import logging
import re
import smtplib
from urllib.parse import urlparse

import dns.resolver
import httpx
from selectolax.parser import HTMLParser

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


# ── Hunter.io free-tier guard ────────────────────────────────────────────────
# Free plan: 25 email-finder "searches" + 50 "verifications" per month. We must
# NOT blow through these blindly. We check the account's remaining quota (cached
# per process) and keep a safety buffer so manual UI usage isn't starved.
_HUNTER_SAFETY_BUFFER = 3          # never spend the last N searches automatically
_hunter_cache: dict = {"searches_left": None, "verifications_left": None, "checked": False}


def _hunter_account() -> dict:
    """Fetch remaining Hunter quota once per process. Returns {} on failure.

    Response shape (v2/account):
      data.requests.searches      = {used, available}
      data.requests.verifications = {used, available}
    """
    from backend.config import settings
    if _hunter_cache["checked"]:
        return _hunter_cache
    _hunter_cache["checked"] = True
    if not settings.HUNTER_API_KEY:
        return _hunter_cache
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/account",
            params={"api_key": settings.HUNTER_API_KEY},
            timeout=10,
        )
        reqs = (r.json().get("data") or {}).get("requests") or {}
        srch = reqs.get("searches") or {}
        verf = reqs.get("verifications") or {}
        _hunter_cache["searches_left"] = max(0, (srch.get("available", 0) - srch.get("used", 0)))
        _hunter_cache["verifications_left"] = max(0, (verf.get("available", 0) - verf.get("used", 0)))
        log.info(
            f"[hunter] free quota — searches left: {_hunter_cache['searches_left']}, "
            f"verifications left: {_hunter_cache['verifications_left']}"
        )
    except Exception as e:
        log.debug(f"[hunter] account check failed: {e}")
    return _hunter_cache


def hunter_quota_available() -> bool:
    """True only if a Hunter key is set AND there's search quota above the buffer."""
    from backend.config import settings
    if not settings.HUNTER_API_KEY:
        return False
    acct = _hunter_account()
    left = acct.get("searches_left")
    if left is None:
        return True  # account check failed — allow one attempt, finder will self-limit
    return left > _HUNTER_SAFETY_BUFFER


def _hunter_verifications_available() -> bool:
    from backend.config import settings
    if not settings.HUNTER_API_KEY:
        return False
    acct = _hunter_account()
    left = acct.get("verifications_left")
    if left is None:
        return True
    return left > _HUNTER_SAFETY_BUFFER


def hunter_find(name: str, domain: str) -> tuple[str | None, bool]:
    """Find a person's email via Hunter. Returns (email, verified).

    `verified` is True only when Hunter's confidence score is high (>=80) or it
    explicitly returns verification.status == "valid". Otherwise the email is a
    confidence-scored guess and should be saved as unverified.
    """
    from backend.config import settings
    if not settings.HUNTER_API_KEY:
        return None, False
    parts = (name or "").split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first, "last_name": last, "api_key": settings.HUNTER_API_KEY},
            timeout=10,
        )
        # Decrement our cached counter so we stop before exhausting the free tier
        if _hunter_cache["searches_left"] is not None:
            _hunter_cache["searches_left"] = max(0, _hunter_cache["searches_left"] - 1)
        data = r.json().get("data", {}) or {}
        email = data.get("email")
        if not email:
            return None, False
        score = data.get("score") or 0
        status = (data.get("verification") or {}).get("status") or ""
        verified = status == "valid" or score >= 80
        return email, verified
    except Exception as e:
        log.debug(f"Hunter API failed: {e}")
        return None, False


def hunter_verify(email: str) -> bool | None:
    """Verify a single email via Hunter's verifier (separate free quota).

    Returns True (valid), False (invalid), or None (unknown / no quota).
    Used to upgrade pattern-guessed emails to verified for free.
    """
    from backend.config import settings
    if not settings.HUNTER_API_KEY or not _hunter_verifications_available():
        return None
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": settings.HUNTER_API_KEY},
            timeout=10,
        )
        if _hunter_cache["verifications_left"] is not None:
            _hunter_cache["verifications_left"] = max(0, _hunter_cache["verifications_left"] - 1)
        status = (r.json().get("data") or {}).get("status") or ""
        if status == "valid":
            return True
        if status in ("invalid", "disposable"):
            return False
        return None  # accept_all / webmail / unknown — inconclusive
    except Exception as e:
        log.debug(f"Hunter verify failed for {email}: {e}")
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


_MOJEEK_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def find_linkedin_url(name: str, company: str | None = None, title: str | None = None) -> str | None:
    """Search Mojeek for the person's LinkedIn /in/ profile URL.

    Uses name + company (or title as fallback) to narrow results.
    Returns the first valid linkedin.com/in/ URL found, or None.
    """
    if not name or len(name.split()) < 2:
        return None
    query = f'site:linkedin.com/in "{name}"'
    if company:
        query += f' "{company}"'
    elif title:
        query += f' "{title}"'
    try:
        r = httpx.get(
            "https://www.mojeek.com/search",
            params={"q": query},
            headers={"User-Agent": _MOJEEK_UA, "Accept": "text/html"},
            timeout=10,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return None
        tree = HTMLParser(r.text)
        for a in tree.css(".results-standard a, .results a"):
            href = (a.attributes.get("href") or "").strip()
            if not href:
                continue
            try:
                p = urlparse(href)
                if "linkedin.com" in p.netloc and p.path.startswith("/in/"):
                    return href
            except Exception:
                continue
    except Exception as e:
        log.debug(f"LinkedIn URL lookup failed for {name!r}: {e}")
    return None


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
    #       Quota-guarded: only fires while free-tier searches remain above buffer.
    if hunter_quota_available() and name and domain:
        email, verified = hunter_find(name, domain)
        if email:
            lead_draft["person_email"] = email
            lead_draft["email_verified"] = verified
            lead_draft["email_source"] = "hunter"
            return lead_draft

    # ── 5. Best-guess pattern — last resort. Try to VERIFY the guess for free
    #       via Hunter's verifier (separate 50/mo quota) so a confirmed guess
    #       becomes a real verified email instead of a shot in the dark.
    if name and domain:
        guess = best_guess_email(name, domain)
        if guess:
            verdict = hunter_verify(guess)
            if verdict is False:
                # Guess is provably invalid — try the next-likeliest pattern once
                alts = guess_email_patterns(name, domain)[1:3]
                for alt in alts:
                    if hunter_verify(alt) is True:
                        guess = alt
                        verdict = True
                        break
            lead_draft["person_email"] = guess
            lead_draft["email_verified"] = verdict is True
            lead_draft["email_source"] = "hunter_verified" if verdict is True else "pattern_guess"

    # ── 6. LinkedIn URL — find profile for every lead that doesn't already have one
    #       Skip if we already have it (e.g. linkedin source sets it directly)
    if not lead_draft.get("person_linkedin_url") and name and len(name.split()) >= 2:
        li_url = find_linkedin_url(
            name,
            lead_draft.get("company_name"),
            lead_draft.get("person_title"),
        )
        if li_url:
            lead_draft["person_linkedin_url"] = li_url
            log.debug(f"LinkedIn URL enriched for {name!r}: {li_url}")

    return lead_draft
