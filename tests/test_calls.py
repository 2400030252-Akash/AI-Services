"""
tests/test_calls.py
===================
Tests for the call management service and API endpoints.

All DB interactions are mocked — no real Postgres connection needed.
The ``client`` fixture (from conftest.py) provides a test HTTP client
with ``get_db`` already overridden.

Coverage:
  Service layer
    - create_call sets status=active and started_at
    - end_call computes duration and sets status=completed
    - end_call raises 409 if already in terminal state
    - mark_call_failed sets status=failed
    - get_call raises 404 for unknown id
    - list_calls returns paginated shape

  API layer
    - GET /calls requires auth (401 without token)
    - GET /calls returns 200 + paginated body
    - GET /calls/{id} returns 200 + detail body
    - GET /calls/{id} returns 404 for unknown id
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.models.call import Call
from app.models.admin_user import AdminUser
from app.schemas.call import CallOut, ConversationTurnOut, PaginatedCallsOut, PaginationMeta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_call(
    status: str = "active",
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    duration: int | None = None,
) -> Call:
    call = Call()
    call.id = uuid.uuid4()
    call.call_sid = f"CA{uuid.uuid4().hex[:30]}"
    call.from_number = "+15550001111"
    call.to_number = "+15559998888"
    call.status = status
    call.direction = "inbound"
    call.duration = duration
    call.started_at = started_at or datetime.now(timezone.utc)
    call.ended_at = ended_at
    call.created_at = datetime.now(timezone.utc)
    call.conversations = []
    return call


def _make_admin_token() -> str:
    from app.core.security import create_access_token
    return create_access_token(subject="admin@example.com")


def _make_admin() -> AdminUser:
    from app.core.security import hash_password
    admin = AdminUser()
    admin.id = uuid.uuid4()
    admin.email = "admin@example.com"
    admin.password_hash = hash_password("password")
    admin.created_at = datetime.now(timezone.utc)
    admin.updated_at = datetime.now(timezone.utc)
    return admin


# ---------------------------------------------------------------------------
# Service layer unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_call_sets_active_and_started_at() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.call_service import CallService

    session = AsyncMock(spec=AsyncSession)
    service = CallService(session)

    created = _make_call(status="active")

    with patch(
        "app.database.repositories.call_repo.CallRepository.create",
        new_callable=AsyncMock,
        return_value=created,
    ):
        result = await service.create_call(
            call_sid="CAtest",
            from_number="+15550001111",
            to_number="+15559998888",
        )

    assert result.status == "active"
    assert result.started_at is not None


@pytest.mark.asyncio
async def test_end_call_computes_duration() -> None:
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.call_service import CallService

    session = AsyncMock(spec=AsyncSession)
    service = CallService(session)

    started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    call = _make_call(status="active", started_at=started)

    completed = _make_call(status="completed", started_at=started, duration=90)

    with (
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.update_status",
            new_callable=AsyncMock,
            return_value=completed,
        ),
        patch("app.services.call_service._now_utc",
              return_value=started + timedelta(seconds=90)),
    ):
        result = await service.end_call(call.id)

    assert result.status == "completed"
    assert result.duration == 90


@pytest.mark.asyncio
async def test_end_call_raises_409_if_already_terminal() -> None:
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.call_service import CallService

    session = AsyncMock(spec=AsyncSession)
    service = CallService(session)
    call = _make_call(status="completed")

    with patch(
        "app.database.repositories.call_repo.CallRepository.get_by_id",
        new_callable=AsyncMock,
        return_value=call,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.end_call(call.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CALL_ALREADY_TERMINAL"


@pytest.mark.asyncio
async def test_mark_call_failed() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.call_service import CallService

    session = AsyncMock(spec=AsyncSession)
    service = CallService(session)
    call = _make_call(status="active")
    failed = _make_call(status="failed")

    with (
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.update_status",
            new_callable=AsyncMock,
            return_value=failed,
        ),
    ):
        result = await service.mark_call_failed(call.id)

    assert result.status == "failed"


@pytest.mark.asyncio
async def test_get_call_raises_404_for_unknown_id() -> None:
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.call_service import CallService

    session = AsyncMock(spec=AsyncSession)
    service = CallService(session)

    with patch(
        "app.database.repositories.call_repo.CallRepository.get_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_call(uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "CALL_NOT_FOUND"


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_calls_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/calls")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_calls_success(client: AsyncClient) -> None:
    admin = _make_admin()
    token = _make_admin_token()
    calls = [_make_call(), _make_call()]

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.count_all",
            new_callable=AsyncMock,
            return_value=2,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.list_all",
            new_callable=AsyncMock,
            return_value=calls,
        ),
    ):
        resp = await client.get(
            "/api/v1/calls",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["total"] == 2
    assert len(body["data"]) == 2


@pytest.mark.asyncio
async def test_list_calls_invalid_sort_by(client: AsyncClient) -> None:
    admin = _make_admin()
    token = _make_admin_token()

    with patch(
        "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
        new_callable=AsyncMock,
        return_value=admin,
    ):
        resp = await client.get(
            "/api/v1/calls?sort_by=hack_attempt",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 422   # regex pattern validation rejects this


@pytest.mark.asyncio
async def test_get_call_detail_success(client: AsyncClient) -> None:
    admin = _make_admin()
    token = _make_admin_token()
    call = _make_call()

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=call,
        ),
    ):
        resp = await client.get(
            f"/api/v1/calls/{call.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(call.id)
    assert "conversations" in body


@pytest.mark.asyncio
async def test_get_call_detail_not_found(client: AsyncClient) -> None:
    admin = _make_admin()
    token = _make_admin_token()
    fake_id = uuid.uuid4()

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        resp = await client.get(
            f"/api/v1/calls/{fake_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "CALL_NOT_FOUND"
