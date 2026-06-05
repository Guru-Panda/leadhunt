"""Multi-provider LLM pool with automatic failover.

Every provider here speaks the OpenAI chat-completions API, so we call them all
with one httpx path — no per-vendor SDKs, no heavy deps. The pool rotates across
whatever free keys are configured; when one rate-limits (429) it goes on a short
cooldown and the next provider takes over. This is what stops a single free-tier
daily cap from taking the whole app down.

Add keys in .env for any of: GROQ, GEMINI, CEREBRAS, OPENROUTER, TOGETHER.
Order = priority (fastest/most-generous first).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from backend.config import settings

log = logging.getLogger(__name__)

_COOLDOWN_MINUTES = 5      # how long to skip a provider after a 429
_TIMEOUT = 30

# Per-provider cooldown timestamps (in-process).
_cooldown: dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _providers() -> list[dict]:
    """Configured providers in priority order. Only those with a key are returned."""
    out: list[dict] = []
    if settings.GROQ_API_KEY:
        out.append({
            "name": "groq",
            "base": "https://api.groq.com/openai/v1",
            "key": settings.GROQ_API_KEY,
            "fast": "llama-3.1-8b-instant",
            "hq": "llama-3.3-70b-versatile",
        })
    if settings.GEMINI_API_KEY:
        out.append({
            "name": "gemini",
            "base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "key": settings.GEMINI_API_KEY,
            "fast": "gemini-2.0-flash-lite",
            "hq": "gemini-2.0-flash",
        })
    if settings.CEREBRAS_API_KEY:
        out.append({
            "name": "cerebras",
            "base": "https://api.cerebras.ai/v1",
            "key": settings.CEREBRAS_API_KEY,
            "fast": "llama3.1-8b",
            "hq": "llama-3.3-70b",
        })
    if settings.OPENROUTER_API_KEY:
        out.append({
            "name": "openrouter",
            "base": "https://openrouter.ai/api/v1",
            "key": settings.OPENROUTER_API_KEY,
            "fast": "meta-llama/llama-3.3-70b-instruct:free",
            "hq": "meta-llama/llama-3.3-70b-instruct:free",
        })
    if settings.TOGETHER_API_KEY:
        out.append({
            "name": "together",
            "base": "https://api.together.xyz/v1",
            "key": settings.TOGETHER_API_KEY,
            "fast": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
            "hq": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        })
    return out


def _available(provs: list[dict]) -> list[dict]:
    now = _now()
    return [p for p in provs if _cooldown.get(p["name"], now) <= now]


def chat(prompt: str, high_quality: bool = False, max_tokens: int = 1000,
         temperature: float = 0.3) -> str:
    """Call the first available provider; fail over on rate-limit / error.

    Raises RuntimeError only when every configured provider is unavailable.
    """
    provs = _providers()
    if not provs:
        raise RuntimeError("No LLM provider configured (set GROQ_API_KEY or another)")

    last_err: Exception | None = None
    for p in _available(provs):
        model = p["hq"] if high_quality else p["fast"]
        try:
            r = httpx.post(
                f"{p['base']}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                headers={
                    "Authorization": f"Bearer {p['key']}",
                    "Content-Type": "application/json",
                },
                timeout=_TIMEOUT,
            )
            if r.status_code == 429:
                _cooldown[p["name"]] = _now() + timedelta(minutes=_COOLDOWN_MINUTES)
                log.warning(f"[llm_pool] {p['name']} rate-limited (429) — cooling down, trying next")
                continue
            if r.status_code in (401, 403):
                # Bad/forbidden key — cool down longer so we stop hammering it.
                _cooldown[p["name"]] = _now() + timedelta(hours=1)
                log.error(f"[llm_pool] {p['name']} auth failed ({r.status_code}) — check the key")
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return (content or "").strip()
        except Exception as e:  # network error, bad shape, etc. — try next provider
            last_err = e
            log.warning(f"[llm_pool] {p['name']} call failed: {e}")
            continue

    raise RuntimeError(f"All LLM providers unavailable/exhausted: {last_err}")


def pool_status() -> dict:
    """Health of the pool — consumed by GET /system/llm-status and the cron's
    degraded-mode checks. rate_limited is True only when EVERY provider is down."""
    provs = _providers()
    avail = _available(provs)
    next_reset = None
    if provs and not avail:
        soonest = min(_cooldown.get(p["name"], _now()) for p in provs)
        next_reset = soonest.isoformat()
    return {
        "configured": len(provs) > 0,
        "providers": [p["name"] for p in provs],
        "available": [p["name"] for p in avail],
        "rate_limited": len(provs) > 0 and len(avail) == 0,
        "resets_at": next_reset,
    }
