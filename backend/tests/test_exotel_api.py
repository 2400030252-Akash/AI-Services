"""
tests/test_exotel_api.py
========================
Tests for Exotel endpoints:
  - GET /api/v1/exotel/health (capability verification and trial account status)
  - GET /api/v1/exotel/ws-config (WebSocket configuration resolver)
  - POST /api/v1/exotel/call-status (call status updates)
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
    call.call_sid = "exotel_call_sid_12345"
    call.from_number = "+919876543210"
    call.to_number = "+918000000000"
    call.status = status
    call.direction = "inbound"
    call.duration = None
    call.started_at = datetime.now(timezone.utc)
    call.ended_at = None
    call.created_at = datetime.now(timezone.utc)
    call.conversations = []
    return call


@pytest.fixture(autouse=True)
def bypass_exotel_auth():
    """Bypass Exotel webhook auth for route testing."""
    from app.main import app
    from app.api.deps_exotel import validate_exotel_request

    app.dependency_overrides[validate_exotel_request] = lambda: None
    yield
    app.dependency_overrides.pop(validate_exotel_request, None)


@pytest.mark.asyncio
async def test_exotel_health_blocked_status_when_streaming_not_enabled(client: AsyncClient):
    """
    Validates Adjustment #1:
    Live streaming must be reported as BLOCKED pending account permission
    when exotel_streaming_enabled is False.
    """
    with patch.object(settings, "exotel_streaming_enabled", False):
        response = await client.get("/api/v1/exotel/health")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "exotel"
    assert data["streaming_capability_verified"] is False
    assert data["live_call_testing_status"] == "BLOCKED_PENDING_EXOTEL_STREAMING_FEATURE"
    assert "Voicebot Applet" in data["account_requirement_note"]


@pytest.mark.asyncio
async def test_exotel_health_ready_status_when_streaming_enabled(client: AsyncClient):
    with patch.object(settings, "exotel_streaming_enabled", True):
        response = await client.get("/api/v1/exotel/health")

    assert response.status_code == 200
    data = response.json()
    assert data["streaming_capability_verified"] is True
    assert data["live_call_testing_status"] == "READY_FOR_LIVE_CALL"


@pytest.mark.asyncio
async def test_exotel_ws_config(client: AsyncClient):
    response = await client.get("/api/v1/exotel/ws-config")
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "/api/v1/exotel/stream" in data["url"]


@pytest.mark.asyncio
async def test_exotel_call_status_completed(client: AsyncClient):
    mock_call = _make_call(status="active")

    with patch("app.api.exotel_status.CallRepository.get_by_sid", new_callable=AsyncMock, return_value=mock_call), \
         patch("app.api.exotel_status.CallService.end_call", new_callable=AsyncMock) as mock_end:
        response = await client.post(
            "/api/v1/exotel/call-status",
            data={
                "CallSid": "exotel_call_sid_12345",
                "Status": "completed",
                "Duration": "45",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_end.assert_called_once_with(mock_call.id)


@pytest.mark.asyncio
async def test_exotel_call_status_failed(client: AsyncClient):
    mock_call = _make_call(status="active")

    with patch("app.api.exotel_status.CallRepository.get_by_sid", new_callable=AsyncMock, return_value=mock_call), \
         patch("app.api.exotel_status.CallService.mark_call_failed", new_callable=AsyncMock) as mock_fail:
        response = await client.post(
            "/api/v1/exotel/call-status",
            data={
                "CallSid": "exotel_call_sid_12345",
                "Status": "failed",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_fail.assert_called_once_with(mock_call.id)
