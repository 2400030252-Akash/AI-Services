"""
app/api/auth.py
===============
Auth router — mounts at /api/v1/auth.

Endpoints:
  POST /api/v1/auth/login   — verify credentials, return JWT
  GET  /api/v1/auth/me      — return current admin's profile (protected)

No signup, no password-reset, no roles beyond 'admin'.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.database.session import get_db
from app.schemas.auth import AdminProfile, LoginRequest, LoginResponse
from app.services.auth_service import AuthService

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin login",
    responses={
        401: {
            "description": "Invalid credentials.",
            "content": {
                "application/json": {
                    "example": {
                        "error": True,
                        "message": "Invalid email or password.",
                        "code": "INVALID_CREDENTIALS",
                    }
                }
            },
        }
    },
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate an admin user.

    - Verifies email + bcrypt password against **admin_users**.
    - Returns a signed JWT access token on success.
    - Always returns HTTP 401 (never 404) on any failure to prevent
      email enumeration.
    """
    service = AuthService(db)
    result = await service.login(email=body.email, password=body.password)
    # Login is read-only — no commit needed
    return result


# ---------------------------------------------------------------------------
# GET /me  (protected)
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=AdminProfile,
    status_code=status.HTTP_200_OK,
    summary="Current admin profile",
    responses={
        401: {
            "description": "Missing or invalid JWT.",
            "content": {
                "application/json": {
                    "example": {
                        "error": True,
                        "message": "Not authenticated.",
                        "code": "NOT_AUTHENTICATED",
                    }
                }
            },
        }
    },
)
async def me(
    current_admin: AdminProfile = Depends(get_current_admin),
) -> AdminProfile:
    """
    Return the profile of the currently authenticated admin.

    Requires a valid ``Authorization: Bearer <token>`` header.
    """
    return current_admin
