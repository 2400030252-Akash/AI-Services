"""
tests/test_ai_service_news.py
=============================
Tests verifying that the AI service detects news queries, calls the news service,
and injects current factual information before generating conversational replies.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.schemas.conversation import LLMMessage
from app.services.ai_service import generate_reply, _is_news_intent, _extract_news_topic
from app.services.news_service import NewsArticle


def _make_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_client_mock(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_make_completion(content))
    return client


def test_is_news_intent_detection():
    assert _is_news_intent("What is the latest news?")
    assert _is_news_intent("Tell me the headlines today")
    assert _is_news_intent("Any breaking news?")
    assert _is_news_intent("What happened today in India?")
    assert not _is_news_intent("Hello, what is your name?")
    assert not _is_news_intent("Can you help me reset my password?")


def test_extract_news_topic():
    assert _extract_news_topic("tell me the news on cricket") == "cricket"
    assert _extract_news_topic("what is the latest news about elections?") == "elections"
    assert _extract_news_topic("what is the news?") == ""


@pytest.mark.asyncio
async def test_news_query_with_configured_service():
    """When NEWS_API_KEY is configured, news articles are injected into the LLM context."""
    client = _make_client_mock("The main headline today is that space exploration saw new progress.")
    sample_articles = [
        NewsArticle(
            title="Rocket successfully orbits Earth",
            description="Mission accomplished.",
            source="SpaceNews",
        )
    ]

    history = [LLMMessage(role="user", content="What is the latest news today?")]

    with patch("app.services.ai_service._get_client", return_value=client), \
         patch("app.services.ai_service.news_service.is_configured", return_value=True), \
         patch("app.services.ai_service.news_service.get_top_headlines", new_callable=AsyncMock, return_value=sample_articles):
        reply = await generate_reply(history)

    assert reply == "The main headline today is that space exploration saw new progress."
    call_args = client.chat.completions.create.call_args.kwargs
    messages = call_args["messages"]
    # Messages should include: system prompt, system news context, user turn
    assert any("CURRENT NEWS SUMMARY" in m.get("content", "") for m in messages if m["role"] == "system")
    assert any("Rocket successfully orbits Earth" in m.get("content", "") for m in messages if m["role"] == "system")


@pytest.mark.asyncio
async def test_news_query_when_unconfigured_informs_user():
    """When NEWS_API_KEY is missing, LLM receives explicit instruction to inform user politely."""
    client = _make_client_mock("Live news feeds are currently not configured on this phone system.")
    history = [LLMMessage(role="user", content="Tell me today's news headlines")]

    with patch("app.services.ai_service._get_client", return_value=client), \
         patch("app.services.ai_service.news_service.is_configured", return_value=False):
        reply = await generate_reply(history)

    assert "not configured" in reply.lower()
    call_args = client.chat.completions.create.call_args.kwargs
    messages = call_args["messages"]
    assert any("NEWS_API_KEY is not set" in m.get("content", "") for m in messages if m["role"] == "system")


def test_extract_news_topic_india_query():
    """Verify that specific queries like 'headlines in India' extract India as the topic."""
    assert _extract_news_topic("What are the latest important news headlines in India?") == "India"
    assert _extract_news_topic("What is the latest news in India?") == "India"
    assert _extract_news_topic("What is happening in artificial intelligence?") == "artificial intelligence"
    assert _extract_news_topic("What are the headlines today?") == ""


@pytest.mark.asyncio
async def test_news_query_empty_results_instructs_llm_not_to_fabricate():
    """When news service returns empty list, LLM receives explicit prompt not to fabricate news."""
    client = _make_client_mock("No recent articles were found on this topic.")
    history = [LLMMessage(role="user", content="Tell me news on rare topic")]

    with patch("app.services.ai_service._get_client", return_value=client), \
         patch("app.services.ai_service.news_service.is_configured", return_value=True), \
         patch("app.services.ai_service.news_service.search_news", new_callable=AsyncMock, return_value=[]):
        reply = await generate_reply(history)

    call_args = client.chat.completions.create.call_args.kwargs
    messages = call_args["messages"]
    assert any("No recent articles were found" in m.get("content", "") for m in messages if m["role"] == "system")
    assert any("Do NOT invent or guess any news" in m.get("content", "") for m in messages if m["role"] == "system")


@pytest.mark.asyncio
async def test_news_query_error_instructs_llm_service_unavailable():
    """When news service fails with an exception, LLM is told feeds are temporarily unavailable."""
    client = _make_client_mock("Live news feeds are temporarily unavailable.")
    history = [LLMMessage(role="user", content="What is the latest news today?")]

    with patch("app.services.ai_service._get_client", return_value=client), \
         patch("app.services.ai_service.news_service.is_configured", return_value=True), \
         patch("app.services.ai_service.news_service.get_top_headlines", new_callable=AsyncMock, side_effect=RuntimeError("Feed error")):
        reply = await generate_reply(history)

    call_args = client.chat.completions.create.call_args.kwargs
    messages = call_args["messages"]
    assert any("Live news retrieval failed" in m.get("content", "") for m in messages if m["role"] == "system")
