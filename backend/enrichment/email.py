from __future__ import annotations

import logging
import re
import smtplib
from urllib.parse import urlparse

import dns.resolver
import httpx
from selectolax.parser import HTMLParser

from backend.enrichment.extractors import extract_emails_from_text, scrape_company_contacts

log = logging.getLogger(__name__)

MAX_SMTP_VERIFIES_PER_LEAD = 5
SMTP_TIMEOUT = 5


def is_noreply(email: str) -> bool:
    prefix = email.split("@")[0].lower()
    return any(k in prefix for k in ["noreply", "no-reply", "notifications", "support", "info", "hello", "team"])


# ── Free MX-existence gate ────────────────────────────────────────────────────
# Port-25 SMTP RCPT is blocked on most networks (Windows dev, Railway), so the
# only free deliverability signal we can trust is whether the domain even has a
# mail server. We refuse to save guessed/scraped emails on domains with no MX.
_mx_cache: dict[str, bool] = {}


def _normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    d = domain.strip().lower()
    if "://" in d:
        d = urlparse(d).netloc
    d = d.lstrip("www.").rstrip("/").split("/")[0]
    return d or None


def domain_has_mx(domain: str | None) -> bool:
    """True if the domain publishes an MX (or fallback A) record — cached per process.

    Conservative on lookup failure: returns True so a transient DNS error never
    silently drops an otherwise-good email.
    """
    d = _normalize_domain(domain)
    if not d or "." not in d:
        return False
    if d in _mx_cache:
        return _mx_cache[d]
    try:
        answers = dns.resolver.resolve(d, "MX")
        ok = len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        # No MX — RFC 5321 allows falling back to an A record for mail.
        try:
            dns.resolver.resolve(d, "A")
            ok = True
        except Exception:
            ok = False
    except Exception as e:
        log.debug(f"MX lookup failed for {d}: {e}")
        ok = True  # transient failure — don't penalise the lead
    _mx_cache[d] = ok
    return ok


# ── Graded email confidence (0.0–1.0) ─────────────────────────────────────────
# How reachable is this email, by how we found it. Verified hits and explicitly
# published addresses rank highest; unverified pattern guesses rank lowest.
_CONFIDENCE_BY_SOURCE: dict[str, float] = {
    "source_text": 0.92,      # the person posted it publicly themselves
    "company_site": 0.85,     # listed on the company's own site
    "github_commit": 0.85,    # from their own commits
    "apollo": 0.9,            # Apollo verified contact DB
    "hunter": 0.8,           # Hunter finder (confidence-scored)
    "hunter_verified": 0.9,   # Hunter verifier said valid
    "whois": 0.65,            # domain registrant — may be an agent/privacy proxy
    "pattern_guess": 0.35,    # heuristic guess
}


def compute_email_confidence(source: str | None, verified: bool, has_mx: bool) -> float:
    base = _CONFIDENCE_BY_SOURCE.get(source or "", 0.5)
    if verified:
        base = max(base, 0.9)
    if not has_mx:
        base = min(base, 0.2)  # domain can't receive mail — heavily discount
    return round(base, 2)


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


def _finalize(lead_draft: dict) -> dict:
    """Stamp a graded email_confidence based on how the email was found + MX check."""
    email = lead_draft.get("person_email")
    if email:
        has_mx = domain_has_mx(email.split("@")[-1])
        lead_draft["email_confidence"] = compute_email_confidence(
            lead_draft.get("email_source"), bool(lead_draft.get("email_verified")), has_mx
        )
    else:
        lead_draft.setdefault("email_confidence", 0.0)
    return lead_draft


def enrich_lead(lead_draft: dict) -> dict:
    """Layered email + phone discovery. Each path is short-circuit, ordered by signal strength:
      1. Email already on the lead (from source extraction)
      1b. Apollo People Match unlock (reveals the real email/phone behind a masked search hit)
      2. Scrape company website mailto/tel links (great for SMB founders)
      2b. WHOIS/RDAP registrant email
      3. GitHub commit emails (gold for OSS folk)
      4. Hunter.io finder (if quota available)
      5. Best-guess pattern — last resort, gated on the domain having an MX record
    Every returned lead carries a graded `email_confidence` (0.0–1.0).
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
            return _finalize(lead_draft)

    # ── 1b. Apollo unlock — search results come back masked (email_not_unlocked@…).
    #        The People Match endpoint reveals the real email (+ phone). Budget-capped.
    if lead_draft.get("source") == "apollo":
        apollo_id = (lead_draft.get("raw_data") or {}).get("apollo_id")
        if apollo_id or lead_draft.get("person_linkedin_url"):
            from backend.sources.apollo import unlock as apollo_unlock
            unlocked = apollo_unlock(apollo_id, lead_draft.get("person_linkedin_url"))
            if unlocked:
                if unlocked.get("phone") and not lead_draft.get("person_phone"):
                    lead_draft["person_phone"] = unlocked["phone"]
                    lead_draft["phone_source"] = "apollo"
                em = unlocked.get("email")
                if em and not is_noreply(em):
                    lead_draft["person_email"] = em
                    lead_draft["email_verified"] = unlocked.get("email_status") == "verified"
                    lead_draft["email_source"] = "apollo"
                    return _finalize(lead_draft)

    # ── 2. Scrape the company's site (only if we have a real, source-set domain)
    if domain and "." in domain:
        contacts = scrape_company_contacts(domain)
        company_emails = contacts.get("emails") or []
        company_phones = contacts.get("phones") or []
        if company_phones and not lead_draft.get("person_phone"):
            lead_draft["person_phone"] = company_phones[0]
            lead_draft["phone_source"] = "company_site"
        if company_emails:
            picked = _pick_personal_email(company_emails, name)
            if picked:
                lead_draft["person_email"] = picked
                lead_draft["email_verified"] = False
                lead_draft["email_source"] = "company_site"
                lead_draft.setdefault("raw_data", {})["all_company_emails"] = company_emails
                return _finalize(lead_draft)

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
                return _finalize(lead_draft)

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
                return _finalize(lead_draft)

    # ── 4. Hunter.io BEFORE pattern guess (more reliable when available)
    #       Quota-guarded: only fires while free-tier searches remain above buffer.
    if hunter_quota_available() and name and domain:
        email, verified = hunter_find(name, domain)
        if email:
            lead_draft["person_email"] = email
            lead_draft["email_verified"] = verified
            lead_draft["email_source"] = "hunter"
            return _finalize(lead_draft)

    # ── 5. Best-guess pattern — last resort. Try to VERIFY the guess for free
    #       via Hunter's verifier (separate 50/mo quota) so a confirmed guess
    #       becomes a real verified email instead of a shot in the dark.
    #       Skip entirely when the domain has no mail server — a guess there is
    #       guaranteed undeliverable, so it would only pollute the lead list.
    if name and domain and domain_has_mx(domain):
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

    return _finalize(lead_draft)
