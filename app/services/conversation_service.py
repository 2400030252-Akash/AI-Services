"""
app/services/conversation_service.py
======================================
Business logic for conversation turn management.

Public surface (consumed internally by the AI service module and by the
admin-facing transcript endpoint):

  add_message(call_id, role, content)
      → persists a single turn; caller must commit.

  get_conversation_history(call_id)
      → returns turns as List[LLMMessage] — ready for the AI service.

  get_transcript(call_id)
      → returns the full ConversationTranscriptOut response model,
        including both display-friendly turns and LLM-ready messages.
        Validates that the parent call exists first (raises 404 if not).

Design decisions:
  - Service does NOT commit. Route handlers / AI service own the boundary.
  - Call existence is validated before transcript access so the 404 is
    clear ("call not found") rather than silently returning an empty list.
  - The LLM message list is built from the same query result — no second
    DB round-trip.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.call_repo import CallRepository
from app.database.repositories.conversation_repo import ConversationRepository
from app.models.call import Conversation
from app.schemas.call import ConversationTurnOut
from app.schemas.conversation import ConversationTranscriptOut, LLMMessage


class ConversationService:
    """
    Conversation service — instantiated per request with a DB session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._conv_repo = ConversationRepository(session)
        self._call_repo = CallRepository(session)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _assert_call_exists(self, call_id: uuid.UUID) -> None:
        """Raise HTTP 404 if the parent call does not exist."""
        call = await self._call_repo.get_by_id(call_id)
        if call is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": True,
                    "message": f"Call '{call_id}' not found.",
                    "code": "CALL_NOT_FOUND",
                },
            )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def add_message(
        self,
        call_id: uuid.UUID,
        role: Literal["user", "assistant"],
        content: str,
    ) -> Conversation:
        """
        Append a single conversation turn to a call.

        Parameters
        ----------
        call_id:
            UUID of the parent Call row.
        role:
            ``"user"``      — transcribed caller speech
            ``"assistant"`` — AI-generated response
        content:
            Raw text of the message.

        Returns
        -------
        Conversation
            The newly created (flushed but uncommitted) turn.

        Notes
        -----
        The caller MUST commit the session after this returns.
        No call-existence check is performed here — the DB foreign key
        constraint will reject an invalid call_id naturally.
        """
        if role not in ("user", "assistant"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": True,
                    "message": f"Invalid role '{role}'. Must be 'user' or 'assistant'.",
                    "code": "INVALID_ROLE",
                },
            )

        turn = await self._conv_repo.create(
            call_id=call_id,
            role=role,
            content=content.strip(),
        )
        return turn

    # ------------------------------------------------------------------
    # Read — LLM interface
    # ------------------------------------------------------------------

    async def get_conversation_history(
        self,
        call_id: uuid.UUID,
    ) -> list[LLMMessage]:
        """
        Return all turns for a call as a list of ``{role, content}`` dicts.

        This is the format expected by OpenAI-compatible chat completion
        APIs (including NVIDIA/DeepSeek).  Pass the result directly to
        the AI service as the ``messages`` parameter.

        Returns an empty list if the call has no turns yet.
        No 404 check — callers in the AI pipeline already hold a valid
        call object and don't need the extra DB round-trip.
        """
        turns = await self._conv_repo.list_by_call(call_id)
        return [LLMMessage(role=t.role, content=t.content) for t in turns]

    # ------------------------------------------------------------------
    # Read — admin transcript endpoint
    # ------------------------------------------------------------------

    async def get_transcript(
        self,
        call_id: uuid.UUID,
    ) -> ConversationTranscriptOut:
        """
        Return the full conversation transcript for a call.

        Validates that the parent call exists (HTTP 404 if not), then
        fetches all turns in chronological order and builds both the
        display-friendly ``turns`` list and the bare ``llm_messages`` list
        in a single query.
        """
        await self._assert_call_exists(call_id)

        turns = await self._conv_repo.list_by_call(call_id)

        turn_out = [ConversationTurnOut.model_validate(t) for t in turns]
        llm_msgs = [LLMMessage(role=t.role, content=t.content) for t in turns]

        return ConversationTranscriptOut(
            call_id=call_id,
            turn_count=len(turns),
            turns=turn_out,
            llm_messages=llm_msgs,
        )
