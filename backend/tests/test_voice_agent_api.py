"""
tests/test_voice_agent_api.py
=============================
Tests for Exotel Voice Agent Custom API integration endpoint:
    POST /api/v1/voice-agent/ask

Covers:
  - 401 Unauthorized for missing API key
  - 401 Unauthorized for invalid API key
  - 200 OK with X-API-Key header
  - 200 OK with Authorization: Bearer header
  - 422 Unprocessable Entity for missing question
  - 422 Unprocessable Entity for blank question
  - Successful response payload format {"answer": "..."}
  - Conversation history and conversation_id handling
  - Exotel parameter aliases (user_input, query, nested parameters)
  - News query handling
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from app.core.config import settings

TEST_KEY = "test-voice-agent-secret-12345"


@pytest.fixture(autouse=True)
def configure_voice_agent_key():
    """Ensure VOICE_AGENT_API_KEY is configured for tests."""
    with patch.object(settings, "voice_agent_api_key", TEST_KEY):
        yield


@pytest.mark.asyncio
async def test_ask_unauthorized_when_no_credentials(client: AsyncClient):
    response = await client.post(
        "/api/v1/voice-agent/ask",
        json={"question": "What is AI?"},
    )
    assert response.status_code == 401
    assert "Missing API key" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_ask_unauthorized_when_invalid_key(client: AsyncClient):
    response = await client.post(
        "/api/v1/voice-agent/ask",
        headers={"X-API-Key": "wrong-key"},
        json={"question": "What is AI?"},
    )
    assert response.status_code == 401
    assert "Invalid API key" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_ask_validation_error_on_missing_question(client: AsyncClient):
    response = await client.post(
        "/api/v1/voice-agent/ask",
        headers={"X-API-Key": TEST_KEY},
        json={"conversation_id": "call-123"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ask_validation_error_on_empty_question(client: AsyncClient):
    response = await client.post(
        "/api/v1/voice-agent/ask",
        headers={"X-API-Key": TEST_KEY},
        json={"question": "   "},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ask_success_with_x_api_key(client: AsyncClient):
    expected_answer = "Artificial intelligence enables computers to perform human-like tasks."

    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value=expected_answer):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "What is artificial intelligence?",
                "conversation_id": "call_abc_123",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == expected_answer
    assert data["conversation_id"] == "call_abc_123"
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_ask_success_with_bearer_token(client: AsyncClient):
    expected_answer = "Machine learning is a subset of artificial intelligence."

    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value=expected_answer):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={"question": "What is machine learning?"},
        )

    assert response.status_code == 200
    assert response.json()["answer"] == expected_answer


@pytest.mark.asyncio
async def test_ask_passes_conversation_history(client: AsyncClient):
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Yes, DeepSeek is an LLM.") as mock_generate:
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "Is it a large language model?",
                "conversation_id": "conv-456",
                "conversation_history": [
                    {"role": "user", "content": "What is DeepSeek?"},
                    {"role": "assistant", "content": "DeepSeek is an advanced AI model."},
                ],
            },
        )

    assert response.status_code == 200
    mock_generate.assert_called_once()
    passed_history = mock_generate.call_args[0][0]
    # Check that previous 2 turns plus current turn are passed
    assert len(passed_history) == 3
    assert passed_history[0].role == "user"
    assert passed_history[0].content == "What is DeepSeek?"
    assert passed_history[1].role == "assistant"
    assert passed_history[2].role == "user"
    assert passed_history[2].content == "Is it a large language model?"


@pytest.mark.asyncio
async def test_ask_supports_exotel_alias_fields(client: AsyncClient):
    """Exotel custom tools may send 'user_input' or wrap parameters in a 'parameters' dict."""
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Hello! How can I help?"):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "parameters": {
                    "user_input": "Hello there",
                    "call_sid": "exotel_sid_789",
                }
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Hello! How can I help?"
    assert data["conversation_id"] == "exotel_sid_789"


@pytest.mark.asyncio
async def test_ask_auth_failure_does_not_leak_secrets(client: AsyncClient):
    """Verify that authentication errors never leak the server's configured secret key."""
    # 1. Missing credentials
    resp1 = await client.post(
        "/api/v1/voice-agent/ask",
        json={"question": "Test question"},
    )
    assert resp1.status_code == 401
    assert TEST_KEY not in resp1.text
    assert TEST_KEY not in str(resp1.headers)

    # 2. Invalid X-API-Key
    resp2 = await client.post(
        "/api/v1/voice-agent/ask",
        headers={"X-API-Key": "completely-wrong-key-12345"},
        json={"question": "Test question"},
    )
    assert resp2.status_code == 401
    assert TEST_KEY not in resp2.text
    assert TEST_KEY not in str(resp2.headers)

    # 3. Invalid Bearer token
    resp3 = await client.post(
        "/api/v1/voice-agent/ask",
        headers={"Authorization": "Bearer completely-wrong-token-12345"},
        json={"question": "Test question"},
    )
    assert resp3.status_code == 401
    assert TEST_KEY not in resp3.text
    assert TEST_KEY not in str(resp3.headers)


@pytest.mark.asyncio
async def test_ask_exact_exotel_template_request(client: AsyncClient):
    """Verify exact Exotel request template payload from Task 4."""
    expected_answer = "Here are the top headlines in India today."

    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value=expected_answer) as mock_generate:
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "What are the latest important news headlines in India?",
                "conversation_id": "test-call-123",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == expected_answer
    assert data["conversation_id"] == "test-call-123"
    assert data["status"] == "success"

    # Verify generate_reply received the question
    mock_generate.assert_called_once()
    passed_history = mock_generate.call_args[0][0]
    assert len(passed_history) == 1
    assert passed_history[0].role == "user"
    assert passed_history[0].content == "What are the latest important news headlines in India?"


@pytest.mark.asyncio
async def test_ask_news_intent_invokes_news_service(client: AsyncClient):
    """Verify end-to-end integration: news question -> news service -> AI service reply."""
    from app.services.news_service import NewsArticle

    mock_articles = [
        NewsArticle(
            title="India advances tech ecosystem",
            description="India continues expansion of digital infrastructure.",
            source="TechDaily",
            url="https://example.com/1",
        )
    ]

    with patch.object(settings, "news_api_key", "dummy-news-key"), \
         patch("app.services.news_service.news_service.search_news", new_callable=AsyncMock, return_value=mock_articles) as mock_news, \
         patch("app.services.ai_service._call_api_once", new_callable=AsyncMock, return_value="India is actively expanding digital infrastructure."):

        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "What are the latest important news headlines in India?",
                "conversation_id": "test-call-123",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["conversation_id"] == "test-call-123"
    assert "India is actively expanding" in data["answer"]
    mock_news.assert_called_once_with("India", max_results=5)


@pytest.mark.asyncio
async def test_ask_general_headlines_invokes_top_headlines(client: AsyncClient):
    """Verify that generic questions ('what is the latest news?') invoke get_top_headlines."""
    from app.services.news_service import NewsArticle

    mock_articles = [
        NewsArticle(
            title="Global Climate Summit concludes",
            description="World leaders sign agreement.",
            source="GlobalNews",
            url="https://example.com/climate",
        )
    ]

    with patch.object(settings, "news_api_key", "dummy-news-key"), \
         patch("app.services.news_service.news_service.get_top_headlines", new_callable=AsyncMock, return_value=mock_articles) as mock_news, \
         patch("app.services.ai_service._call_api_once", new_callable=AsyncMock, return_value="The Global Climate Summit has just concluded."):

        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "What is the latest news today?",
                "conversation_id": "test-call-456",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Global Climate Summit" in data["answer"]
    mock_news.assert_called_once_with(max_results=5)


@pytest.mark.asyncio
async def test_ask_news_api_failure_handled_gracefully(client: AsyncClient):
    """Verify that when news retrieval raises an exception, the assistant responds gracefully without 500."""
    with patch.object(settings, "news_api_key", "dummy-news-key"), \
         patch("app.services.news_service.news_service.search_news", new_callable=AsyncMock, side_effect=RuntimeError("News API timeout")), \
         patch("app.services.ai_service._call_api_once", new_callable=AsyncMock, return_value="Live news feeds are temporarily unavailable."):

        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "What is the latest news about India?",
                "conversation_id": "test-call-789",
            },
        )

    assert response.status_code == 200
    assert "temporarily unavailable" in response.json()["answer"]


@pytest.mark.asyncio
async def test_ask_unauthorized_when_invalid_bearer_token(client: AsyncClient):
    """Verify 401 Unauthorized when an incorrect Bearer token is provided."""
    response = await client.post(
        "/api/v1/voice-agent/ask",
        headers={"Authorization": "Bearer wrong-bearer-token"},
        json={"question": "What is AI?"},
    )
    assert response.status_code == 401
    assert "Invalid API key" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_ask_success_with_bearer_token_double_prefix(client: AsyncClient):
    """Verify tolerance for users who accidentally type 'Bearer <key>' into Swagger's Bearer field."""
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Natural language processing."):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"Authorization": f"Bearer Bearer {TEST_KEY}"},
            json={"question": "What is NLP?"},
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Natural language processing."


def test_openapi_security_spec_for_voice_agent():
    """Verify that OpenAPI spec registers both APIKeyHeader and HTTPBearer on the endpoint for Swagger UI."""
    from app.main import app
    openapi = app.openapi()
    post_op = openapi["paths"]["/api/v1/voice-agent/ask"]["post"]
    security = post_op.get("security", [])

    assert {"APIKeyHeader": []} in security
    assert {"HTTPBearer": []} in security

    schemes = openapi["components"]["securitySchemes"]
    assert "APIKeyHeader" in schemes
    assert "HTTPBearer" in schemes
    assert schemes["APIKeyHeader"]["in"] == "header"
    assert schemes["APIKeyHeader"]["name"] == "X-API-Key"
    assert schemes["HTTPBearer"]["scheme"] == "bearer"


def test_voice_agent_key_loaded_from_env_file():
    """Verify that Settings loads voice_agent_api_key correctly from backend/.env."""
    from app.core.config import Settings, _ENV_FILE
    assert _ENV_FILE.exists(), f"Expected .env at {_ENV_FILE}"
    test_settings = Settings()
    # Key must be non-empty and have a secure length
    assert len(test_settings.voice_agent_api_key) >= 16


@pytest.mark.asyncio
async def test_ask_ordinary_question_returns_ai_generated_answer(client: AsyncClient):
    """Verify ordinary non-news questions invoke the AI service and return generated answers."""
    expected = "Artificial intelligence enables machines to perform tasks requiring human-like intelligence."
    with patch("app.services.ai_service._call_api_once", new_callable=AsyncMock, return_value=expected):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "What is artificial intelligence?",
                "conversation_id": "test-call-123",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == expected
    assert data["conversation_id"] == "test-call-123"
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_ask_ai_failure_returns_fallback_gracefully(client: AsyncClient):
    """Verify that when AI calls fail, the endpoint safely returns FALLBACK_REPLY without 500 error."""
    from app.services.ai_service import FALLBACK_REPLY

    with patch("app.services.ai_service._call_api_once", side_effect=Exception("NVIDIA API connection reset")):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"X-API-Key": TEST_KEY},
            json={
                "question": "What is artificial intelligence?",
                "conversation_id": "test-call-123",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == FALLBACK_REPLY
    assert data["conversation_id"] == "test-call-123"
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_generate_reply_fallback_model_on_primary_timeout():
    """Verify that if the primary model times out, generate_reply falls back to the verified secondary model."""
    from app.services.ai_service import generate_reply
    from app.schemas.conversation import LLMMessage

    call_count = 0

    async def mock_call(messages, model=None):
        nonlocal call_count
        call_count += 1
        if model != "meta/llama-3.2-11b-vision-instruct":
            raise asyncio.TimeoutError("Primary model timed out")
        return "Reply from verified fallback model."

    with patch.object(settings, "nvidia_model", "moonshotai/kimi-k3"), \
         patch("app.services.ai_service._call_api_once", side_effect=mock_call):
        reply = await generate_reply([LLMMessage(role="user", content="What is AI?")])

    assert reply == "Reply from verified fallback model."
    assert call_count >= 2


@pytest.mark.asyncio
async def test_ask_success_with_query_param(client: AsyncClient):
    """Exotel can pass secret in URL query: /api/v1/voice-agent/ask?api_key=..."""
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Query auth works."):
        response = await client.post(
            f"/api/v1/voice-agent/ask?api_key={TEST_KEY}",
            json={"question": "What is AI?"},
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Query auth works."


@pytest.mark.asyncio
async def test_ask_success_with_path_token(client: AsyncClient):
    """Exotel can pass secret in URL path: /api/v1/voice-agent/ask/<token>"""
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Path auth works."):
        response = await client.post(
            f"/api/v1/voice-agent/ask/{TEST_KEY}",
            json={"question": "What is AI?"},
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Path auth works."


@pytest.mark.asyncio
async def test_ask_success_with_prefix_path_token(client: AsyncClient):
    """Exotel can pass secret in URL prefix path: /api/v1/voice-agent/<token>/ask"""
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Prefix path auth works."):
        response = await client.post(
            f"/api/v1/voice-agent/{TEST_KEY}/ask",
            json={"question": "What is AI?"},
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Prefix path auth works."


@pytest.mark.asyncio
async def test_ask_success_with_basic_auth(client: AsyncClient):
    """Exotel can pass secret via HTTP Basic Auth: Authorization: Basic <base64>"""
    import base64
    b64_creds = base64.b64encode(f"{TEST_KEY}:".encode()).decode()
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Basic auth works."):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            headers={"Authorization": f"Basic {b64_creds}"},
            json={"question": "What is AI?"},
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Basic auth works."


@pytest.mark.asyncio
async def test_ask_success_with_body_api_key(client: AsyncClient):
    """Exotel can pass secret in JSON body if platform supports body defaults."""
    with patch("app.api.voice_agent.generate_reply", new_callable=AsyncMock, return_value="Body auth works."):
        response = await client.post(
            "/api/v1/voice-agent/ask",
            json={"question": "What is AI?", "api_key": TEST_KEY},
        )
    assert response.status_code == 200
    assert response.json()["answer"] == "Body auth works."


@pytest.mark.asyncio
async def test_ask_fails_with_invalid_path_token(client: AsyncClient):
    """Invalid path token must return 401."""
    response = await client.post(
        "/api/v1/voice-agent/ask/wrong-secret-token",
        json={"question": "What is AI?"},
    )
    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ask_fails_with_invalid_query_param(client: AsyncClient):
    """Invalid query param must return 401."""
    response = await client.post(
        "/api/v1/voice-agent/ask?api_key=wrong-secret-token",
        json={"question": "What is AI?"},
    )
    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]


