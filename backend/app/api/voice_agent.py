"""
app/api/voice_agent.py
======================
HTTP endpoint for Exotel Voice Agent Custom API Integration.

Mounts at:
    POST /api/v1/voice-agent/ask

Connects Exotel Voice Agents (which handle telephony, STT, and TTS)
directly to our backend's NVIDIA DeepSeek AI service and live news retrieval.

Security:
- Guarded by ``validate_voice_agent_auth`` (X-API-Key or Bearer token).
- Never leaks internal credentials, API keys, or database details.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Security, status

from app.api.deps_voice_agent import validate_voice_agent_auth
from app.schemas.conversation import LLMMessage
from app.schemas.voice_agent import VoiceAgentAskRequest, VoiceAgentAskResponse
from app.services.ai_service import FALLBACK_REPLY, generate_reply

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum execution timeout for AI reply generation (seconds)
_ASK_TIMEOUT_SECONDS: float = 30.0


@router.post(
    "/ask/{auth_token}",
    response_model=VoiceAgentAskResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    dependencies=[Security(validate_voice_agent_auth)],
)
@router.post(
    "/{auth_token}/ask",
    response_model=VoiceAgentAskResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    dependencies=[Security(validate_voice_agent_auth)],
)
@router.post(
    "/ask",
    response_model=VoiceAgentAskResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask AI Assistant (Exotel Voice Agent Custom API Integration)",
    description=(
        "Endpoint invoked by Exotel Voice Agents to generate conversational answers. "
        "Reuses NVIDIA DeepSeek and real-time news retrieval. "
        "Supports X-API-Key, Authorization: Bearer/Basic, URL query (?api_key=...), or path token (/ask/{auth_token})."
    ),
    dependencies=[Security(validate_voice_agent_auth)],
)
async def ask_voice_agent(
    payload: VoiceAgentAskRequest,
    auth_token: str | None = None,
) -> VoiceAgentAskResponse:
    """
    Process a question from an Exotel Voice Agent:
    1. Validates the question and history.
    2. Reconstructs the conversation context (LLMMessage list).
    3. Triggers live news retrieval if the question asks about breaking/current events.
    4. Generates an AI reply via NVIDIA DeepSeek.
    5. Returns {"answer": "...", "conversation_id": "...", "status": "success"}.
    """
    cleaned_question = payload.question.strip()
    if not cleaned_question:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question is required and cannot be empty.",
        )

    t_start = time.perf_counter()
    logger.info(
        "Exotel voice agent query received: question_len=%d, conv_id=%s, history_turns=%d",
        len(cleaned_question),
        payload.conversation_id or "none",
        len(payload.conversation_history),
    )

    # 1. Convert previous turns into LLMMessage objects
    llm_history: list[LLMMessage] = []
    for turn in payload.conversation_history:
        turn_text = turn.content.strip()
        if turn_text:
            # turn.role is already normalized to "user" or "assistant"
            role = "assistant" if turn.role == "assistant" else "user"
            llm_history.append(LLMMessage(role=role, content=turn_text))

    # 2. Append the current question as the latest user turn
    llm_history.append(LLMMessage(role="user", content=cleaned_question))

    # 3. Call AI service (which includes news intent detection & retrieval)
    try:
        reply = await asyncio.wait_for(
            generate_reply(llm_history),
            timeout=_ASK_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Voice agent request timed out after %.1fs for conv_id=%s",
            _ASK_TIMEOUT_SECONDS,
            payload.conversation_id,
        )
        reply = FALLBACK_REPLY
    except Exception as exc:
        logger.exception("Unexpected error generating voice agent reply: %s", exc)
        reply = FALLBACK_REPLY

    latency_ms = int((time.perf_counter() - t_start) * 1000)
    logger.info(
        "Exotel voice agent reply completed: latency=%dms, reply_chars=%d, conv_id=%s",
        latency_ms,
        len(reply),
        payload.conversation_id or "none",
    )

    return VoiceAgentAskResponse(
        answer=reply,
        conversation_id=payload.conversation_id,
        status="success",
    )
