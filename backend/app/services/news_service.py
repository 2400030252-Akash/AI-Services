"""
app/services/news_service.py
============================
Live news retrieval service using NewsAPI.org.

Provides current news headlines and topic-specific search for the
conversational AI phone assistant.

Public surface
--------------
    NewsArticle (Pydantic model)
    NewsService
        .get_top_headlines(category, country, max_results) -> list[NewsArticle]
        .search_news(query, max_results) -> list[NewsArticle]
        .format_news_for_llm(articles) -> str

Design decisions
----------------
- **Async HTTP** — uses ``httpx.AsyncClient`` with strict 5-second timeout.
- **In-memory TTL cache** — caches responses for 5 minutes (300s) to avoid
  hitting rate limits and reduce latency during live voice calls.
- **Graceful degradation** — if NEWS_API_KEY is missing or invalid, logs a clear
  guidance message and returns empty results without crashing.
- **Voice-optimized formatting** — ``format_news_for_llm`` extracts key facts
  in plain text without markdown markup, keeping speech natural.
"""
from __future__ import annotations

import logging
import time
from typing import Final
from pydantic import BaseModel, Field
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cache duration in seconds (5 minutes)
_CACHE_TTL: Final[float] = 300.0

# Request timeout in seconds
_REQUEST_TIMEOUT: Final[float] = 5.0


class NewsArticle(BaseModel):
    """Structured representation of a single news item."""
    title: str
    description: str = ""
    source: str = ""
    published_at: str = ""
    url: str = ""


class NewsService:
    """
    Service for retrieving and formatting live news from NewsAPI.org.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[NewsArticle]]] = {}

    def is_configured(self) -> bool:
        """Return True if NEWS_API_KEY is set in environment."""
        return bool(settings.news_api_key and settings.news_api_key.strip())

    async def get_top_headlines(
        self,
        category: str = "general",
        country: str | None = None,
        max_results: int = 4,
    ) -> list[NewsArticle]:
        """
        Fetch current top headlines from NewsAPI.org.

        For countries where /top-headlines has no active feeds (such as India, where NewsAPI's
        curated /top-headlines feeds are stale or yield 0 results), this method seamlessly falls
        back to /everything with targeted queries (language=en, sortBy=publishedAt) to guarantee
        that real, current news articles are always returned.
        """
        if not self.is_configured():
            logger.warning(
                "NEWS_API_KEY is not configured in backend/.env. "
                "Register for a free key at https://newsapi.org and set NEWS_API_KEY to enable live news."
            )
            return []

        country_code = (country or settings.news_country or "in").strip().lower()
        cache_key = f"headlines:{country_code}:{category}:{max_results}"

        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        articles: list[NewsArticle] = []

        # NewsAPI /top-headlines?country=in has zero active feeds and returns 0 results.
        # Directly use /everything for fresh, real-time Indian news headlines.
        if country_code == "in":
            query = "India" if category == "general" else f"India {category}"
            logger.info("Fetching real-time India headlines via NewsAPI /everything (query: %s)", query)
            articles = await self._fetch_everything(query=query, max_results=max_results)
        else:
            # For other countries, attempt /top-headlines first
            url = f"{settings.news_api_base_url.rstrip('/')}/top-headlines"
            params: dict[str, str | int] = {
                "country": country_code,
                "category": category,
                "pageSize": max_results,
                "apiKey": settings.news_api_key,
            }
            articles = await self._fetch_news(url, params)
            # If /top-headlines returned 0 results, fall back to /everything
            if not articles:
                fallback_query = category if category != "general" else f"{country_code} news"
                logger.info(
                    "Top headlines returned 0 results for country '%s'; falling back to /everything (query: %s)",
                    country_code,
                    fallback_query,
                )
                articles = await self._fetch_everything(query=fallback_query, max_results=max_results)

        self._set_cache(cache_key, articles)
        return articles

    async def search_news(
        self,
        query: str,
        max_results: int = 4,
    ) -> list[NewsArticle]:
        """
        Search recent news articles matching a keyword or topic via /everything.

        Parameters
        ----------
        query:
            Search phrase, country, or topic keyword.
        max_results:
            Maximum articles to return.
        """
        if not self.is_configured():
            logger.warning(
                "NEWS_API_KEY is not configured in backend/.env. "
                "Register at https://newsapi.org and set NEWS_API_KEY to enable news search."
            )
            return []

        cleaned_query = query.strip()
        if not cleaned_query:
            return await self.get_top_headlines(max_results=max_results)

        cache_key = f"search:{cleaned_query.lower()}:{max_results}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        articles = await self._fetch_everything(query=cleaned_query, max_results=max_results)
        self._set_cache(cache_key, articles)
        return articles

    async def _fetch_everything(
        self,
        query: str,
        max_results: int = 4,
    ) -> list[NewsArticle]:
        """
        Helper to fetch articles via /everything with standard voice parameters:
        language=en, sortBy=publishedAt, pageSize=max_results.
        """
        url = f"{settings.news_api_base_url.rstrip('/')}/everything"
        params: dict[str, str | int] = {
            "q": query,
            "sortBy": "publishedAt",
            "pageSize": max_results,
            "language": "en",
            "apiKey": settings.news_api_key,
        }
        return await self._fetch_news(url, params)

    def format_news_for_llm(self, articles: list[NewsArticle]) -> str:
        """
        Format a list of news articles into a plain-text prompt injection context.
        Provides title, source, publication date, URL, and summary for accurate LLM grounding.
        """
        if not articles:
            return ""

        lines = ["CURRENT NEWS SUMMARY (Use this factual information to answer the caller):"]
        for idx, art in enumerate(articles, start=1):
            source_tag = f" (Source: {art.source})" if art.source else ""
            desc = f" - {art.description}" if art.description else ""
            extra_details: list[str] = []
            if art.published_at:
                extra_details.append(f"Published: {art.published_at}")
            if art.url:
                extra_details.append(f"URL: {art.url}")
            extra_str = f" [{', '.join(extra_details)}]" if extra_details else ""
            lines.append(f"{idx}. {art.title}{source_tag}{desc}{extra_str}")

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Internal HTTP & Cache Helpers
    # -----------------------------------------------------------------------

    def _get_from_cache(self, key: str) -> list[NewsArticle] | None:
        if key in self._cache:
            ts, items = self._cache[key]
            if time.monotonic() - ts < _CACHE_TTL:
                return items
            del self._cache[key]
        return None

    def _set_cache(self, key: str, items: list[NewsArticle]) -> None:
        self._cache[key] = (time.monotonic(), items)

    async def _fetch_news(self, url: str, params: dict[str, str | int]) -> list[NewsArticle]:
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.get(url, params=params)

                # Explicit error handling for common NewsAPI status codes
                if resp.status_code == 401:
                    logger.error("NewsAPI returned 401 Unauthorized — verify NEWS_API_KEY in backend/.env")
                    return []
                elif resp.status_code == 429:
                    logger.warning("NewsAPI rate limit reached (429 Too Many Requests) — daily request cap may be exceeded")
                    return []
                elif resp.status_code == 426:
                    logger.warning("NewsAPI account restriction (426 Upgrade Required) — developer plan constraint")
                    return []
                elif resp.status_code >= 400:
                    logger.warning("NewsAPI request failed with HTTP status %d", resp.status_code)
                    return []

                data = resp.json()

            # Handle JSON body errors (e.g. status == 'error')
            if isinstance(data, dict) and data.get("status") == "error":
                code = data.get("code", "unknown")
                msg = data.get("message", "unknown error")
                logger.warning("NewsAPI reported error status: code=%s, message=%s", code, msg)
                return []

            articles: list[NewsArticle] = []
            for raw in data.get("articles", []) if isinstance(data, dict) else []:
                title = raw.get("title") or ""
                # Skip removed/deleted articles common on NewsAPI
                if "[Removed]" in title or not title.strip():
                    continue

                source_name = (raw.get("source") or {}).get("name") or ""
                articles.append(
                    NewsArticle(
                        title=title.strip(),
                        description=(raw.get("description") or "").strip(),
                        source=source_name.strip(),
                        published_at=(raw.get("publishedAt") or "").strip(),
                        url=(raw.get("url") or "").strip(),
                    )
                )
            return articles

        except httpx.TimeoutException:
            logger.warning("NewsAPI request timed out after %.1fs", _REQUEST_TIMEOUT)
            return []
        except httpx.RequestError as exc:
            logger.warning("NewsAPI network connection error: %s", type(exc).__name__)
            return []
        except Exception as exc:
            logger.warning("NewsAPI unexpected error: %s", type(exc).__name__)
            return []


# Global singleton
news_service = NewsService()
