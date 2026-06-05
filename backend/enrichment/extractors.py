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


# Anti-scraping obfuscation: "name [at] domain [dot] com", "name (at) domain dot com", etc.
# Normalise these back to real "@"/"." so the email regex can catch them.
_AT_RE = re.compile(r"\s*[\[\(\{]?\s*(?:at|@)\s*[\]\)\}]?\s*", re.IGNORECASE)
_DOT_RE = re.compile(r"\s*[\[\(\{]\s*(?:dot|\.)\s*[\]\)\}]\s*", re.IGNORECASE)
# Only deobfuscate spans that actually look like an obfuscated email, so we don't
# mangle ordinary prose containing the words "at"/"dot".
_OBFUSCATED_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+\s*[\[\(\{]?\s*(?:at|@)\s*[\]\)\}]?\s*"
    r"[A-Za-z0-9.\-]+(?:\s*[\[\(\{]?\s*(?:dot|\.)\s*[\]\)\}]?\s*[A-Za-z]{2,})+",
    re.IGNORECASE,
)


def _deobfuscate(text: str) -> str:
    def _fix(m: re.Match) -> str:
        span = m.group(0)
        span = _AT_RE.sub("@", span, count=1)
        span = _DOT_RE.sub(".", span)
        # bare " dot " (no brackets) between word chars → "."
        span = re.sub(r"(?<=[A-Za-z0-9])\s+dot\s+(?=[A-Za-z0-9])", ".", span, flags=re.IGNORECASE)
        return span.replace(" ", "")
    return _OBFUSCATED_RE.sub(_fix, text)


def decode_cfemail(hex_str: str) -> str | None:
    """Decode a Cloudflare email-protection token (the hex in data-cfemail)."""
    try:
        key = int(hex_str[:2], 16)
        return "".join(
            chr(int(hex_str[i:i + 2], 16) ^ key) for i in range(2, len(hex_str), 2)
        )
    except (ValueError, IndexError):
        return None


def extract_emails_from_text(text: str | None) -> list[str]:
    """Pull all plausible emails out of free-form text (HN/Reddit comments, etc.)."""
    if not text:
        return []
    text = _deobfuscate(_unescape(text))
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


_PHONE_RE = re.compile(r"(?:\+?\d[\d\-().\s]{7,}\d)")


def _clean_phone(raw: str) -> str | None:
    """Normalise a tel: / visible-text phone to a compact, plausible number."""
    digits = re.sub(r"[^\d+]", "", raw)
    # A real phone has 7–15 digits (E.164 max is 15); reject obvious junk.
    core = digits.lstrip("+")
    if 7 <= len(core) <= 15:
        return digits
    return None


def scrape_company_contacts(domain: str, max_pages: int = 4, timeout: int = 8) -> dict:
    """Fetch a company's homepage + contact pages; return both emails and phones.

    Handles mailto:/tel: links, Cloudflare-obfuscated emails (data-cfemail),
    and "name [at] domain [dot] com" text obfuscation. Returns
    {"emails": [...], "phones": [...]} — caller decides which to attach.
    """
    if not domain:
        return {"emails": [], "phones": []}
    domain = domain.lstrip("www.").rstrip("/")
    if "://" in domain:
        domain = urlparse(domain).netloc

    base = f"https://{domain}"
    emails: set[str] = set()
    phones: set[str] = set()
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
                    emails.add(email)
            # 2. tel: links — phones
            for a in tree.css("a[href^='tel:']"):
                href = a.attributes.get("href", "")
                phone = _clean_phone(href.split("tel:", 1)[-1])
                if phone:
                    phones.add(phone)
            # 3. Cloudflare email protection (data-cfemail attribute)
            for el in tree.css("[data-cfemail]"):
                decoded = decode_cfemail(el.attributes.get("data-cfemail", ""))
                if decoded and "@" in decoded:
                    emails.add(decoded.lower())
            # 4. emails in visible text (deobfuscated inside extract_emails_from_text)
            visible_text = tree.body.text(separator=" ", strip=True) if tree.body else ""
            for e in extract_emails_from_text(visible_text):
                # Only keep emails on this company's own domain (skip vendor/partner emails)
                if e.endswith("@" + domain) or domain in e.split("@")[1]:
                    emails.add(e)
        except Exception as e:
            log.debug(f"Company scrape failed for {url}: {e}")
            continue

    clean_emails = [
        e for e in emails
        if not any(b in e.split("@")[0] for b in ("noreply", "no-reply", "donotreply"))
    ]
    return {"emails": clean_emails, "phones": list(phones)}


def scrape_company_emails(domain: str, max_pages: int = 4, timeout: int = 8) -> list[str]:
    """Back-compat wrapper — emails only. New callers should use scrape_company_contacts."""
    return scrape_company_contacts(domain, max_pages=max_pages, timeout=timeout)["emails"]
