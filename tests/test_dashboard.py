"""
tests/test_dashboard.py
========================
Tests for dashboard APIs:
  - GET /api/v1/dashboard/summary
  - GET /api/v1/dashboard/active-calls

Verifies:
  - Unauthenticated access returns 401
  - Authenticated admin JWT accesses summary metrics
  - Active call list includes computed live_duration_seconds
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.admin_user import AdminUser
from app.models.call import Call


def _make_admin() -> AdminUser:
    admin = AdminUser()
    admin.id = uuid.uuid4()
    admin.email = "admin@example.com"
    admin.password_hash = "hashed_password"
    admin.created_at = datetime.now(timezone.utc)
    admin.updated_at = datetime.now(timezone.utc)
    return admin


def _make_active_call() -> Call:
    call = Call()
    call.id = uuid.uuid4()
    call.call_sid = "CA11112222333344445555666677778888"
    call.from_number = "+15551234567"
    call.to_number = "+15559876543"
    call.status = "active"
    call.direction = "inbound"
    call.duration = None
    call.started_at = datetime.now(timezone.utc)
    call.ended_at = None
    call.created_at = datetime.now(timezone.utc)
    return call


@pytest.mark.asyncio
async def test_dashboard_summary_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.asyncio
async def test_dashboard_summary_success(client: AsyncClient) -> None:
    admin = _make_admin()
    token = create_access_token(subject=admin.email)

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.count_all",
            new_callable=AsyncMock,
            return_value=42,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.count_by_status",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.count_calls_started_since",
            new_callable=AsyncMock,
            return_value=12,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.get_total_duration_seconds",
            new_callable=AsyncMock,
            return_value=3600,
        ),
    ):
        resp = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 42
    assert data["active_calls_count"] == 3
    assert data["calls_today"] == 12
    assert data["total_talk_time_seconds"] == 3600


@pytest.mark.asyncio
async def test_active_calls_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/dashboard/active-calls")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.asyncio
async def test_active_calls_success(client: AsyncClient) -> None:
    admin = _make_admin()
    token = create_access_token(subject=admin.email)
    call = _make_active_call()

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.list_active_calls",
            new_callable=AsyncMock,
            return_value=[call],
        ),
    ):
        resp = await client.get(
            "/api/v1/dashboard/active-calls",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == str(call.id)
    assert data[0]["status"] == "active"
    assert "live_duration_seconds" in data[0]
    assert data[0]["live_duration_seconds"] >= 0
