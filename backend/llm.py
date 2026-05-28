from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from groq import Groq

from backend.config import settings

log = logging.getLogger(__name__)

_client: Groq | None = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

FAST_MODEL = "llama-3.1-8b-instant"
HQ_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"

# ── Rate-limit state (module-level, in-process) ────────────────────────────────
# Set when Groq returns a 429/quota error so the UI can warn that AI scoring is
# temporarily degraded to keyword matching.
_rate_limited_until: datetime | None = None


def _parse_retry_after(err_text: str) -> datetime:
    """Best-effort parse of 'try again in 5m56s' from Groq's 429 body."""
    now = datetime.now(timezone.utc)
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)s", err_text)
    if m:
        mins = int(m.group(1) or 0)
        secs = float(m.group(2) or 0)
        return now + timedelta(minutes=mins, seconds=secs)
    # Daily token cap with no parseable hint → assume it resets within the day
    if "per day" in err_text.lower() or "TPD" in err_text:
        return now + timedelta(hours=2)
    return now + timedelta(minutes=5)


def _mark_rate_limited(err_text: str) -> None:
    global _rate_limited_until
    _rate_limited_until = _parse_retry_after(err_text)
    log.warning(f"Groq rate-limited until ~{_rate_limited_until.isoformat()}")


def llm_status() -> dict:
    """Current LLM availability — consumed by GET /system/llm-status."""
    now = datetime.now(timezone.utc)
    limited = _rate_limited_until is not None and _rate_limited_until > now
    return {
        "configured": _client is not None,
        "rate_limited": limited,
        "resets_at": _rate_limited_until.isoformat() if (limited and _rate_limited_until) else None,
    }


def llm_call(
    prompt: str,
    high_quality: bool = False,
    max_tokens: int = 1000,
    retries: int = 3,
) -> str:
    global _rate_limited_until
    if _client is None:
        raise RuntimeError("GROQ_API_KEY is not configured")
    model = HQ_MODEL if high_quality else FAST_MODEL
    models_to_try = [model, FALLBACK_MODEL] if model != FALLBACK_MODEL else [FALLBACK_MODEL]

    for attempt, m in enumerate(models_to_try):
        for retry in range(retries):
            try:
                response = _client.chat.completions.create(
                    model=m,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                # Success — clear any stale rate-limit flag
                _rate_limited_until = None
                return response.choices[0].message.content.strip()
            except Exception as e:
                err_text = str(e)
                if "429" in err_text or "rate_limit" in err_text.lower() or "quota" in err_text.lower():
                    _mark_rate_limited(err_text)
                wait = 2 ** retry
                log.warning(f"LLM call failed (model={m}, retry={retry}): {e}. Waiting {wait}s")
                if retry < retries - 1:
                    time.sleep(wait)

    raise RuntimeError("All LLM models and retries exhausted")


def llm_json(prompt: str, high_quality: bool = False, max_tokens: int = 1500) -> dict | list:
    raw = llm_call(prompt, high_quality=high_quality, max_tokens=max_tokens)
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # LLM often wraps JSON in prose ("Here's the result: [...]"). Extract the
    # outermost [...] or {...} region and try that.
    start_array = raw.find("[")
    start_object = raw.find("{")
    if start_array == -1 and start_object == -1:
        raise ValueError(f"llm_json: no JSON found in response: {raw[:200]}")
    starts = [s for s in (start_array, start_object) if s != -1]
    start = min(starts)
    open_char = raw[start]
    close_char = "]" if open_char == "[" else "}"
    end = raw.rfind(close_char)
    if end > start:
        candidate = raw[start: end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Truncation repair: cut back to last "}," then close the array
            if open_char == "[":
                last_obj_end = candidate.rfind("},")
                if last_obj_end > 0:
                    repaired = candidate[: last_obj_end + 1] + "]"
                    try:
                        return json.loads(repaired)
                    except Exception:
                        pass
    log.error(f"llm_json: could not parse or repair. Raw (first 400): {raw[:400]}")
    raise ValueError(f"llm_json: parse failed for response: {raw[:200]}")
