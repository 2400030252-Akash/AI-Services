"""
app/database/repositories/call_repo.py
=======================================
Repository for the ``calls`` table.

Handles all data-access for Call records.
Conversation turns have their own repository (conversation_repo.py).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import Call

SortOrder = Literal["asc", "desc"]


class CallRepository:
    """Data-access layer for Call records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        call_sid: str,
        from_number: str,
        to_number: str,
        direction: str,
        status: str = "queued",
        started_at: datetime | None = None,
    ) -> Call:
        """
        Persist a new call record and return the flushed instance.
        Caller must commit the session.
        """
        call = Call(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            direction=direction,
            status=status,
            started_at=started_at,
        )
        self._session.add(call)
        await self._session.flush()
        await self._session.refresh(call)
        return call

    async def update_status(
        self,
        call: Call,
        *,
        status: str,
        duration: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> Call:
        """
        Mutate mutable fields on an existing call.

        Only keyword args that are not None are applied; others are left
        unchanged.  The caller must commit after this returns.
        """
        call.status = status
        if duration is not None:
            call.duration = duration
        if started_at is not None:
            call.started_at = started_at
        if ended_at is not None:
            call.ended_at = ended_at
        await self._session.flush()
        await self._session.refresh(call)
        return call

    # ------------------------------------------------------------------
    # Read — single row
    # ------------------------------------------------------------------

    async def get_by_id(self, call_id: uuid.UUID) -> Call | None:
        """Return a Call by its internal UUID, or None."""
        result = await self._session.execute(
            select(Call).where(Call.id == call_id)
        )
        return result.scalar_one_or_none()

    async def get_by_sid(self, call_sid: str) -> Call | None:
        """Return a Call by Twilio CallSid, or None."""
        result = await self._session.execute(
            select(Call).where(Call.call_sid == call_sid)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Read — collection + count (for pagination)
    # ------------------------------------------------------------------

    async def count_all(self) -> int:
        """Return total number of calls in the table."""
        result = await self._session.execute(
            select(func.count()).select_from(Call)
        )
        return result.scalar_one()

    async def list_all(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "started_at",
        sort_order: SortOrder = "desc",
    ) -> list[Call]:
        """
        Return paginated calls, sortable by ``started_at`` or ``created_at``.

        Defaults to most-recent first (``started_at DESC``).
        Falls back to ``created_at`` for any unrecognised ``sort_by`` value.
        """
        # Resolve sort column — whitelist to prevent injection
        sort_col = Call.started_at if sort_by == "started_at" else Call.created_at
        order_expr = sort_col.desc() if sort_order == "desc" else sort_col.asc()

        result = await self._session.execute(
            select(Call)
            .order_by(order_expr)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Dashboard metrics aggregations
    # ------------------------------------------------------------------

    async def count_by_status(self, status: str) -> int:
        """Return total count of calls with a given status."""
        result = await self._session.execute(
            select(func.count()).select_from(Call).where(Call.status == status)
        )
        return result.scalar_one()

    async def count_calls_started_since(self, since_dt: datetime) -> int:
        """Return total count of calls started on or after a given timestamp."""
        result = await self._session.execute(
            select(func.count())
            .select_from(Call)
            .where(func.coalesce(Call.started_at, Call.created_at) >= since_dt)
        )
        return result.scalar_one()

    async def get_total_duration_seconds(self) -> int:
        """Return total sum of call duration seconds across all calls."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(Call.duration), 0)).select_from(Call)
        )
        return int(result.scalar_one())

    async def list_active_calls(self) -> list[Call]:
        """Return all calls currently in 'active' status."""
        result = await self._session.execute(
            select(Call)
            .where(Call.status == "active")
            .order_by(Call.started_at.desc())
        )
        return list(result.scalars().all())
