"""
app/api/exotel_voice.py
========================
Exotel AgentStream (Bidirectional Voice Streaming) WebSocket handler.

Replaces Twilio's TwiML webhook model with real-time audio streaming.
This is the heart of the Exotel integration.

Endpoints:
  WS  /api/v1/exotel/stream      — Main WebSocket for bidirectional audio
  GET /api/v1/exotel/ws-config    — Returns WebSocket URL for Exotel Voicebot applet
  GET /api/v1/exotel/health       — Health check for Exotel integration

Flow:
  1. Exotel opens WebSocket when call connects via Voicebot Applet
  2. Backend receives 'start' event with call metadata (CallSid, From, To)
  3. Backend streams a greeting audio (TTS) to the caller
  4. Conversation loop:
     a. Caller speaks → Exotel streams audio chunks via 'media' events
     b. Silence detected → buffer sent to STT (Deepgram)
     c. Transcribed text → AI service (NVIDIA DeepSeek)
     d. AI reply text → TTS (edge-tts) → audio chunks streamed back
  5. Exotel sends 'stop' event when call ends
  6. Backend finalizes call record in DB

WebSocket Event Protocol (from Exotel):
  connected  → WebSocket link established
  start      → Call metadata (call_sid, stream_sid, custom params)
  media      → Base64-encoded PCM audio chunks from caller
  dtmf       → Keypad button presses
  clear      → Barge-in: caller interrupted the bot
  stop       → Stream ended, call finishing

Outbound events (to Exotel):
  media      → Base64-encoded PCM audio chunks (bot response)
  clear      → Flush queued audio on Exotel side
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.services.ai_service import FALLBACK_REPLY, generate_reply
from app.services.call_service import CallService
from app.services.conversation_service import ConversationService
from app.services.stt_service import AudioBuffer, transcribe_audio_batch
from app.services.tts_service import generate_speech_base64_chunks

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Greeting spoken to the caller when the call connects
_GREETING_TEXT = "Hello! Thank you for calling. How can I help you today?"

# Fallback message when no speech is detected
_NO_SPEECH_TEXT = "I'm sorry, I didn't catch that. Could you please repeat yourself?"

# Goodbye message when the conversation times out
_GOODBYE_TEXT = "Thank you for calling. Have a great day! Goodbye."

# Silence threshold — how long to wait after last audio chunk before
# considering the user has finished speaking (seconds)
_SILENCE_THRESHOLD: float = 1.5

# Maximum duration for a single turn's audio buffer (seconds)
# Prevents infinite buffering if silence detection fails
_MAX_TURN_DURATION: float = 30.0

# Minimum audio buffer size to attempt transcription (bytes)
# Filters out very short noise bursts
_MIN_AUDIO_FOR_STT: int = 3200  # ~200ms at 8kHz/16bit


# ---------------------------------------------------------------------------
# GET /ws-config — Dynamic WebSocket URL resolver
# ---------------------------------------------------------------------------

@router.get(
    "/ws-config",
    summary="Exotel Voicebot Applet WebSocket URL resolver",
)
async def ws_config(request: Request) -> JSONResponse:
    """
    Returns the WebSocket URL for Exotel's Voicebot Applet.

    Configure the Voicebot Applet in Exotel Flow Builder to point to
    this HTTPS endpoint.  Exotel will call this to discover the WSS URL.

    Response format:
        {"url": "wss://your-domain/api/v1/exotel/stream"}
    """
    # Build WebSocket URL from the request's base URL
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.hostname)
    ws_url = f"{scheme}://{host}/api/v1/exotel/stream"

    logger.info("Exotel ws-config requested, returning URL: %s", ws_url)
    return JSONResponse({"url": ws_url})


# ---------------------------------------------------------------------------
# GET /health — Exotel integration health check
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    summary="Exotel integration health and capability verification",
)
async def exotel_health() -> dict:
    """
    Check Exotel integration readiness and account capability verification.

    Per official Exotel documentation, Voicebot Applet (bidirectional AgentStream)
    requires enterprise provisioning and is NOT enabled by default on standard trial tiers.
    """
    is_streaming_enabled = settings.exotel_streaming_enabled
    return {
        "status": "ready" if is_streaming_enabled else "streaming_blocked_pending_account_permission",
        "provider": "exotel",
        "exophone_configured": bool(settings.exotel_exophone),
        "deepgram_configured": bool(settings.deepgram_api_key),
        "streaming_capability_verified": is_streaming_enabled,
        "live_call_testing_status": (
            "READY_FOR_LIVE_CALL" if is_streaming_enabled else "BLOCKED_PENDING_EXOTEL_STREAMING_FEATURE"
        ),
        "documentation_reference": "https://developer.exotel.com/api/#voice-stream",
        "account_requirement_note": (
            "Exotel trial accounts do not include the Voicebot Applet / AgentStream by default. "
            "To enable bidirectional WebSocket streaming, request Voicebot Applet enablement from Exotel support (hello@exotel.com) "
            "and set EXOTEL_STREAMING_ENABLED=true in backend/.env once active."
        ),
    }


# ---------------------------------------------------------------------------
# WebSocket /stream — Main bidirectional audio handler
# ---------------------------------------------------------------------------

@router.websocket("/stream")
async def exotel_stream(websocket: WebSocket):
    """
    Main WebSocket endpoint for Exotel AgentStream.

    Handles the full call lifecycle:
    1. Accept connection
    2. Process incoming events (start, media, stop, clear, dtmf)
    3. Stream audio responses back to the caller
    4. Persist call + conversation data to DB
    """
    await websocket.accept()
    logger.info("Exotel AgentStream WebSocket connection accepted")

    # Per-connection state
    stream_sid: str = ""
    call_sid: str = ""
    from_number: str = ""
    to_number: str = ""
    call_db_id: uuid.UUID | None = None
    audio_buffer = AudioBuffer()
    last_audio_time: float = 0.0
    is_bot_speaking: bool = False
    silence_task: asyncio.Task | None = None

    async def _create_call_record() -> uuid.UUID | None:
        """Create a call record in the DB and return its UUID."""
        try:
            async with AsyncSessionLocal() as session:
                call_service = CallService(session)
                call = await call_service.create_call(
                    call_sid=call_sid or f"exotel-{uuid.uuid4().hex[:16]}",
                    from_number=from_number or "unknown",
                    to_number=to_number or settings.exotel_exophone or "unknown",
                    direction="inbound",
                )
                await session.commit()
                logger.info("Call record created: id=%s, sid=%s", call.id, call_sid)
                return call.id
        except Exception as exc:
            logger.exception("Failed to create call record: %s", exc)
            return None

    async def _finalize_call() -> None:
        """Mark the call as completed in the DB."""
        if not call_db_id:
            return
        try:
            async with AsyncSessionLocal() as session:
                call_service = CallService(session)
                await call_service.end_call(call_db_id)
                await session.commit()
                logger.info("Call finalized: id=%s", call_db_id)
        except Exception as exc:
            logger.warning("Failed to finalize call: %s", exc)

    async def _send_audio(text: str) -> None:
        """Generate TTS audio and stream it to the caller via WebSocket."""
        nonlocal is_bot_speaking
        if not text or not text.strip():
            return

        is_bot_speaking = True
        try:
            chunks = await generate_speech_base64_chunks(text)
            for chunk in chunks:
                if not is_bot_speaking:
                    logger.info("Bot speech playback interrupted by barge-in")
                    break
                try:
                    await websocket.send_json({
                        "event": "media",
                        "stream_sid": stream_sid,
                        "media": {
                            "payload": chunk,
                        },
                    })
                except Exception:
                    break
                # Small delay between chunks to simulate natural pacing
                await asyncio.sleep(0.02)
        except Exception as exc:
            logger.warning("Failed to send TTS audio: %s", exc)
        finally:
            is_bot_speaking = False

    async def _process_speech_turn() -> None:
        """
        Process a completed speech turn:
        1. Transcribe buffered audio (STT)
        2. Generate AI reply
        3. Stream reply audio back (TTS)
        4. Persist conversation turns to DB
        """
        nonlocal call_db_id

        if not audio_buffer.has_audio or audio_buffer.size_bytes < _MIN_AUDIO_FOR_STT:
            audio_buffer.clear()
            return

        audio_bytes = audio_buffer.get_audio()
        audio_buffer.clear()

        logger.info(
            "Processing speech turn: %d bytes, %d chunks",
            len(audio_bytes), audio_buffer.chunk_count,
        )

        # 1. Speech-to-Text
        transcript = await transcribe_audio_batch(audio_bytes)

        if not transcript or not transcript.strip():
            logger.info("Empty transcript — asking caller to repeat")
            await _send_audio(_NO_SPEECH_TEXT)
            return

        logger.info("Caller said: %r", transcript)

        # 2. Persist user turn + get history
        history = []
        if call_db_id:
            try:
                async with AsyncSessionLocal() as session:
                    conv_service = ConversationService(session)
                    await conv_service.add_message(
                        call_db_id, role="user", content=transcript,
                    )
                    history = await conv_service.get_conversation_history(call_db_id)
                    await session.commit()
            except Exception as exc:
                logger.warning("Failed to persist user turn: %s", exc)

        # 3. Generate AI reply
        ai_reply = await generate_reply(history)
        logger.info("AI reply: %r", ai_reply)

        # 4. Persist assistant turn
        if call_db_id:
            try:
                async with AsyncSessionLocal() as session:
                    conv_service = ConversationService(session)
                    await conv_service.add_message(
                        call_db_id, role="assistant", content=ai_reply,
                    )
                    await session.commit()
            except Exception as exc:
                logger.warning("Failed to persist assistant turn: %s", exc)

        # 5. Stream TTS reply back to caller
        await _send_audio(ai_reply)

    async def _silence_monitor() -> None:
        """
        Monitor for silence after the last audio chunk.
        When silence exceeds the threshold, process the buffered speech.
        """
        while True:
            await asyncio.sleep(0.2)  # check every 200ms

            if not audio_buffer.has_audio or is_bot_speaking:
                continue

            elapsed = time.monotonic() - last_audio_time
            if elapsed >= _SILENCE_THRESHOLD:
                logger.debug("Silence detected (%.1fs) — processing turn", elapsed)
                await _process_speech_turn()
            elif audio_buffer.size_bytes > _MAX_TURN_DURATION * _TARGET_BYTES_PER_SEC:
                logger.warning("Turn duration exceeded max — forcing processing")
                await _process_speech_turn()

    # Approximate bytes per second at 8kHz, 16-bit, mono
    _TARGET_BYTES_PER_SEC = 8000 * 2 * 1

    try:
        # Start silence monitor
        silence_task = asyncio.create_task(_silence_monitor())

        while True:
            raw_message = await websocket.receive_text()

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON WebSocket message")
                continue

            event = message.get("event", "")

            # ----- connected -----
            if event == "connected":
                logger.info("Exotel AgentStream: connected")

            # ----- start -----
            elif event == "start":
                start_data = message.get("start", {})
                stream_sid = (
                    start_data.get("stream_sid", "")
                    or start_data.get("streamSid", "")
                    or message.get("stream_sid", "")
                    or message.get("streamSid", "")
                )
                call_sid = (
                    start_data.get("call_sid", "")
                    or start_data.get("callSid", "")
                    or message.get("call_sid", "")
                    or message.get("callSid", "")
                )

                # Extract caller info from custom parameters or start data
                custom_params = (
                    start_data.get("custom_parameters", {})
                    or start_data.get("customParameters", {})
                )
                from_number = (
                    custom_params.get("From", "")
                    or custom_params.get("from", "")
                    or start_data.get("from", "")
                    or custom_params.get("CallFrom", "")
                )
                to_number = (
                    custom_params.get("To", "")
                    or custom_params.get("to", "")
                    or start_data.get("to", "")
                    or custom_params.get("CallTo", "")
                )

                logger.info(
                    "Exotel AgentStream started: "
                    "stream_sid=%s, call_sid=%s, from=%s, to=%s",
                    stream_sid, call_sid, from_number, to_number,
                )

                # Create call record
                call_db_id = await _create_call_record()

                # Send greeting
                await _send_audio(_GREETING_TEXT)

            # ----- media -----
            elif event == "media":
                media_data = message.get("media", {})
                payload = media_data.get("payload", "")

                if payload and not is_bot_speaking:
                    audio_buffer.add_chunk(payload)
                    last_audio_time = time.monotonic()

            # ----- dtmf -----
            elif event == "dtmf":
                digit = message.get("dtmf", {}).get("digit", "")
                logger.info("DTMF digit received: %s", digit)
                # Could handle keypad input here if needed

            # ----- clear -----
            elif event == "clear":
                # Barge-in: caller interrupted the bot
                logger.info("Barge-in detected — clearing audio")
                is_bot_speaking = False
                # Send clear event back to flush Exotel's audio queue
                try:
                    await websocket.send_json({
                        "event": "clear",
                        "stream_sid": stream_sid,
                    })
                except Exception:
                    pass

            # ----- stop -----
            elif event == "stop":
                logger.info("Exotel AgentStream stopped: call_sid=%s", call_sid)
                break

            else:
                logger.debug("Unknown WebSocket event: %s", event)

    except WebSocketDisconnect:
        logger.info("Exotel WebSocket disconnected: call_sid=%s", call_sid)
    except Exception as exc:
        logger.exception("Exotel WebSocket error: %s", exc)
    finally:
        # Cancel the silence monitor
        if silence_task and not silence_task.done():
            silence_task.cancel()
            try:
                await silence_task
            except asyncio.CancelledError:
                pass

        # Finalize the call
        await _finalize_call()

        # Close WebSocket if still open
        try:
            await websocket.close()
        except Exception:
            pass

        logger.info(
            "Exotel call session ended: call_sid=%s, db_id=%s",
            call_sid, call_db_id,
        )
