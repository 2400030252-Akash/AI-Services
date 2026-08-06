"""
tests/test_voice.py
====================
Tests for Twilio voice webhook endpoints.

Covers:
  - Signature validation rejection (403)
  - POST /api/v1/voice/voice (Incoming call setup)
  - POST /api/v1/voice/respond (Empty speech handling)
  - POST /api/v1/voice/respond (Valid speech processing & AI generation)
  - POST /api/v1/voice/call-status (Call completion & failure handling)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.call import Call


def _make_call(status: str = "active") -> Call:
    call = Call()
    call.id = uuid.uuid4()
    call.call_sid = "CA1234567890abcdef1234567890abcdef"
    call.from_number = "+15550001111"
    call.to_number = "+15559998888"
    call.status = status
    call.direction = "inbound"
    call.duration = None
    call.started_at = datetime.now(timezone.utc)
    call.ended_at = None
    call.created_at = datetime.now(timezone.utc)
    call.conversations = []
    return call


@pytest.fixture(autouse=True)
def skip_twilio_sig_validation():
    """Bypass Twilio signature validation for testing."""
    original = settings.twilio_skip_signature_validation
    settings.twilio_skip_signature_validation = True
    yield
    settings.twilio_skip_signature_validation = original


@pytest.mark.asyncio
async def test_signature_validation_fails_when_enabled(client: AsyncClient) -> None:
    """When signature validation is enabled, request without signature fails with 403."""
    settings.twilio_skip_signature_validation = False

    form_data = {
        "CallSid": "CA1234567890abcdef1234567890abcdef",
        "From": "+15550001111",
        "To": "+15559998888",
    }
    resp = await client.post("/api/v1/voice/voice", data=form_data)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "TWILIO_SIGNATURE_MISSING"


@pytest.mark.asyncio
async def test_incoming_call_success(client: AsyncClient) -> None:
    """Incoming call setup persists a call record and returns TwiML XML."""
    call = _make_call()

    with patch(
        "app.services.call_service.CallService.create_call",
        new_callable=AsyncMock,
        return_value=call,
    ):
        form_data = {
            "CallSid": call.call_sid,
            "From": call.from_number,
            "To": call.to_number,
            "Direction": "inbound",
        }
        resp = await client.post("/api/v1/voice/voice", data=form_data)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<Gather" in resp.text
    assert "<Say>Hello! Thank you for calling." in resp.text


@pytest.mark.asyncio
async def test_respond_empty_speech(client: AsyncClient) -> None:
    """Unclear/empty speech result returns a polite prompt to repeat."""
    call = _make_call()

    with patch(
        "app.database.repositories.call_repo.CallRepository.get_by_sid",
        new_callable=AsyncMock,
        return_value=call,
    ):
        form_data = {
            "CallSid": call.call_sid,
            "SpeechResult": "   ",
        }
        resp = await client.post("/api/v1/voice/respond", data=form_data)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "didn't catch that" in resp.text
    assert "<Gather" in resp.text


@pytest.mark.asyncio
async def test_respond_valid_speech(client: AsyncClient) -> None:
    """Valid speech input calls AI service and returns TwiML with AI response."""
    call = _make_call()

    with (
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_sid",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.services.conversation_service.ConversationService.add_message",
            new_callable=AsyncMock,
        ) as mock_add_message,
        patch(
            "app.services.conversation_service.ConversationService.get_conversation_history",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.api.voice.generate_reply",
            new_callable=AsyncMock,
            return_value="I can help you with your account details.",
        ) as mock_generate_reply,
    ):
        form_data = {
            "CallSid": call.call_sid,
            "SpeechResult": "I need help with my account",
        }
        resp = await client.post("/api/v1/voice/respond", data=form_data)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<Say>I can help you with your account details.</Say>" in resp.text
    assert "<Gather" in resp.text

    # Verify user message and assistant message were persisted
    assert mock_add_message.call_count == 2
    mock_generate_reply.assert_called_once()


@pytest.mark.asyncio
async def test_call_status_completed(client: AsyncClient) -> None:
    """CallStatus completed triggers end_call service logic."""
    call = _make_call()

    with (
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_sid",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.services.call_service.CallService.end_call",
            new_callable=AsyncMock,
        ) as mock_end_call,
    ):
        form_data = {
            "CallSid": call.call_sid,
            "CallStatus": "completed",
        }
        resp = await client.post("/api/v1/voice/call-status", data=form_data)

    assert resp.status_code == 200
    mock_end_call.assert_called_once_with(call.id)


@pytest.mark.asyncio
async def test_call_status_failed(client: AsyncClient) -> None:
    """CallStatus failed triggers mark_call_failed service logic."""
    call = _make_call()

    with (
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_sid",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.services.call_service.CallService.mark_call_failed",
            new_callable=AsyncMock,
        ) as mock_mark_call_failed,
    ):
        form_data = {
            "CallSid": call.call_sid,
            "CallStatus": "failed",
        }
        resp = await client.post("/api/v1/voice/call-status", data=form_data)

    assert resp.status_code == 200
    mock_mark_call_failed.assert_called_once_with(call.id)
