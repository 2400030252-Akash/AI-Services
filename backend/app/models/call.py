"""
app/models/call.py
==================
Call and Conversation ORM models.

Schema (from architecture doc):

calls:
    id           UUID PK
    call_sid     VARCHAR   Twilio CallSid, unique, indexed
    from_number  VARCHAR   caller's E.164 phone number
    to_number    VARCHAR   dialled E.164 phone number
    status       VARCHAR   queued | ringing | in-progress | completed | failed
    direction    VARCHAR   inbound | outbound
    duration     INTEGER   seconds, nullable (unknown until call ends)
    started_at   TIMESTAMPTZ nullable
    ended_at     TIMESTAMPTZ nullable
    created_at   TIMESTAMPTZ server default now()

conversations:
    id         UUID PK
    call_id    UUID FK → calls.id  (CASCADE delete)
    role       VARCHAR   "user" | "assistant"
    content    TEXT
    created_at TIMESTAMPTZ server default now()
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UUIDPrimaryKey


# ---------------------------------------------------------------------------
# Call status / direction literals (kept as plain strings so they stay
# flexible for DB-level queries; use Python enums in Pydantic schemas).
# ---------------------------------------------------------------------------
CALL_STATUS = ("queued", "ringing", "in-progress", "completed", "failed")
CALL_DIRECTION = ("inbound", "outbound")


class Call(UUIDPrimaryKey, Base):
    """
    Represents a single Twilio voice call leg.
    One call has many Conversation turn rows.
    """
    __tablename__ = "calls"

    call_sid: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Twilio CallSid — globally unique per call.",
    )
    from_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Caller phone number in E.164 format.",
    )
    to_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Dialled phone number in E.164 format.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="queued",
        comment="queued | ringing | in-progress | completed | failed",
    )
    direction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="inbound | outbound",
    )
    duration: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Call duration in seconds; null until call ends.",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship — one call → many conversation turns
    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation",
        back_populates="call",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Call id={self.id} sid={self.call_sid!r} status={self.status!r}>"


class Conversation(UUIDPrimaryKey, Base):
    """
    A single turn in the AI conversation for a call.
    role is 'user' (caller speech → text) or 'assistant' (AI response).
    """
    __tablename__ = "conversations"

    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'user' or 'assistant'",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship — many conversation turns → one call
    call: Mapped[Call] = relationship(
        "Call",
        back_populates="conversations",
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} call_id={self.call_id} role={self.role!r}>"
