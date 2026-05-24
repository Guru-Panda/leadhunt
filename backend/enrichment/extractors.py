"""Shared helpers for pulling emails out of free-form text and web pages."""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)

# Standard email regex — RFC 5322 lite, good enough for free-form text
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Common false positives — file names, image URLs, library refs
_EMAIL_BLOCKLIST = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "example.com", "domain.com", "test.com", "yourcompany.com",
    "sentry.io", "github.com", "gravatar.com", "wordpress.com",
}

# HTML entity unescape map for common cases
_ENTITY_MAP = {
    "&#x2F;": "/", "&#x40;": "@", "&amp;": "&", "&lt;": "<",
    "&gt;": ">", "&quot;": '"', "&#x27;": "'", "&apos;": "'",
}


def _unescape(text: str) -> str:
    for k, v in _ENTITY_MAP.items():
        text = text.replace(k, v)
    return text


def extract_emails_from_text(text: str | None) -> list[str]:
    """Pull all plausible emails out of free-form text (HN/Reddit comments, etc.)."""
    if not text:
        return []
    text = _unescape(text)
    found = _EMAIL_RE.findall(text)
    out: list[str] = []
    seen: set[str] = set()
    for email in found:
        email = email.lower().strip(".,;:!?")
        if email in seen:
            continue
        # Skip obvious garbage
        local, _, domain = email.partition("@")
        if not local or not domain:
            continue
        if any(b in domain for b in _EMAIL_BLOCKLIST) or local in _EMAIL_BLOCKLIST:
            continue
        # Filter image/file-like patterns (e.g. "2x@cdn.foo.com" from img srcsets)
        if re.match(r"^\d+x$", local):
            continue
        seen.add(email)
        out.append(email)
    return out


_CONTACT_PATHS = ["/", "/contact", "/contact-us", "/about", "/about-us", "/team", "/people"]
_UA = "Mozilla/5.0 LeadHunt/1.0"


def scrape_company_emails(domain: str, max_pages: int = 4, timeout: int = 8) -> list[str]:
    """Fetch a company's homepage + common contact pages, return mailto: emails found.

    Returns ALL emails found — caller decides which to attach to which person.
    """
    if not domain:
        return []
    domain = domain.lstrip("www.").rstrip("/")
    if "://" in domain:
        domain = urlparse(domain).netloc
    base = f"https://{domain}"

    found: set[str] = set()
    pages_fetched = 0

    for path in _CONTACT_PATHS:
        if pages_fetched >= max_pages:
            break
        url = urljoin(base, path)
        try:
            r = httpx.get(url, timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True)
            pages_fetched += 1
            if r.status_code != 200 or not r.text:
                continue
            tree = HTMLParser(r.text)
            # 1. mailto: links — highest signal
            for a in tree.css("a[href^='mailto:']"):
                href = a.attributes.get("href", "")
                email = href.split("mailto:", 1)[-1].split("?", 1)[0].lower().strip()
                if email and "@" in email:
                    found.add(email)
            # 2. emails in visible text (some sites obfuscate to text-only)
            visible_text = tree.body.text(separator=" ", strip=True) if tree.body else ""
            for e in extract_emails_from_text(visible_text):
                # Only keep emails on this company's own domain (skip vendor/partner emails)
                if e.endswith("@" + domain) or domain in e.split("@")[1]:
                    found.add(e)
        except Exception as e:
            log.debug(f"Company scrape failed for {url}: {e}")
            continue

    # Filter noreply
    return [e for e in found if not any(b in e.split("@")[0] for b in ("noreply", "no-reply", "donotreply"))]
