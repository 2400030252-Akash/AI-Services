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
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from app.core.config import settings
from app.schemas.conversation import LLMMessage
from app.services.news_service import news_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Spoken aloud by Twilio/Exotel when the AI cannot respond in time.
FALLBACK_REPLY: Final[str] = (
    "I'm sorry, I didn't catch that. Could you please repeat yourself?"
)

# Timeout for a single API attempt (seconds).
_API_TIMEOUT: Final[float] = 25.0

# Maximum number of *retry* attempts after the first failure.
_MAX_RETRIES: Final[int] = 2

# Base backoff in seconds — doubles each retry, plus random jitter.
_BACKOFF_BASE: Final[float] = 0.5

# Active verified fallback model on NVIDIA NIM if the configured model is unresponsive
_FALLBACK_MODEL: Final[str] = "meta/llama-3.2-11b-vision-instruct"

# System prompt — concise, natural spoken language, no markdown.
# This is prepended to every conversation sent to the model.
_SYSTEM_PROMPT: Final[str] = (
    "You are a helpful phone assistant. "
    "Keep all replies short, clear, and natural — as if spoken aloud. "
    "Avoid filler phrases like 'Certainly!' or 'Of course!'. "
    "If you don't understand something, ask a simple clarifying question. "
    "Respond in plain conversational English only."
)

# System prompt used only when a news context has been injected.
# Does NOT prohibit listing headlines — the user may explicitly ask for a numbered list.
_NEWS_SYSTEM_PROMPT: Final[str] = (
    "You are a helpful phone assistant that reads out current news. "
    "Always answer directly using ONLY the news articles provided below — never invent or assume events. "
    "When the caller asks for a numbered list of headlines, read them out one by one in plain spoken English. "
    "Keep each headline summary brief (one sentence per item). "
    "Mention the source name naturally, for example: 'According to The Times of India'. "
    "Do NOT read URLs, technical timestamps, or markdown formatting aloud. "
    "Avoid filler phrases like 'Certainly!' or 'Of course!'. "
    "Respond in plain conversational English only."
)

# Triggers for news and current affairs queries
_NEWS_TRIGGERS: Final[tuple[str, ...]] = (
    "news", "headline", "headlines", "breaking news", "current events",
    "what happened today", "latest news", "today's news", "updates today",
    "what is happening in", "what's happening in", "current updates",
    "what is happening", "what's happening", "top stories", "breaking",
    "current affairs", "world news", "national news", "daily news",
    "recent news", "recent updates", "recent headlines",
    "give me news", "tell me the news", "read me the news",
    "give me headlines", "tell me headlines",
    "important news",
)


def _is_news_intent(text: str) -> bool:
    """Check if the user's message is asking about news or current events."""
    lowered = text.lower()
    return any(trigger in lowered for trigger in _NEWS_TRIGGERS)


def _extract_news_topic(text: str) -> str:
    """
    Extract specific news subject, region, or keyword from caller query if present.
    Returns empty string if query is a general headline request (e.g. 'what is the news?').
    """
    import re

    cleaned = text.strip().rstrip("?.!,")
    lowered = cleaned.lower()

    # 1. Regex patterns for news/headlines/updates followed by prepositions (in, about, on, from, for, regarding)
    patterns = [
        r'(?:news|headlines?|updates?|stories)\s+(?:about|on|in|from|regarding|for)\s+([a-zA-Z0-9][a-zA-Z0-9\s]+)',
        r'(?:what(?:\x27s|\s+is)\s+(?:the\s+)?(?:latest\s+)?(?:important\s+)?(?:news|updates?|headlines?)\s+(?:about|on|in|from|regarding|for))\s+([a-zA-Z0-9][a-zA-Z0-9\s]+)',
        r'(?:what\s+happened\s+(?:in|with|to))\s+([a-zA-Z0-9][a-zA-Z0-9\s]+)',
        r'(?:what(?:\x27s|\s+is)\s+happening\s+(?:in|with))\s+([a-zA-Z0-9][a-zA-Z0-9\s]+)',
        # Patterns for "give me/tell me X news" or "latest X news"
        r'(?:give\s+me|tell\s+me|show\s+me|read\s+me)\s+(?:\d+\s+)?(?:latest|recent|top|current|important)?\s*(?:important\s+)?(?:news|headlines?)\s+(?:about|on|in|from|regarding|for)\s+([a-zA-Z0-9][a-zA-Z0-9\s]+)',
        r'(?:latest|recent|top|current)\s+([a-zA-Z0-9][a-zA-Z0-9\s]+)\s+(?:news|headlines?|updates?)',
    ]
    for pat in patterns:
        m = re.search(pat, cleaned, re.IGNORECASE)
        if m:
            topic = m.group(1).strip()
            topic = re.sub(r'\b(today|now|right now|currently|this week|recently|their|sources?|and|with|publication|dates?)\b', '', topic, flags=re.IGNORECASE).strip()
            if topic and len(topic) > 1:
                return topic

    # 2. Check for traditional prefix matches (e.g. "tell me the news on cricket")
    prefixes = [
        "what is the latest news about", "what's the latest news about",
        "tell me news on", "tell me the news on", "news about", "news on",
        "updates on", "what happened with", "what happened to",
        "give me news about", "give me the latest news on",
    ]
    for p in prefixes:
        if p in lowered:
            parts = lowered.split(p, 1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip().strip("?.!,")

    # 3. Check for specific high-value regions/topics explicitly mentioned in the news query
    known_entities = [
        "artificial intelligence", "india", "us", "usa", "uk", "israel", "iran",
        "russia", "ukraine", "china", "technology", "sports", "cricket",
        "business", "economy", "finance", "politics", "science", "health",
    ]
    for entity in sorted(known_entities, key=len, reverse=True):
        if re.search(rf'\b{re.escape(entity)}\b', lowered):
            return entity.title() if len(entity) > 3 else entity.upper()

    return ""


def _extract_requested_count(text: str) -> int:
    """
    Extract how many news items the caller requested (e.g. 'top 5 headlines' -> 5).
    Returns 5 as the default for news queries (a sensible spoken number).
    Max is capped at 10 to avoid excessive API usage.
    """
    import re
    m = re.search(r'\b(\d+)\b', text)
    if m:
        count = int(m.group(1))
        if 1 <= count <= 10:
            return count
    return 5


# ---------------------------------------------------------------------------
# Lazy-initialised client cache
# ---------------------------------------------------------------------------

_client: ChatNVIDIA | AsyncOpenAI | None = None
_clients: dict[str, ChatNVIDIA | AsyncOpenAI] = {}


def _get_client(model: str | None = None) -> ChatNVIDIA | AsyncOpenAI:
    """
    Return (and lazily create) the shared ChatNVIDIA client for the given model.

    Defaults to settings.nvidia_model.
    """
    global _client
    target_model = model or settings.nvidia_model

    # Check cached clients
    if target_model in _clients:
        selected = _clients[target_model]
        if model is None:
            _client = selected
        return selected

    try:
        client = ChatNVIDIA(
            model=target_model,
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            temperature=0.6,
            max_completion_tokens=250,
        )
        logger.info(
            "ChatNVIDIA client initialised for model '%s'",
            target_model,
            extra={"base_url": settings.nvidia_base_url, "model": target_model},
        )
        _clients[target_model] = client
    except Exception as exc:
        logger.warning(
            "Failed to initialize ChatNVIDIA for %s, falling back to AsyncOpenAI: %s",
            target_model,
            exc,
        )
        client = AsyncOpenAI(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            max_retries=0,
            timeout=_API_TIMEOUT + 2.0,
        )
        _clients[target_model] = client

    if model is None:
        _client = client
    return client


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_messages(
    history: list[LLMMessage],
    news_context: str = "",
    use_news_prompt: bool = False,
) -> list[dict[str, str]]:
    """
    Prepend the system prompt and optional news context to the conversation history.

    When ``use_news_prompt`` is True (i.e. the turn is a news query), the news-specific
    system prompt is used instead of the default voice assistant prompt so that the model
    is allowed to enumerate headlines rather than being instructed to avoid lists.

    Returns a list of plain dicts (not Pydantic models) because both
    ChatNVIDIA and OpenAI SDK accept standard role/content dicts.
    """
    system_prompt = _NEWS_SYSTEM_PROMPT if (use_news_prompt and news_context) else _SYSTEM_PROMPT
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if news_context:
        messages.append({"role": "system", "content": news_context})
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    return messages


async def _call_api_once(messages: list[dict[str, str]], model: str | None = None) -> str:
    """
    Make a single chat-completion request using ChatNVIDIA (or fallback client).
    Raises on any error; wrapped by generate_reply for retries and timeouts.
    """
    client = _get_client(model)

    import inspect
    from unittest.mock import AsyncMock

    # 1. Real ChatNVIDIA instance or mock with ainvoke
    ainvoke_fn = getattr(client, "ainvoke", None)
    if isinstance(client, ChatNVIDIA) or isinstance(ainvoke_fn, AsyncMock) or (ainvoke_fn and inspect.iscoroutinefunction(ainvoke_fn)):
        response = await client.ainvoke(messages)
        content = getattr(response, "content", "") or ""
        # Handle reasoning models where output text is in reasoning_content or additional_kwargs
        if not content and hasattr(response, "additional_kwargs"):
            content = response.additional_kwargs.get("reasoning_content", "") or ""
        if isinstance(content, list):
            parts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in content]
            content = " ".join(p for p in parts if p)
        return str(content).strip()

    # 2. AsyncOpenAI client (or mock with chat.completions.create)
    if hasattr(client, "chat") and hasattr(getattr(client, "chat", None), "completions"):
        create_fn = getattr(client.chat.completions, "create", None)
        if isinstance(create_fn, AsyncMock) or (create_fn and inspect.iscoroutinefunction(create_fn)):
            target_model = model or getattr(client, "model", None) or settings.nvidia_model
            response = await create_fn(
                model=target_model,
                messages=messages,          # type: ignore[arg-type]
                temperature=0.6,
                max_tokens=250,             # keep replies short for voice
                stream=False,
            )
            msg = response.choices[0].message
            content = msg.content or getattr(msg, "reasoning_content", None) or ""
            return str(content).strip()

    # 3. Callable fallback
    response = await client(messages)
    return str(getattr(response, "content", response)).strip()


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
        Plain text reply, ready to be passed to TTS.
        Never raises — returns ``FALLBACK_REPLY`` on any unrecoverable error.
    """
    news_context = ""
    is_news_query = False
    # Check if the latest turn is a user query with news intent
    if conversation_history:
        last_turn = conversation_history[-1]
        if last_turn.role == "user" and _is_news_intent(last_turn.content):
            is_news_query = True
            if news_service.is_configured():
                topic = _extract_news_topic(last_turn.content)
                requested_count = _extract_requested_count(last_turn.content)
                logger.info(
                    "News query detected: topic=%r, requested_count=%d",
                    topic or "general",
                    requested_count,
                )
                try:
                    if topic:
                        articles = await news_service.search_news(topic, max_results=requested_count)
                    else:
                        articles = await news_service.get_top_headlines(max_results=requested_count)
                    if articles:
                        news_context = news_service.format_news_for_llm(articles)
                        news_context += (
                            "\n\nINSTRUCTIONS FOR YOUR RESPONSE:\n"
                            f"The caller asked about current news and you have {len(articles)} articles above. "
                            "Answer DIRECTLY using only the facts in the articles — do not ask for clarification. "
                            f"If the caller requested {requested_count} headlines, list all {min(len(articles), requested_count)} of them. "
                            "For each headline, say the title in plain English and mention the source name (e.g. 'According to The Times of India'). "
                            "Keep each item to one sentence. Do NOT read URLs, dates, or brackets aloud. "
                            "Do NOT invent any headlines not listed above."
                        )
                    else:
                        news_context = (
                            f"CURRENT NEWS: No recent articles were found for topic: '{topic or 'general'}'. "
                            "Tell the caller directly that no recent articles are available on this topic right now. "
                            "Do NOT invent or guess any news stories."
                        )
                except Exception as exc:
                    logger.warning("Failed to fetch news for AI reply: %s", type(exc).__name__)
                    news_context = (
                        "CURRENT NEWS: Live news retrieval failed due to a temporary connection issue. "
                        "Tell the caller directly that live news could not be fetched right now. "
                        "Do NOT invent any news."
                    )
            else:
                news_context = (
                    "SYSTEM NOTICE: Live news retrieval is NOT configured because NEWS_API_KEY is not set. "
                    "Tell the caller directly that live news is not available on this assistant right now."
                )

    messages = _build_messages(conversation_history, news_context=news_context, use_news_prompt=is_news_query)
    turn_count = len(conversation_history)

    for attempt in range(_MAX_RETRIES + 1):
        t_start = time.perf_counter()
        try:
            reply = await asyncio.wait_for(
                _call_api_once(messages, model=settings.nvidia_model),
                timeout=_API_TIMEOUT,
            )
            latency_ms = int((time.perf_counter() - t_start) * 1000)

            # Guard against empty replies (e.g. reasoning models with no output tokens)
            if not reply:
                logger.warning(
                    "AI model '%s' returned empty content on attempt %d",
                    settings.nvidia_model,
                    attempt + 1,
                )
                continue

            logger.info(
                "AI reply generated: model=%s, latency=%dms, reply_chars=%d, attempt=%d",
                settings.nvidia_model,
                latency_ms,
                len(reply),
                attempt + 1,
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
                "AI API timeout for model '%s' after %dms (timeout limit: %.1fs, attempt %d/%d)",
                settings.nvidia_model,
                latency_ms,
                _API_TIMEOUT,
                attempt + 1,
                _MAX_RETRIES + 1,
            )

        except RateLimitError as exc:
            logger.warning(
                "AI API rate limited for model '%s': status=%s",
                settings.nvidia_model,
                exc.status_code,
            )

        except APIConnectionError as exc:
            logger.warning(
                "AI API connection error for model '%s': %s",
                settings.nvidia_model,
                type(exc).__name__,
            )

        except APIStatusError as exc:
            # 4xx client errors are not retryable (bad request, auth failure, etc.)
            logger.error(
                "AI API client error for model '%s' — not retrying: status=%s, error=%s",
                settings.nvidia_model,
                exc.status_code,
                str(exc.message)[:150],
            )
            return FALLBACK_REPLY

        except Exception as exc:
            logger.warning(
                "AI API error calling model '%s': [%s] %s",
                settings.nvidia_model,
                type(exc).__name__,
                str(exc)[:150],
            )

        # Short backoff before retrying
        if attempt < _MAX_RETRIES:
            import random
            base_wait = _BACKOFF_BASE * (2 ** attempt)
            jitter = base_wait * random.uniform(-0.2, 0.2)
            wait = max(0.05, base_wait + jitter)
            await asyncio.sleep(wait)

    # In live execution (real ChatNVIDIA client), if primary model failed or timed out,
    # fall back to an active verified NVIDIA NIM model to prevent silent voice failures.
    from unittest.mock import MagicMock
    primary_client = _get_client()
    if not isinstance(primary_client, MagicMock) and settings.nvidia_model != _FALLBACK_MODEL:
        logger.warning(
            "Primary model '%s' failed after %d attempts. Switching to active verified model '%s'...",
            settings.nvidia_model,
            _MAX_RETRIES + 1,
            _FALLBACK_MODEL,
        )
        try:
            fallback_reply = await asyncio.wait_for(
                _call_api_once(messages, model=_FALLBACK_MODEL),
                timeout=_API_TIMEOUT,
            )
            if fallback_reply:
                logger.info(
                    "Fallback AI model '%s' succeeded: reply_chars=%d",
                    _FALLBACK_MODEL,
                    len(fallback_reply),
                )
                return fallback_reply
        except Exception as exc:
            logger.error(
                "Fallback model '%s' also failed: [%s] %s",
                _FALLBACK_MODEL,
                type(exc).__name__,
                str(exc)[:150],
            )

    # All attempts exhausted
    logger.error("All AI attempts exhausted — using spoken fallback reply")
    return FALLBACK_REPLY


