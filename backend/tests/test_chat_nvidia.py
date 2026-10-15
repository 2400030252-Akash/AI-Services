"""
tests/test_chat_nvidia.py
=========================
Unit tests for ChatNVIDIA integration with moonshotai/kimi-k3 in ai_service.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import settings
from app.schemas.conversation import LLMMessage
from app.services.ai_service import _get_client, _call_api_once, generate_reply


def test_chat_nvidia_client_initialization():
    """Verify that _get_client creates ChatNVIDIA targeting moonshotai/kimi-k3."""
    with patch("app.services.ai_service._client", None), \
         patch.object(settings, "nvidia_model", "moonshotai/kimi-k3"), \
         patch.object(settings, "nvidia_api_key", "nvapi-test-key-12345"):
        client = _get_client()

    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    assert isinstance(client, ChatNVIDIA)
    assert client.model == "moonshotai/kimi-k3"


@pytest.mark.asyncio
async def test_call_api_once_uses_ainvoke():
    """Verify that _call_api_once calls ainvoke on ChatNVIDIA."""
    mock_ai_message = MagicMock()
    mock_ai_message.content = "This is a response from moonshotai/kimi-k3."

    mock_chat_nvidia = MagicMock()
    mock_chat_nvidia.ainvoke = AsyncMock(return_value=mock_ai_message)

    messages = [{"role": "user", "content": "Hello"}]

    with patch("app.services.ai_service._get_client", return_value=mock_chat_nvidia):
        reply = await _call_api_once(messages)

    assert reply == "This is a response from moonshotai/kimi-k3."
    mock_chat_nvidia.ainvoke.assert_called_once_with(messages)


@pytest.mark.asyncio
async def test_generate_reply_with_chat_nvidia_and_news():
    """Verify that generate_reply works with ChatNVIDIA and incorporates news context."""
    from app.services.news_service import NewsArticle

    mock_ai_message = MagicMock()
    mock_ai_message.content = "Today's top headline is about renewable energy."

    mock_chat_nvidia = MagicMock()
    mock_chat_nvidia.ainvoke = AsyncMock(return_value=mock_ai_message)

    mock_articles = [
        NewsArticle(
            title="Solar energy hits record high",
            description="Major surge in clean power.",
            source="Reuters",
        )
    ]

    history = [LLMMessage(role="user", content="What is the latest news today?")]

    with patch("app.services.ai_service._get_client", return_value=mock_chat_nvidia), \
         patch("app.services.ai_service.news_service.is_configured", return_value=True), \
         patch("app.services.ai_service.news_service.get_top_headlines", new_callable=AsyncMock, return_value=mock_articles):
        reply = await generate_reply(history)

    assert reply == "Today's top headline is about renewable energy."
    mock_chat_nvidia.ainvoke.assert_called_once()
    called_messages = mock_chat_nvidia.ainvoke.call_args[0][0]
    # Verify news context is present in the messages passed to ChatNVIDIA
    assert any("CURRENT NEWS SUMMARY" in m["content"] for m in called_messages if m["role"] == "system")
    assert any("Solar energy hits record high" in m["content"] for m in called_messages if m["role"] == "system")
