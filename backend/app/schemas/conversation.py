"""
app/schemas/conversation.py
============================
Pydantic v2 schemas for conversation / transcript endpoints.

ConversationTurnOut is already defined in app.schemas.call and re-exported
here for backwards compatibility.  This file adds the transcript response
wrapper and the LLM-ready message format.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Re-export so downstream code can import from one consistent location
from app.schemas.call import ConversationTurnOut  # noqa: F401


# ---------------------------------------------------------------------------
# LLM-ready message dict
# Used by get_conversation_history() → passed directly to AI service
# ---------------------------------------------------------------------------

class LLMMessage(BaseModel):
    """
    A single message in the format expected by OpenAI-compatible chat APIs
    (including NVIDIA/DeepSeek).

    ``role`` is either ``"user"`` or ``"assistant"``.
    ``content`` is the raw text of the message.
    """
    role: Literal["user", "assistant"]
    content: str


# ---------------------------------------------------------------------------
# Transcript response — returned by GET /calls/{id}/conversation
# ---------------------------------------------------------------------------

class ConversationTranscriptOut(BaseModel):
    """
    Full transcript for a single call.

    ``turns``          — ordered list of all conversation turns, suitable
                         for display in the admin UI.
    ``llm_messages``   — same turns in the bare {role, content} format
                         ready to be passed to the AI service.
    ``turn_count``     — total number of turns (convenience field).
    """
    call_id: uuid.UUID
    turn_count: int = Field(description="Total number of conversation turns.")
    turns: list[ConversationTurnOut] = Field(
        description="Full turn list with metadata (id, role, content, created_at).",
    )
    llm_messages: list[LLMMessage] = Field(
        description=(
            "Bare {role, content} list — ready to pass to an OpenAI-compatible "
            "chat completions endpoint."
        ),
    )
