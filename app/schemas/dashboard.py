"""
app/schemas/dashboard.py
========================
Pydantic v2 schemas for dashboard summary & active calls endpoints.

Covers:
  - DashboardSummaryOut  — High-level call metrics summary
  - ActiveCallOut        — Single active call with calculated live duration
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DashboardSummaryOut(BaseModel):
    """Response model for GET /api/v1/dashboard/summary."""

    total_calls: int = Field(
        description="Total count of all calls stored in the database."
    )
    active_calls_count: int = Field(
        description="Count of calls currently in 'active' status."
    )
    calls_today: int = Field(
        description="Count of calls started today (UTC midnight to present)."
    )
    total_talk_time_seconds: int = Field(
        description="Sum of all completed call durations in seconds."
    )


class ActiveCallOut(BaseModel):
    """Response model for single call item in GET /api/v1/dashboard/active-calls."""

    id: uuid.UUID
    call_sid: str
    from_number: str
    to_number: str
    status: str
    direction: str
    started_at: datetime | None = None
    created_at: datetime
    live_duration_seconds: int = Field(
        description="Elapsed seconds since the call started."
    )

    model_config = {"from_attributes": True}
