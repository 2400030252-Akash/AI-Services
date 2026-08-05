"""
tests/test_auth.py
==================
Tests for the admin authentication endpoints.

Uses an in-process test client (httpx.AsyncClient) backed by the FastAPI app.
No real database connection is required — AdminUserRepository is mocked.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.models.admin_user import AdminUser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin(email: str = "admin@example.com") -> AdminUser:
    """Return a minimal AdminUser instance for mocking."""
    from app.core.security import hash_password

    admin = AdminUser()
    admin.id = uuid.uuid4()
    admin.email = email
    admin.password_hash = hash_password("correctpassword")
    admin.created_at = datetime.now(timezone.utc)
    admin.updated_at = datetime.now(timezone.utc)
    return admin


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    admin = _make_admin()

    with patch(
        "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
        new_callable=AsyncMock,
        return_value=admin,
    ):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correctpassword"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["token"]["token_type"] == "bearer"
    assert data["token"]["access_token"]
    assert data["admin"]["email"] == "admin@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    admin = _make_admin()

    with patch(
        "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
        new_callable=AsyncMock,
        return_value=admin,
    ):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrongpassword"},
        )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["error"] is True
    assert detail["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    with patch(
        "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "noone@example.com", "password": "anypassword"},
        )

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_missing_fields(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": "admin@example.com"})
    assert resp.status_code == 422   # pydantic validation error


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer this.is.not.valid"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_me_valid_token(client: AsyncClient) -> None:
    from app.core.security import create_access_token

    admin = _make_admin()
    token = create_access_token(subject=admin.email)

    with patch(
        "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
        new_callable=AsyncMock,
        return_value=admin,
    ):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert resp.json()["email"] == admin.email
