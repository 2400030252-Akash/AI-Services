"""
app/schemas/voice_agent.py
==========================
Pydantic v2 schemas for the Exotel Voice Agent Custom API integration.

Handles request parsing, field aliases (to ensure compatibility with Exotel's
variable mapping), validation, and standard response formatting.
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class VoiceAgentMessage(BaseModel):
    """A single turn in the conversation history."""
    role: str = Field(
        default="user",
        description="Speaker role: 'user' or 'assistant'.",
    )
    content: str = Field(
        default="",
        description="Text content of the message.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_message(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize role
            raw_role = str(data.get("role") or data.get("sender") or "user").lower().strip()
            if raw_role in ("user", "caller", "human", "customer"):
                role = "user"
            elif raw_role in ("assistant", "agent", "bot", "system"):
                role = "assistant"
            else:
                role = "user"

            # Normalize content
            content = str(data.get("content") or data.get("text") or data.get("message") or "")
            return {"role": role, "content": content}
        return data


class VoiceAgentAskRequest(BaseModel):
    """
    Request payload sent by Exotel Voice Agent Custom API integration.

    Supports:
    - Standard schema: {"question": "...", "conversation_id": "...", "conversation_history": [...]}
    - Common Exotel variable aliases: query, user_input, prompt, message
    - Nested parameters wrapper: {"parameters": {"question": ...}}
    """
    question: str = Field(
        ...,
        description="The caller's question or speech input.",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Optional conversation, session, or call identifier from Exotel.",
    )
    conversation_history: list[VoiceAgentMessage] = Field(
        default_factory=list,
        description="Optional list of previous conversation turns.",
    )
    api_key: str | None = Field(
        default=None,
        description="Optional API key supplied in body if the platform cannot set custom headers or URL parameters.",
    )

    @model_validator(mode="before")
    @classmethod
    def _extract_and_validate_question(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # Check for nested parameters object (common in tool-calling frameworks)
        params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}

        raw_question = (
            data.get("question")
            or params.get("question")
            or data.get("user_input")
            or params.get("user_input")
            or data.get("query")
            or params.get("query")
            or data.get("prompt")
            or params.get("prompt")
            or data.get("message")
            or params.get("message")
        )

        if raw_question is None or not str(raw_question).strip():
            raise ValueError("Question is required and cannot be empty.")

        data["question"] = str(raw_question).strip()

        # Normalize conversation_id if present in nested params
        if not data.get("conversation_id"):
            data["conversation_id"] = (
                params.get("conversation_id")
                or data.get("call_sid")
                or params.get("call_sid")
                or data.get("session_id")
                or params.get("session_id")
            )

        return data


class VoiceAgentAskResponse(BaseModel):
    """
    JSON response returned to the Exotel Voice Agent.

    Contains top-level 'answer' string for direct variable extraction in Exotel.
    """
    answer: str = Field(
        ...,
        description="The AI-generated natural spoken response.",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Echoes back the conversation identifier if provided.",
    )
    status: str = Field(
        default="success",
        description="Execution status.",
    )
