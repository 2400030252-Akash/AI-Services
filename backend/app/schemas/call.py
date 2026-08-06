"""
app/schemas/call.py
===================
Pydantic v2 schemas for the calls endpoints.

Covers:
  - CallStatus / CallDirection enums (validated at API boundary)
  - CallResponse       — single call row
  - CallDetailResponse — call row + embedded conversation turns
  - PaginatedCallsResponse — list endpoint wrapper with pagination metadata
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Value-set enums  (mirrors CALL_STATUS / CALL_DIRECTION in call.py model)
# ---------------------------------------------------------------------------

class CallStatus(str):
    QUEUED      = "queued"
    RINGING     = "ringing"
    IN_PROGRESS = "in-progress"
    ACTIVE      = "active"       # service-layer alias for in-progress
    COMPLETED   = "completed"
    FAILED      = "failed"


CallStatusLiteral = Literal[
    "queued", "ringing", "in-progress", "active", "completed", "failed"
]
CallDirectionLiteral = Literal["inbound", "outbound"]
SortOrderLiteral = Literal["asc", "desc"]


# ---------------------------------------------------------------------------
# Conversation turn (embedded inside CallDetailResponse)
# ---------------------------------------------------------------------------

class ConversationTurnOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Single call response
# ---------------------------------------------------------------------------

class CallOut(BaseModel):
    """
    Serialised representation of a calls row.
    Returned by both the list and detail endpoints.
    """
    id: uuid.UUID
    call_sid: str
    from_number: str
    to_number: str
    status: str
    direction: str
    duration: int | None = Field(
        default=None,
        description="Call duration in seconds. Null until the call ends.",
    )
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CallDetailOut(CallOut):
    """
    Full call detail — includes embedded conversation turns.
    Returned only by GET /calls/{id}.
    """
    conversations: list[ConversationTurnOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Paginated list wrapper
# ---------------------------------------------------------------------------

class PaginationMeta(BaseModel):
    total: int = Field(description="Total number of calls matching the query.")
    limit: int
    offset: int
    has_more: bool


class PaginatedCallsOut(BaseModel):
    """Response shape for GET /calls."""
    data: list[CallOut]
    pagination: PaginationMeta
