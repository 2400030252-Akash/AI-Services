"""
app/database/repositories/conversation_repo.py
===============================================
Repository for the ``conversations`` table.

Conversation turns belong to a Call (FK call_id → calls.id).
Deleting a Call cascades to its Conversations at the DB level.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import Conversation


class ConversationRepository:
    """Data-access layer for Conversation (AI turn) records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        call_id: uuid.UUID,
        role: str,
        content: str,
    ) -> Conversation:
        """
        Append a new conversation turn to a call.

        ``role`` must be 'user' or 'assistant'.
        The caller is responsible for committing the transaction.
        """
        turn = Conversation(call_id=call_id, role=role, content=content)
        self._session.add(turn)
        await self._session.flush()
        await self._session.refresh(turn)
        return turn

    async def bulk_create(
        self,
        turns: list[dict],
    ) -> list[Conversation]:
        """
        Insert multiple turns in a single flush.

        Each dict in ``turns`` must have: call_id, role, content.
        Useful when seeding or replaying a conversation.
        """
        objects = [Conversation(**t) for t in turns]
        self._session.add_all(objects)
        await self._session.flush()
        for obj in objects:
            await self._session.refresh(obj)
        return objects

    # ------------------------------------------------------------------
    # Read — by call
    # ------------------------------------------------------------------

    async def list_by_call(
        self,
        call_id: uuid.UUID,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Conversation]:
        """
        Return all conversation turns for a call in chronological order.

        ``limit`` defaults to 200 which is well above the practical
        context window for a single voice call.
        """
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.call_id == call_id)
            .order_by(Conversation.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Read — single row
    # ------------------------------------------------------------------

    async def get_by_id(self, conversation_id: uuid.UUID) -> Conversation | None:
        """Return a single Conversation turn by its UUID, or None."""
        result = await self._session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()
