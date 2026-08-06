"""
app/api/voice.py
================
Twilio Voice Webhook router — mounts at /api/v1/voice.

All endpoints handle form-encoded webhooks sent directly from Twilio.
Signature validation is applied via ``Depends(validate_twilio_signature)``.

Endpoints:
  POST /api/v1/voice/incoming     — Handles incoming call setup & initial greeting
  POST /api/v1/voice/respond      — Handles caller speech recognition & AI response loop
  POST /api/v1/voice/call-status  — Status callback for call lifecycle updates (completed/failed)
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.voice_response import Gather, VoiceResponse

from app.api.deps_twilio import validate_twilio_signature
from app.database.repositories.call_repo import CallRepository
from app.database.session import get_db
from app.services.ai_service import FALLBACK_REPLY, generate_reply
from app.services.call_service import CallService
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

router = APIRouter()

# Helper for TwiML XML responses
def _twiml_response(response: VoiceResponse) -> Response:
    return Response(content=str(response), media_type="application/xml")


# ---------------------------------------------------------------------------
# POST /voice  (Incoming Call)
# ---------------------------------------------------------------------------
@router.post(
    "/voice",
    status_code=status.HTTP_200_OK,
    summary="Twilio incoming call webhook",
    response_class=Response,
)
async def incoming_call(
    request: Request,
    CallSid: Annotated[str, Form(...)],
    From: Annotated[str, Form(...)],
    To: Annotated[str, Form(...)],
    Direction: Annotated[str, Form()] = "inbound",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(validate_twilio_signature),
) -> Response:
    """
    Called when an incoming call arrives at the Twilio phone number.

    1. Creates a call record in DB with status "active".
    2. Responds with TwiML greeting and a <Gather input="speech"> prompt.
    """
    logger.info("Incoming call received from Twilio: CallSid=%s, From=%s", CallSid, From)

    # Create call record
    call_service = CallService(db)
    await call_service.create_call(
        call_sid=CallSid,
        from_number=From,
        to_number=To,
        direction=Direction,
    )
    await db.commit()

    # Build TwiML response
    twiml = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/api/v1/voice/respond",
        method="POST",
        speech_timeout="auto",
        timeout=5,
    )
    gather.say("Hello! Thank you for calling. How can I help you today?")
    twiml.append(gather)

    # Fallback if gather times out with no user input
    twiml.say("We haven't received any response. Thank you for calling. Goodbye!")
    twiml.hangup()

    return _twiml_response(twiml)


# ---------------------------------------------------------------------------
# POST /respond  (Speech Recognition Callback)
# ---------------------------------------------------------------------------
@router.post(
    "/respond",
    status_code=status.HTTP_200_OK,
    summary="Twilio speech recognition response handler",
    response_class=Response,
)
async def process_speech(
    request: Request,
    CallSid: Annotated[str, Form(...)],
    SpeechResult: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(validate_twilio_signature),
) -> Response:
    """
    Called by Twilio when the caller finishes speaking.

    1. Looks up active call by CallSid.
    2. Handles empty/unclear speech input gracefully.
    3. Persists user transcript turn to DB.
    4. Generates AI response using DeepSeek via NVIDIA API.
    5. Persists AI response turn to DB.
    6. Returns TwiML <Say> with AI reply and another <Gather> loop.
    """
    logger.info("Speech received for CallSid=%s: %r", CallSid, SpeechResult)

    call_repo = CallRepository(db)
    call = await call_repo.get_by_sid(CallSid)

    twiml = VoiceResponse()

    if not call:
        logger.error("Call object not found for CallSid=%s", CallSid)
        twiml.say("I'm sorry, an error occurred with this call session. Goodbye.")
        twiml.hangup()
        return _twiml_response(twiml)

    cleaned_speech = (SpeechResult or "").strip()

    if not cleaned_speech:
        logger.warning("Empty or unclear speech result for CallSid=%s", CallSid)
        gather = Gather(
            input="speech",
            action="/api/v1/voice/respond",
            method="POST",
            speech_timeout="auto",
            timeout=5,
        )
        gather.say("I'm sorry, I didn't catch that. Could you please repeat yourself?")
        twiml.append(gather)
        twiml.say("We haven't received any input. Goodbye!")
        twiml.hangup()
        return _twiml_response(twiml)

    # Process valid user speech
    conv_service = ConversationService(db)

    # Add caller turn
    await conv_service.add_message(call.id, role="user", content=cleaned_speech)

    # Retrieve conversation history
    history = await conv_service.get_conversation_history(call.id)

    # Generate AI reply
    ai_reply = await generate_reply(history)

    # Add assistant turn
    await conv_service.add_message(call.id, role="assistant", content=ai_reply)

    # Commit both turns
    await db.commit()

    # Respond with TwiML
    gather = Gather(
        input="speech",
        action="/api/v1/voice/respond",
        method="POST",
        speech_timeout="auto",
        timeout=5,
    )
    gather.say(ai_reply)
    twiml.append(gather)

    # Fallback if no further user speech is heard
    twiml.say("Thank you for calling. Have a great day! Goodbye.")
    twiml.hangup()

    return _twiml_response(twiml)


# ---------------------------------------------------------------------------
# POST /call-status  (Twilio Call Status Callback)
# ---------------------------------------------------------------------------
@router.post(
    "/call-status",
    status_code=status.HTTP_200_OK,
    summary="Twilio call status lifecycle callback",
    response_class=Response,
)
async def call_status_callback(
    request: Request,
    CallSid: Annotated[str, Form(...)],
    CallStatus: Annotated[str, Form(...)],
    db: AsyncSession = Depends(get_db),
    _: None = Depends(validate_twilio_signature),
) -> Response:
    """
    Called by Twilio when the status of a call changes (e.g. completed, failed).

    Updates the Call record status, ended_at, and duration.
    """
    logger.info("Call status update received: CallSid=%s, CallStatus=%s", CallSid, CallStatus)

    call_repo = CallRepository(db)
    call = await call_repo.get_by_sid(CallSid)

    if call and call.status not in ("completed", "failed"):
        call_service = CallService(db)
        if CallStatus in ("completed", "canceled"):
            await call_service.end_call(call.id)
        elif CallStatus in ("failed", "busy", "no-answer"):
            await call_service.mark_call_failed(call.id)
        await db.commit()

    # Twilio status callback expects a simple 200 OK TwiML or 200 OK empty/JSON
    twiml = VoiceResponse()
    return _twiml_response(twiml)
