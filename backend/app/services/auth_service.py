"""
app/services/auth_service.py
=============================
Business logic for admin authentication.

Responsibilities:
  - Verify email + password against the admin_users table.
  - Issue JWT access tokens via app.core.security.
  - Create admin users (used by the seed script only — no API signup).

This service is session-aware but does NOT commit.  The calling
route handler owns the transaction boundary.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.database.repositories.admin_user_repo import AdminUserRepository
from app.models.admin_user import AdminUser
from app.schemas.auth import AdminProfile, LoginResponse, TokenResponse


class AuthService:
    """Stateless auth service — instantiated per request with a DB session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AdminUserRepository(session)

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> LoginResponse:
        """
        Authenticate an admin by email + password.

        Raises HTTP 401 with a generic message on any failure so callers
        cannot distinguish 'wrong email' from 'wrong password' (timing-safe
        approach via constant-time bcrypt verify even on miss).
        """
        admin = await self._repo.get_by_email(email)

        # Always run bcrypt even on miss to avoid timing oracle
        dummy_hash = "$2b$12$3jIcGRZs5qvQWEGr4pfXtOxWaDSIorzsnRBguKJAT3SiV0EUuUNNy"
        password_to_check = admin.password_hash if admin else dummy_hash
        password_ok = verify_password(password, password_to_check)

        if not admin or not password_ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": True,
                    "message": "Invalid email or password.",
                    "code": "INVALID_CREDENTIALS",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_str = create_access_token(subject=admin.email)
        expire_seconds = settings.access_token_expire_minutes * 60

        return LoginResponse(
            token=TokenResponse(
                access_token=token_str,
                token_type="bearer",
                expires_in=expire_seconds,
            ),
            admin=AdminProfile.model_validate(admin),
        )

    # ------------------------------------------------------------------
    # Admin creation (seed / CLI only — not exposed via API)
    # ------------------------------------------------------------------

    async def create_admin(self, email: str, password: str) -> AdminUser:
        """
        Create a new admin user record.

        Raises HTTP 409 if the email already exists.
        Caller must commit the session after this returns.
        """
        existing = await self._repo.get_by_email(email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": True,
                    "message": f"Admin with email '{email}' already exists.",
                    "code": "ADMIN_ALREADY_EXISTS",
                },
            )

        pw_hash = hash_password(password)
        admin = await self._repo.create(email=email, password_hash=pw_hash)
        return admin
