"""
app/database/repositories/admin_user_repo.py
=============================================
Repository for the ``admin_users`` table.

All methods accept an ``AsyncSession`` injected by the caller (typically
via FastAPI's ``Depends(get_db)``).  No session management happens here —
that belongs in the route / service layer.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_user import AdminUser


class AdminUserRepository:
    """Data-access layer for AdminUser records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
    ) -> AdminUser:
        """
        Persist a new admin user and return the flushed instance.

        The caller is responsible for committing the transaction.
        """
        admin = AdminUser(email=email, password_hash=password_hash)
        self._session.add(admin)
        await self._session.flush()          # assign DB-generated values
        await self._session.refresh(admin)   # populate id, created_at, …
        return admin

    # ------------------------------------------------------------------
    # Read — single row
    # ------------------------------------------------------------------

    async def get_by_id(self, admin_id: uuid.UUID) -> AdminUser | None:
        """Return AdminUser by primary key, or None if not found."""
        result = await self._session.execute(
            select(AdminUser).where(AdminUser.id == admin_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> AdminUser | None:
        """Return AdminUser by email (case-sensitive), or None if not found."""
        result = await self._session.execute(
            select(AdminUser).where(AdminUser.email == email)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Read — collection
    # ------------------------------------------------------------------

    async def list_all(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AdminUser]:
        """Return a paginated list of all admin users, ordered by created_at."""
        result = await self._session.execute(
            select(AdminUser)
            .order_by(AdminUser.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
