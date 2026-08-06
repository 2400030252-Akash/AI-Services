"""
app/services/call_service.py
=============================
Business logic for call lifecycle management.

Public surface (called by the telephony webhook module in a later module,
and also directly accessible to the admin API for reads):

  create_call(...)         → creates a row with status "active"
  end_call(call_id)        → sets ended_at, computes duration, marks "completed"
  mark_call_failed(call_id)→ sets status "failed"

  get_call(call_id)        → single call or 404
  list_calls(...)          → paginated + sortable list

Design decisions:
  - The service does NOT commit.  Route handlers own transaction boundaries.
  - All writes go through CallRepository — no raw ORM in this file.
  - Duration is computed here (Python layer) rather than in SQL so it is
    easy to test without a live database.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.call_repo import CallRepository, SortOrder
from app.models.call import Call
from app.schemas.call import (
    CallDetailOut,
    CallOut,
    PaginatedCallsOut,
    PaginationMeta,
)


def _now_utc() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def _not_found(call_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": True,
            "message": f"Call '{call_id}' not found.",
            "code": "CALL_NOT_FOUND",
        },
    )


class CallService:
    """
    Call lifecycle service.
    Instantiated per request with a DB session injected by FastAPI's DI.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CallRepository(session)

    # ------------------------------------------------------------------
    # Write — lifecycle transitions
    # ------------------------------------------------------------------

    async def create_call(
        self,
        *,
        call_sid: str,
        from_number: str,
        to_number: str,
        direction: str = "inbound",
    ) -> Call:
        """
        Create a new call row.

        - ``status`` is set to ``"active"`` (in-progress) immediately.
        - ``started_at`` is stamped now (UTC).

        The Twilio webhook module will call this when a call connects.
        The caller must commit after this returns.
        """
        call = await self._repo.create(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            direction=direction,
            status="active",
            started_at=_now_utc(),
        )
        return call

    async def end_call(self, call_id: uuid.UUID) -> Call:
        """
        Mark a call as completed.

        Sets ``ended_at = now()``, computes ``duration_seconds`` from
        ``started_at`` → ``ended_at``, and sets ``status = "completed"``.

        Raises HTTP 404 if the call is not found.
        Raises HTTP 409 if the call is already completed or failed.
        Caller must commit after this returns.
        """
        call = await self._repo.get_by_id(call_id)
        if call is None:
            raise _not_found(call_id)

        if call.status in ("completed", "failed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": True,
                    "message": (
                        f"Call '{call_id}' is already in terminal state "
                        f"'{call.status}' and cannot be ended again."
                    ),
                    "code": "CALL_ALREADY_TERMINAL",
                },
            )

        ended = _now_utc()
        duration: int | None = None
        if call.started_at is not None:
            delta = ended - call.started_at.replace(tzinfo=timezone.utc) \
                if call.started_at.tzinfo is None \
                else ended - call.started_at
            duration = max(0, int(delta.total_seconds()))

        call = await self._repo.update_status(
            call,
            status="completed",
            ended_at=ended,
            duration=duration,
        )
        return call

    async def mark_call_failed(self, call_id: uuid.UUID) -> Call:
        """
        Mark a call as failed (error path).

        Sets ``ended_at = now()`` and ``status = "failed"``.
        Duration is not computed (call may never have connected).

        Raises HTTP 404 if the call is not found.
        Caller must commit after this returns.
        """
        call = await self._repo.get_by_id(call_id)
        if call is None:
            raise _not_found(call_id)

        if call.status in ("completed", "failed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": True,
                    "message": (
                        f"Call '{call_id}' is already in terminal state "
                        f"'{call.status}'."
                    ),
                    "code": "CALL_ALREADY_TERMINAL",
                },
            )

        call = await self._repo.update_status(
            call,
            status="failed",
            ended_at=_now_utc(),
        )
        return call

    # ------------------------------------------------------------------
    # Read — used by admin API endpoints
    # ------------------------------------------------------------------

    async def get_call(self, call_id: uuid.UUID) -> Call:
        """
        Return a single Call by UUID.
        Raises HTTP 404 if not found.
        """
        call = await self._repo.get_by_id(call_id)
        if call is None:
            raise _not_found(call_id)
        return call

    async def list_calls(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "started_at",
        sort_order: SortOrder = "desc",
    ) -> PaginatedCallsOut:
        """
        Return a paginated list of calls with metadata.

        ``sort_by`` accepts ``started_at`` or ``created_at``.
        ``sort_order`` accepts ``asc`` or ``desc``.
        """
        total, calls = await self._repo.count_all(), await self._repo.list_all(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return PaginatedCallsOut(
            data=[CallOut.model_validate(c) for c in calls],
            pagination=PaginationMeta(
                total=total,
                limit=limit,
                offset=offset,
                has_more=(offset + len(calls)) < total,
            ),
        )
