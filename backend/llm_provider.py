"""LLM provider abstraction for the ParkSentinel query engine.

Provider selection priority (harness engineering):
    1. Gemini   - if GEMINI_API_KEY is set (primary, REST API)
    2. OpenAI   - if OPENAI_API_KEY is set (fallback)
    3. Groq     - if GROQ_API_KEY is set (second fallback, 1k RPD free)
    4. (error)  - graceful failure with an actionable message

Both free-tier keys are tightly quota-capped, so ``complete`` does NOT just run
the primary provider and surface its error. It walks the provider chain in
priority order and, when a provider call fails (most importantly a Gemini HTTP
429 / RESOURCE_EXHAUSTED daily-quota error), AUTOMATICALLY FALLS BACK to the
next configured provider (OpenAI on the cheapest durable model). Only when every
provider in the chain fails does it raise ``LLMError``. This keeps the demo's
/query path answering even after Gemini's ~20 requests/day/model free-tier cap
is exhausted.

Anthropic is intentionally dormant: the user opted out, so the code path
exists for completeness but is *never* placed in the provider chain.

This module is provider-agnostic from the caller's perspective: callers use
``complete(system_instruction, user_text)`` and get back plain text, with
request timeouts, structured logging (provider / latency / errors), a small
HTTP-level retry for transient failures, and cross-provider failover handled
here.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

logger = logging.getLogger(__name__)

# --- Key wiring --------------------------------------------------------------
# Load backend/.env explicitly and let it WIN over any pre-existing process /
# OS environment variable. Without override=True a stale machine/user-scope
# OPENAI_API_KEY (or GEMINI_API_KEY) silently shadows the project key — that
# breaks the OpenAI fallback with a 401 even though backend/.env is correct.
# We resolve the path relative to this file so it works no matter the CWD the
# server (uvicorn) was launched from. python-dotenv is a declared dependency
# (see requirements.txt); guard the import so a stripped deployment still runs.
try:  # pragma: no cover - trivial wiring
    from dotenv import load_dotenv

    load_dotenv(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        override=True,
    )
except Exception:  # noqa: BLE001 - never let env loading break import
    pass

# --- Configuration -----------------------------------------------------------

# Pinned to "gemini-2.5-flash". The "*-latest" aliases resolve to a heavier
# thinking model (gemini-3.5-flash) that burned ~78 reasoning tokens
# (thoughtsTokenCount) on an ~8-token Text-to-SQL prompt (90 total). 2.5-flash
# still does light default thinking (~24-33 thoughts/call observed) but roughly
# halves the per-call burn and returns plain text parts directly, so the normal
# text-concatenation path works. NOTE: this does NOT by itself stop HTTP 429 --
# that is a separate free-tier *request-count* cap (~20 requests/day/model);
# raise it with a billing-enabled key, not by changing the model.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
# Cheapest DURABLE OpenAI model for Text-to-SQL, configurable via OPENAI_MODEL.
# Chosen: "gpt-4.1-nano" ($0.10/M input, $0.40/M output as of mid-2026) — GA, 1M
# context, purpose-built for classification/extraction/routing (Text-to-SQL
# fits), and verified live to return valid SQL at temperature=0.0.
# NOT "gpt-5-nano": although cheaper on input ($0.05/M), it is a reasoning model
# that REJECTS non-default temperature on chat.completions ("temperature does
# not support 0.0 ... only the default (1) value is supported"), so it is
# incompatible with this pipeline's temperature=0.0/0.2 calls without
# restructuring. gpt-4.1-nano also beats the old gpt-4o-mini default ($0.15/M
# in, $0.60/M out) on price. Override OPENAI_MODEL to switch models.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-nano")

# Groq: free 1,000 RPD on 70B model. Uses the OpenAI SDK with a custom base_url.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Network / robustness knobs.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
LLM_HTTP_RETRIES = int(os.getenv("LLM_HTTP_RETRIES", "2"))


class LLMError(RuntimeError):
    """Raised when no provider is configured or a provider call fails hard."""


# --- Provider detection ------------------------------------------------------

def get_provider_chain() -> list[str]:
    """Return configured providers in priority/failover order.

    Gemini is primary (it resets daily and is the project default); OpenAI is
    the fallback. Anthropic is intentionally excluded (user opted out) even if
    ANTHROPIC_API_KEY is present. ``complete`` walks this list and fails over to
    the next provider on error (e.g. a Gemini 429 daily-quota exhaustion).
    """
    chain: list[str] = []
    if os.getenv("GEMINI_API_KEY"):
        chain.append("gemini")
    if os.getenv("OPENAI_API_KEY"):
        chain.append("openai")
    if os.getenv("GROQ_API_KEY"):
        chain.append("groq")
    return chain


def get_active_provider() -> str | None:
    """Return the primary provider that will be tried first, or None.

    Anthropic is never returned here even if ANTHROPIC_API_KEY is present.
    """
    chain = get_provider_chain()
    return chain[0] if chain else None


def provider_status() -> dict[str, object]:
    """Lightweight status snapshot, handy for logging / health output."""
    return {
        "active": get_active_provider(),
        "provider_chain": get_provider_chain(),  # priority + failover order
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "anthropic_used": False,  # opted out — never selected
        "gemini_model": GEMINI_MODEL,
        "openai_model": OPENAI_MODEL,
        "groq_model": GROQ_MODEL,
    }


# --- Gemini (REST) -----------------------------------------------------------

def _extract_gemini_text(payload: dict) -> str:
    """Pull plain text out of a Gemini generateContent response.

    Robust to "thinking" models that may emit multiple parts (some carrying
    only a ``thoughtSignature`` and no ``text``): we concatenate every part
    that actually contains text.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback")
        raise LLMError(f"Gemini returned no candidates (promptFeedback={feedback})")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p["text"] for p in parts if isinstance(p, dict) and "text" in p)
    if not text.strip():
        raise LLMError("Gemini candidate contained no text parts")
    return text


def _call_gemini(system_instruction: str, user_text: str, temperature: float) -> str:
    import requests  # local import keeps module import cheap

    api_key = os.environ["GEMINI_API_KEY"]
    body = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": temperature},
    }
    headers = {"X-goog-api-key": api_key, "Content-Type": "application/json"}

    last_err: Exception | None = None
    for attempt in range(LLM_HTTP_RETRIES + 1):
        try:
            resp = requests.post(
                GEMINI_ENDPOINT, headers=headers, json=body, timeout=LLM_TIMEOUT_SECONDS
            )
            if resp.status_code != 200:
                # 429 / 5xx are worth retrying; 4xx (except 429) are not.
                retryable = resp.status_code == 429 or resp.status_code >= 500
                msg = f"Gemini HTTP {resp.status_code}: {resp.text[:300]}"
                if retryable and attempt < LLM_HTTP_RETRIES:
                    last_err = LLMError(msg)
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise LLMError(msg)
            return _extract_gemini_text(resp.json())
        except requests.RequestException as e:  # timeout / connection errors
            last_err = e
            if attempt < LLM_HTTP_RETRIES:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise LLMError(f"Gemini request failed: {e}") from e
    raise LLMError(f"Gemini request failed: {last_err}")


# --- OpenAI (fallback) -------------------------------------------------------

def _call_openai(system_instruction: str, user_text: str, temperature: float) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=LLM_TIMEOUT_SECONDS)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_text},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


# --- Groq (third fallback) ---------------------------------------------------

def _call_groq(system_instruction: str, user_text: str, temperature: float) -> str:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ["GROQ_API_KEY"],
        timeout=LLM_TIMEOUT_SECONDS,
    )
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_text},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


# --- Anthropic (DORMANT — never selected) ------------------------------------

def _call_anthropic(system_instruction: str, user_text: str, temperature: float) -> str:
    """Dormant fallback. Kept for completeness; never reached via ``complete``."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=1024,
        temperature=temperature,
        system=system_instruction,
        messages=[{"role": "user", "content": user_text}],
    )
    return resp.content[0].text


_DISPATCH: dict[str, Callable[[str, str, float], str]] = {
    "gemini": _call_gemini,
    "openai": _call_openai,
    "groq": _call_groq,
    "anthropic": _call_anthropic,  # registered but never selected
}


# --- Failover classification -------------------------------------------------

# Substrings that mark a quota / rate-limit / availability error worth failing
# over on. Matched case-insensitively against "<ErrorType>: <message>" so it
# catches both the Gemini REST path ("Gemini HTTP 429: ... RESOURCE_EXHAUSTED")
# and the OpenAI SDK path (RateLimitError, insufficient_quota, 5xx, etc.).
_QUOTA_SIGNALS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "ratelimit",
    "rate_limit",
    "quota",
    "insufficient_quota",
    "too many requests",
    "overloaded",
    "unavailable",
    "503",
    "502",
    "504",
    "500",
    "timeout",
    "timed out",
)


def _is_quota_or_availability_error(exc: Exception) -> bool:
    """True if ``exc`` looks like a quota/rate-limit/transient availability error."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(sig in text for sig in _QUOTA_SIGNALS)


# --- Public API --------------------------------------------------------------

def complete(
    system_instruction: str,
    user_text: str,
    *,
    temperature: float = 0.0,
) -> str:
    """Run a completion, failing over across the provider chain on error.

    Tries each configured provider in priority order (Gemini -> OpenAI). On a
    provider failure it cascades to the next provider — most importantly a
    Gemini HTTP 429 / daily-quota exhaustion transparently falls back to OpenAI
    (cheapest model) instead of surfacing the 429 as the user's answer. Raises
    ``LLMError`` only when no provider is configured or every provider fails.
    Emits structured logs with provider name, latency, and failover reason.
    """
    chain = get_provider_chain()
    if not chain:
        raise LLMError(
            "No LLM API key configured. Set GEMINI_API_KEY (preferred), "
            "OPENAI_API_KEY, or GROQ_API_KEY in backend/.env"
        )

    errors: list[str] = []
    for idx, provider in enumerate(chain):
        has_next = idx + 1 < len(chain)
        start = time.perf_counter()
        try:
            text = _DISPATCH[provider](system_instruction, user_text, temperature)
            latency_ms = (time.perf_counter() - start) * 1000
            if idx > 0:
                logger.warning(
                    "llm.complete recovered via fallback provider=%s after %d "
                    "failed provider(s)",
                    provider,
                    idx,
                )
            logger.info(
                "llm.complete provider=%s latency_ms=%.0f chars=%d",
                provider,
                latency_ms,
                len(text),
            )
            return text
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            quota = _is_quota_or_availability_error(e)
            errors.append(f"{provider}: {e}")
            logger.error(
                "llm.complete FAILED provider=%s latency_ms=%.0f quota=%s "
                "will_fallback=%s err=%s",
                provider,
                latency_ms,
                quota,
                has_next,
                e,
            )
            if has_next:
                logger.warning(
                    "llm.failover %s -> %s (reason=%s)",
                    provider,
                    chain[idx + 1],
                    "quota/429" if quota else "provider_error",
                )
                continue
            # Last provider in the chain also failed — surface a combined error.
            raise LLMError(
                "All configured LLM providers failed: " + " | ".join(errors)
            ) from e

    # Defensive: chain was non-empty, so we either returned or raised above.
    raise LLMError("No LLM provider produced a response")
