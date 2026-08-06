"""
app/services/dashboard_service.py
==================================
Business logic for computing dashboard summary metrics & live active calls.

Responsibilities:
  - Aggregate high-level call metrics (total calls, active count, calls today, talk time).
  - List active calls and compute live elapsed duration in seconds for each active session.

This service is read-only and stateless — instantiated per request with an AsyncSession.
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.call_repo import CallRepository
from app.schemas.dashboard import ActiveCallOut, DashboardSummaryOut


class DashboardService:
    """Service layer for dashboard metrics computation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CallRepository(session)

    async def get_summary(self) -> DashboardSummaryOut:
        """
        Compute and return high-level dashboard metrics summary.

        - total_calls: total count of all calls stored
        - active_calls_count: calls with status 'active'
        - calls_today: calls started since 00:00:00 UTC today
        - total_talk_time_seconds: total sum of duration across all calls
        """
        now = datetime.now(timezone.utc)
        today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

        total_calls = await self._repo.count_all()
        active_calls_count = await self._repo.count_by_status("active")
        calls_today = await self._repo.count_calls_started_since(today_start)
        total_talk_time = await self._repo.get_total_duration_seconds()

        return DashboardSummaryOut(
            total_calls=total_calls,
            active_calls_count=active_calls_count,
            calls_today=calls_today,
            total_talk_time_seconds=total_talk_time,
        )

    async def get_active_calls(self) -> list[ActiveCallOut]:
        """
        Retrieve calls currently in 'active' status and calculate live duration.

        Live duration is computed in seconds as:
            int((now_utc - (started_at or created_at)).total_seconds())
        """
        active_calls = await self._repo.list_active_calls()
        now = datetime.now(timezone.utc)

        result: list[ActiveCallOut] = []
        for call in active_calls:
            ref_time = call.started_at or call.created_at
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)

            elapsed_seconds = max(0, int((now - ref_time).total_seconds()))

            call_out = ActiveCallOut(
                id=call.id,
                call_sid=call.call_sid,
                from_number=call.from_number,
                to_number=call.to_number,
                status=call.status,
                direction=call.direction,
                started_at=call.started_at,
                created_at=call.created_at,
                live_duration_seconds=elapsed_seconds,
            )
            result.append(call_out)

        return result
