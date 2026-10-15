"""
app/services/stt_service.py
============================
Speech-to-Text service using Deepgram's real-time streaming API.

Converts raw PCM audio chunks from Exotel's AgentStream into text
transcriptions.  Designed for real-time use inside the WebSocket handler.

Public surface
--------------
    STTService(api_key)
        .transcribe_audio(audio_bytes) → str | None

        Buffers incoming PCM audio and sends it to Deepgram.
        Returns transcribed text when a final transcript is available,
        or None while still accumulating partial results.

    transcribe_audio_batch(audio_bytes) → str

        One-shot batch transcription for buffered audio.
        Simpler but higher-latency alternative to streaming.

Design decisions
----------------
- Uses Deepgram's Nova-2 model for best accuracy + speed balance.
- Configured for telephony audio: 8kHz, 16-bit, mono (linear16).
- Smart endpointing at 500ms silence to detect end of speech.
- Falls back to a batch transcription if the streaming connection
  is not available.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Final

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Deepgram model optimised for phone calls
_MODEL: Final[str] = "nova-2"

# Audio format from Exotel AgentStream
_SAMPLE_RATE: Final[int] = 8000
_ENCODING: Final[str] = "linear16"
_CHANNELS: Final[int] = 1

# Silence threshold for endpointing (ms)
_ENDPOINTING_MS: Final[int] = 500


# ---------------------------------------------------------------------------
# Batch transcription (simpler, higher latency)
# ---------------------------------------------------------------------------

async def transcribe_audio_batch(audio_bytes: bytes) -> str:
    """
    Transcribe a complete audio buffer using Deepgram's REST API.

    Parameters
    ----------
    audio_bytes:
        Raw PCM audio bytes (8kHz, 16-bit, mono).

    Returns
    -------
    str
        Transcribed text, or empty string on failure.
    """
    if not audio_bytes:
        return ""

    api_key = settings.deepgram_api_key
    if not api_key:
        logger.error("DEEPGRAM_API_KEY not configured — cannot transcribe audio")
        return ""

    try:
        import httpx

        url = "https://api.deepgram.com/v1/listen"
        params = {
            "model": _MODEL,
            "language": "en",
            "encoding": _ENCODING,
            "sample_rate": str(_SAMPLE_RATE),
            "channels": str(_CHANNELS),
            "punctuate": "true",
            "smart_format": "true",
            "endpointing": str(_ENDPOINTING_MS),
        }
        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/octet-stream",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                params=params,
                headers=headers,
                content=audio_bytes,
            )
            response.raise_for_status()
            data = response.json()

        # Extract transcript from Deepgram response
        transcript = (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )
        if transcript:
            logger.info(
                "STT transcription complete",
                extra={"chars": len(transcript), "audio_bytes": len(audio_bytes)},
            )
        return transcript.strip()

    except Exception as exc:
        logger.exception("STT batch transcription failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Audio buffer for accumulating chunks during a speech turn
# ---------------------------------------------------------------------------

class AudioBuffer:
    """
    Accumulates raw PCM audio chunks from Exotel's media events.

    Call ``add_chunk()`` for each incoming media payload and
    ``get_audio()`` to retrieve the full buffer.  ``clear()`` resets
    for the next turn.
    """

    def __init__(self) -> None:
        self._buffer = io.BytesIO()
        self._chunk_count = 0

    def add_chunk(self, base64_payload: str) -> None:
        """Decode a base64-encoded audio chunk and append to buffer."""
        try:
            raw = base64.b64decode(base64_payload)
            self._buffer.write(raw)
            self._chunk_count += 1
        except Exception as exc:
            logger.warning("Failed to decode audio chunk: %s", exc)

    def get_audio(self) -> bytes:
        """Return the accumulated raw PCM bytes."""
        return self._buffer.getvalue()

    def clear(self) -> None:
        """Reset the buffer for a new speech turn."""
        self._buffer = io.BytesIO()
        self._chunk_count = 0

    @property
    def size_bytes(self) -> int:
        """Current buffer size in bytes."""
        return self._buffer.tell()

    @property
    def chunk_count(self) -> int:
        """Number of chunks added so far."""
        return self._chunk_count

    @property
    def has_audio(self) -> bool:
        """Whether the buffer contains any audio data."""
        return self._buffer.tell() > 0
