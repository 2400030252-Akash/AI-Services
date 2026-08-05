"""
app/api/deps.py
===============
FastAPI dependency injection helpers shared across all route modules.

``get_current_admin`` is the primary auth guard.  Inject it via
``Depends(get_current_admin)`` on any route that requires authentication.

Usage::

    @router.get("/some-protected-route")
    async def handler(admin: AdminProfile = Depends(get_current_admin)):
        ...
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database.repositories.admin_user_repo import AdminUserRepository
from app.database.session import get_db
from app.schemas.auth import AdminProfile

# HTTPBearer extracts the token from the Authorization: Bearer <token> header.
# auto_error=False lets us return a structured error instead of FastAPI's default.
bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Structured 401 helpers
# ---------------------------------------------------------------------------

def _unauthorized(message: str, code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": True, "message": message, "code": code},
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# Primary auth dependency
# ---------------------------------------------------------------------------

async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AdminProfile:
    """
    Validate the Bearer JWT and return the authenticated admin's profile.

    Error codes returned:
      NOT_AUTHENTICATED — no token in header
      TOKEN_EXPIRED     — token has expired
      INVALID_TOKEN     — token is malformed or signature invalid
      ADMIN_NOT_FOUND   — token subject no longer exists in DB
    """
    if credentials is None:
        raise _unauthorized("Authentication required.", "NOT_AUTHENTICATED")

    token = credentials.credentials

    try:
        email = decode_access_token(token)
    except ExpiredSignatureError:
        raise _unauthorized("Token has expired. Please log in again.", "TOKEN_EXPIRED")
    except JWTError:
        raise _unauthorized("Invalid or malformed token.", "INVALID_TOKEN")

    repo = AdminUserRepository(db)
    admin = await repo.get_by_email(email)

    if admin is None:
        raise _unauthorized("Admin account not found.", "ADMIN_NOT_FOUND")

    return AdminProfile.model_validate(admin)
