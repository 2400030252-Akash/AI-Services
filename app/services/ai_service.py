"""
app/services/ai_service.py
===========================
AI reply generation via the NVIDIA API (DeepSeek model).

Uses the OpenAI Python client pointed at NVIDIA's OpenAI-compatible endpoint.
This is intentionally a pure service layer — no FastAPI routes here.
The Twilio webhook module will call ``generate_reply`` directly.

Public surface
--------------
    generate_reply(conversation_history) → str

        Takes a list of LLMMessage (from ConversationService.get_conversation_history)
        and returns the AI's plain-text reply, ready to be spoken aloud by Twilio TTS.

Design decisions
----------------
- **Async client** — using ``AsyncOpenAI`` so this never blocks the event loop.
- **Retry with exponential backoff** — up to 2 retries on transient API errors,
  with jitter to avoid thundering-herd on concurrent calls.
- **Hard timeout** — ``asyncio.wait_for`` wraps the API call; on timeout a
  graceful fallback phrase is returned instead of raising.
- **Fallback reply** — configurable constant; returned on timeout OR after all
  retries are exhausted so Twilio always has something to say.
- **No conversation content in production logs** — only status code / latency
  / model name are logged. Set DEBUG=true to enable full content logging.
- **Lazy client instantiation** — the OpenAI client is created once on first
  call and reused across requests (connection pool reuse).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Final

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError

from app.core.config import settings
from app.schemas.conversation import LLMMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Spoken aloud by Twilio when the AI cannot respond in time.
FALLBACK_REPLY: Final[str] = (
    "I'm sorry, I didn't catch that. Could you please repeat yourself?"
)

# Timeout for a single API attempt (seconds).
_API_TIMEOUT: Final[float] = 8.0

# Maximum number of *retry* attempts after the first failure.
_MAX_RETRIES: Final[int] = 2

# Base backoff in seconds — doubles each retry, plus random jitter.
_BACKOFF_BASE: Final[float] = 1.0

# System prompt — concise, natural spoken language, no markdown.
# This is prepended to every conversation sent to the model.
_SYSTEM_PROMPT: Final[str] = (
    "You are a helpful phone assistant. "
    "Keep all replies short, clear, and natural — as if spoken aloud. "
    "Never use bullet points, numbered lists, headers, or any text formatting. "
    "Avoid filler phrases like 'Certainly!' or 'Of course!'. "
    "If you don't understand something, ask a simple clarifying question. "
    "Respond in plain conversational English only."
)


# ---------------------------------------------------------------------------
# Lazy-initialised client singleton
# ---------------------------------------------------------------------------

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """
    Return (and lazily create) the shared AsyncOpenAI client.

    Pointed at NVIDIA's OpenAI-compatible endpoint.  The client is created
    once on first call and reused for all subsequent requests — this enables
    HTTP connection pool reuse and avoids per-request TLS handshakes.
    """
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            # The openai SDK's built-in retry is disabled here — we manage
            # retries ourselves so we can log each attempt and apply jitter.
            max_retries=0,
            timeout=_API_TIMEOUT + 2.0,  # SDK timeout > our asyncio timeout
        )
        logger.info(
            "AI client initialised",
            extra={"base_url": settings.nvidia_base_url, "model": settings.nvidia_model},
        )
    return _client


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_messages(history: list[LLMMessage]) -> list[dict[str, str]]:
    """
    Prepend the system prompt to the conversation history.

    Returns a list of plain dicts (not Pydantic models) because the
    OpenAI SDK accepts plain dicts for the ``messages`` parameter.
    """
    return [{"role": "system", "content": _SYSTEM_PROMPT}] + [
        {"role": msg.role, "content": msg.content} for msg in history
    ]


async def _call_api_once(messages: list[dict[str, str]]) -> str:
    """
    Make a single chat-completion request.  Raises on any error.
    Wrapped by ``generate_reply`` which handles retries and timeout.
    """
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.nvidia_model,
        messages=messages,          # type: ignore[arg-type]
        temperature=0.6,
        max_tokens=150,             # keep replies short for voice
        stream=False,
    )
    content = response.choices[0].message.content or ""
    return content.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_reply(conversation_history: list[LLMMessage]) -> str:
    """
    Generate an AI reply for the current call turn.

    Parameters
    ----------
    conversation_history:
        Ordered list of ``LLMMessage`` objects from
        ``ConversationService.get_conversation_history(call_id)``.
        May be empty (first turn) — the system prompt is always prepended.

    Returns
    -------
    str
        Plain text reply, ready to be passed to Twilio TTS.
        Never raises — returns ``FALLBACK_REPLY`` on any unrecoverable error.

    Behaviour
    ---------
    1. Attempt the API call with a hard ``_API_TIMEOUT`` second deadline.
    2. On ``asyncio.TimeoutError``, ``RateLimitError``, or ``APIConnectionError``
       wait ``_BACKOFF_BASE * 2**attempt`` seconds (with ±20 % jitter) and retry.
    3. After ``_MAX_RETRIES`` exhausted, or on a non-retryable ``APIStatusError``
       (4xx client errors), return ``FALLBACK_REPLY`` immediately.
    4. Log status + latency at INFO level always; log full content at DEBUG level.
    """
    messages = _build_messages(conversation_history)
    turn_count = len(conversation_history)

    for attempt in range(_MAX_RETRIES + 1):
        t_start = time.perf_counter()
        try:
            reply = await asyncio.wait_for(
                _call_api_once(messages),
                timeout=_API_TIMEOUT,
            )
            latency_ms = int((time.perf_counter() - t_start) * 1000)

            logger.info(
                "AI reply generated",
                extra={
                    "model": settings.nvidia_model,
                    "turn_count": turn_count,
                    "attempt": attempt + 1,
                    "latency_ms": latency_ms,
                    "reply_chars": len(reply),
                },
            )
            if settings.debug:
                logger.debug("AI reply content: %r", reply)

            return reply

        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - t_start) * 1000)
            logger.warning(
                "AI API timeout",
                extra={
                    "attempt": attempt + 1,
                    "latency_ms": latency_ms,
                    "timeout_s": _API_TIMEOUT,
                },
            )

        except RateLimitError as exc:
            logger.warning(
                "AI API rate limited",
                extra={"attempt": attempt + 1, "status": exc.status_code},
            )

        except APIConnectionError as exc:
            logger.warning(
                "AI API connection error",
                extra={"attempt": attempt + 1, "error": str(exc)},
            )

        except APIStatusError as exc:
            # 4xx client errors are not retryable (bad request, auth failure, etc.)
            logger.error(
                "AI API client error — not retrying",
                extra={"status": exc.status_code, "error": str(exc.message)},
            )
            return FALLBACK_REPLY

        except Exception as exc:  # noqa: BLE001 — last resort catch
            logger.exception("Unexpected AI service error: %s", exc)
            return FALLBACK_REPLY

        # --- Exponential backoff with ±20% jitter ---
        if attempt < _MAX_RETRIES:
            import random
            base_wait = _BACKOFF_BASE * (2 ** attempt)
            jitter = base_wait * random.uniform(-0.2, 0.2)
            wait = max(0.1, base_wait + jitter)
            logger.debug("Retrying AI call in %.2fs (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
            await asyncio.sleep(wait)

    # All retries exhausted
    logger.error(
        "AI reply generation failed after %d attempts — using fallback",
        _MAX_RETRIES + 1,
    )
    return FALLBACK_REPLY
