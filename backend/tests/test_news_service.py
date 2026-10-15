"""
tests/test_news_service.py
==========================
Unit tests for app/services/news_service.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from app.services.news_service import NewsArticle, NewsService


@pytest.fixture
def news_svc() -> NewsService:
    return NewsService()


@pytest.mark.asyncio
async def test_news_not_configured_returns_empty(news_svc: NewsService) -> None:
    with patch("app.services.news_service.settings.news_api_key", ""):
        assert not news_svc.is_configured()
        articles = await news_svc.get_top_headlines()
        assert articles == []
        search_res = await news_svc.search_news("technology")
        assert search_res == []


@pytest.mark.asyncio
async def test_get_top_headlines_success(news_svc: NewsService) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "articles": [
            {
                "title": "SpaceX launches new satellite",
                "description": "A successful mission to orbit.",
                "source": {"name": "Reuters"},
                "publishedAt": "2026-10-14T10:00:00Z",
                "url": "https://example.com/spacex",
            },
            {
                "title": "[Removed]",
                "description": "",
                "source": {"name": "None"},
            },
        ],
    }

    with patch("app.services.news_service.settings.news_api_key", "test-news-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        articles = await news_svc.get_top_headlines(country="in", max_results=2)

    assert len(articles) == 1  # [Removed] was filtered out
    assert articles[0].title == "SpaceX launches new satellite"
    assert articles[0].source == "Reuters"
    assert articles[0].description == "A successful mission to orbit."


@pytest.mark.asyncio
async def test_search_news_success(news_svc: NewsService) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "articles": [
            {
                "title": "Stock market hits record high",
                "description": "Sensex gains 500 points.",
                "source": {"name": "Economic Times"},
                "publishedAt": "2026-10-14T09:00:00Z",
                "url": "https://example.com/stocks",
            }
        ],
    }

    with patch("app.services.news_service.settings.news_api_key", "test-news-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        articles = await news_svc.search_news("economy")

    assert len(articles) == 1
    assert "Stock market" in articles[0].title


@pytest.mark.asyncio
async def test_news_cache_avoids_repeated_requests(news_svc: NewsService) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "articles": [{"title": "Cached News", "source": {"name": "BBC"}}],
    }

    with patch("app.services.news_service.settings.news_api_key", "test-news-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
        # First call fetches from API
        res1 = await news_svc.get_top_headlines()
        # Second call hits cache
        res2 = await news_svc.get_top_headlines()

    assert len(res1) == 1
    assert len(res2) == 1
    assert mock_get.call_count == 1  # Only one HTTP GET was made


def test_format_news_for_llm(news_svc: NewsService) -> None:
    articles = [
        NewsArticle(
            title="AI breakthrough announced",
            description="New model achieves human parity.",
            source="TechCrunch",
        ),
        NewsArticle(
            title="Weather update: Sunny today",
            description="",
            source="Meteorology Dept",
        ),
    ]
    formatted = news_svc.format_news_for_llm(articles)
    assert "CURRENT NEWS SUMMARY" in formatted
    assert "1. AI breakthrough announced (Source: TechCrunch) - New model achieves human parity." in formatted
    assert "2. Weather update: Sunny today (Source: Meteorology Dept)" in formatted


def test_format_news_for_llm_with_publication_and_url(news_svc: NewsService) -> None:
    articles = [
        NewsArticle(
            title="Markets Rally",
            description="Sensex surges 800 points.",
            source="Reuters",
            published_at="2026-10-14T09:30:00Z",
            url="https://news.example.com/markets",
        )
    ]
    formatted = news_svc.format_news_for_llm(articles)
    assert "CURRENT NEWS SUMMARY" in formatted
    assert "Markets Rally" in formatted
    assert "Source: Reuters" in formatted
    assert "Published: 2026-10-14T09:30:00Z" in formatted
    assert "URL: https://news.example.com/markets" in formatted


@pytest.mark.asyncio
async def test_india_headlines_routes_to_everything(news_svc: NewsService) -> None:
    """Verify that requesting India headlines routes to /everything with q=India."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "articles": [
            {
                "title": "Major policy update in New Delhi",
                "source": {"name": "The Hindu"},
                "publishedAt": "2026-10-14T08:00:00Z",
                "url": "https://example.com/delhi",
            }
        ],
    }

    with patch("app.services.news_service.settings.news_api_key", "test-news-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
        articles = await news_svc.get_top_headlines(country="in")

    assert len(articles) == 1
    assert articles[0].title == "Major policy update in New Delhi"
    # Verify it hit /everything with q=India
    called_url = mock_get.call_args[0][0]
    called_params = mock_get.call_args[1]["params"]
    assert "/everything" in called_url
    assert called_params["q"] == "India"
    assert called_params["sortBy"] == "publishedAt"
    assert called_params["language"] == "en"


@pytest.mark.asyncio
async def test_fetch_news_401_unauthorized_returns_empty(news_svc: NewsService) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("app.services.news_service.settings.news_api_key", "invalid-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        articles = await news_svc.search_news("cricket")
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_news_429_rate_limited_returns_empty(news_svc: NewsService) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    with patch("app.services.news_service.settings.news_api_key", "test-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        articles = await news_svc.search_news("economy")
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_news_426_account_restriction_returns_empty(news_svc: NewsService) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 426
    with patch("app.services.news_service.settings.news_api_key", "test-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        articles = await news_svc.search_news("sports")
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_news_status_error_in_body_returns_empty(news_svc: NewsService) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "error",
        "code": "parameterInvalid",
        "message": "The query parameter was not accepted.",
    }
    with patch("app.services.news_service.settings.news_api_key", "test-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        articles = await news_svc.search_news("test")
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_news_timeout_returns_empty(news_svc: NewsService) -> None:
    with patch("app.services.news_service.settings.news_api_key", "test-key"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=httpx.TimeoutException("Read timed out")):
        articles = await news_svc.search_news("technology")
    assert articles == []
