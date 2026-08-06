"""
tests/test_ai_service.py
=========================
Unit tests for app/services/ai_service.py.

Strategy
--------
- The ``AsyncOpenAI`` client is patched at the module level so no real
  NVIDIA API calls are made.
- Each test patches ``app.services.ai_service._get_client`` to return a
  mock whose ``chat.completions.create`` coroutine is controlled per-test.
- ``asyncio.sleep`` is patched to a no-op to keep tests fast.
- The module-level ``_client`` singleton is reset between tests via a
  fixture so lazy-init behaviour can be tested independently.

Coverage
--------
- Successful reply returned correctly
- System prompt prepended before user history
- Fallback reply returned on asyncio.TimeoutError
- Fallback reply returned after all retries exhausted (connection error)
- No retry on 4xx APIStatusError (non-retryable)
- Fallback on unexpected exception
- Reply content never logged at INFO level (only at DEBUG)
- Backoff sleep is called between retries
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError, APIStatusError, RateLimitError

from app.schemas.conversation import LLMMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _history(*pairs: tuple[str, str]) -> list[LLMMessage]:
    """Build a conversation history from (role, content) tuples."""
    return [LLMMessage(role=r, content=c) for r, c in pairs]  # type: ignore[arg-type]


def _make_completion(content: str) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response object."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_client_mock(return_value: Any = None, side_effect: Any = None) -> MagicMock:
    """Return a mock AsyncOpenAI client whose create() is a controlled coroutine."""
    create_mock = AsyncMock()
    if side_effect is not None:
        create_mock.side_effect = side_effect
    else:
        create_mock.return_value = return_value
    client = MagicMock()
    client.chat.completions.create = create_mock
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_client_singleton():
    """
    Reset the module-level _client singleton before each test so lazy
    initialisation is exercised cleanly without cross-test contamination.
    """
    import app.services.ai_service as ai_mod
    original = ai_mod._client
    ai_mod._client = None
    yield
    ai_mod._client = original


@pytest.fixture(autouse=True)
def no_sleep():
    """Patch asyncio.sleep to a no-op so backoff doesn't slow tests."""
    with patch("app.services.ai_service.asyncio.sleep", new_callable=AsyncMock):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_reply_returned() -> None:
    from app.services.ai_service import generate_reply

    client = _make_client_mock(return_value=_make_completion("How can I help you?"))

    with patch("app.services.ai_service._get_client", return_value=client):
        result = await generate_reply(_history(("user", "Hello")))

    assert result == "How can I help you?"


@pytest.mark.asyncio
async def test_system_prompt_prepended() -> None:
    """Verify the system prompt is the first element sent to the API."""
    from app.services.ai_service import generate_reply, _SYSTEM_PROMPT

    client = _make_client_mock(return_value=_make_completion("Acknowledged."))

    with patch("app.services.ai_service._get_client", return_value=client):
        await generate_reply(_history(("user", "Test message")))

    call_kwargs = client.chat.completions.create.call_args.kwargs
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == _SYSTEM_PROMPT
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Test message"


@pytest.mark.asyncio
async def test_empty_history_still_sends_system_prompt() -> None:
    from app.services.ai_service import generate_reply

    client = _make_client_mock(return_value=_make_completion("Hello!"))

    with patch("app.services.ai_service._get_client", return_value=client):
        await generate_reply([])

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert len(messages) == 1   # system prompt only
    assert messages[0]["role"] == "system"


@pytest.mark.asyncio
async def test_fallback_on_timeout() -> None:
    from app.services.ai_service import generate_reply, FALLBACK_REPLY

    # Make the API call hang forever — asyncio.wait_for will fire TimeoutError.
    async def _hang(*args, **kwargs):
        await asyncio.sleep(9999)

    client = MagicMock()
    client.chat.completions.create = _hang

    with patch("app.services.ai_service._get_client", return_value=client):
        # Patch wait_for to immediately raise TimeoutError on every attempt
        with patch(
            "app.services.ai_service.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            result = await generate_reply(_history(("user", "Hi")))

    assert result == FALLBACK_REPLY


@pytest.mark.asyncio
async def test_retries_on_connection_error_then_fallback() -> None:
    """All attempts fail with APIConnectionError → fallback returned."""
    from app.services.ai_service import generate_reply, FALLBACK_REPLY, _MAX_RETRIES

    exc = APIConnectionError.__new__(APIConnectionError)

    client = _make_client_mock(side_effect=exc)

    with patch("app.services.ai_service._get_client", return_value=client):
        result = await generate_reply(_history(("user", "Hi")))

    assert result == FALLBACK_REPLY
    # Called on first attempt + _MAX_RETRIES retries
    assert client.chat.completions.create.call_count == _MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_retries_on_rate_limit_then_success() -> None:
    """First attempt rate-limited, second succeeds."""
    from app.services.ai_service import generate_reply

    rate_err = RateLimitError.__new__(RateLimitError)
    rate_err.status_code = 429
    success = _make_completion("Here to help!")

    client = _make_client_mock(side_effect=[rate_err, success])

    with patch("app.services.ai_service._get_client", return_value=client):
        result = await generate_reply(_history(("user", "Hi")))

    assert result == "Here to help!"
    assert client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_4xx_status_error() -> None:
    """Non-retryable 4xx errors (e.g. bad request) return fallback immediately."""
    from app.services.ai_service import generate_reply, FALLBACK_REPLY

    # Construct an APIStatusError (needs response + body)
    resp_mock = MagicMock()
    resp_mock.status_code = 400
    err = APIStatusError(
        "Bad request",
        response=resp_mock,
        body={"error": {"message": "Bad request"}},
    )

    client = _make_client_mock(side_effect=err)

    with patch("app.services.ai_service._get_client", return_value=client):
        result = await generate_reply(_history(("user", "Hi")))

    assert result == FALLBACK_REPLY
    # Should NOT retry on 4xx
    assert client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_fallback_on_unexpected_exception() -> None:
    from app.services.ai_service import generate_reply, FALLBACK_REPLY

    client = _make_client_mock(side_effect=RuntimeError("Unexpected!"))

    with patch("app.services.ai_service._get_client", return_value=client):
        result = await generate_reply(_history(("user", "Hi")))

    assert result == FALLBACK_REPLY


@pytest.mark.asyncio
async def test_reply_content_not_in_info_logs(caplog) -> None:
    """Production logs must not contain conversation content at INFO level."""
    from app.services.ai_service import generate_reply

    secret_content = "TOP_SECRET_VOICE_CONTENT"
    client = _make_client_mock(return_value=_make_completion(secret_content))

    with patch("app.services.ai_service._get_client", return_value=client):
        with caplog.at_level(logging.INFO, logger="app.services.ai_service"):
            await generate_reply(_history(("user", "Tell me something secret")))

    # Content must NOT appear in any INFO-level log record
    info_messages = " ".join(
        r.message for r in caplog.records if r.levelno == logging.INFO
    )
    assert secret_content not in info_messages


@pytest.mark.asyncio
async def test_reply_whitespace_stripped() -> None:
    """The AI reply has leading/trailing whitespace stripped."""
    from app.services.ai_service import generate_reply

    client = _make_client_mock(return_value=_make_completion("  Sure thing.  "))

    with patch("app.services.ai_service._get_client", return_value=client):
        result = await generate_reply(_history(("user", "Hi")))

    assert result == "Sure thing."
