"""
app/services/tts_service.py
============================
Text-to-Speech service using edge-tts.

Converts AI reply text into raw PCM audio bytes suitable for streaming
back through Exotel's AgentStream WebSocket.

Public surface
--------------
    generate_speech(text, voice=...) → bytes

        Convert plain text to raw PCM audio (8kHz, 16-bit, mono).
        Returns bytes ready to be base64-encoded and sent via WebSocket.

    generate_speech_base64_chunks(text, voice=..., chunk_size=...) → list[str]

        Same as above, but returns a list of base64-encoded chunks
        suitable for direct inclusion in Exotel media event payloads.

Design decisions
----------------
- **edge-tts** is free, produces natural-sounding speech, and requires
  no API key.  Perfect for trial/MVP.  Can be swapped for Google Cloud
  TTS or ElevenLabs later by changing only this file.
- Audio is generated as MP3 by edge-tts and then converted to raw PCM
  (8kHz, 16-bit, mono) to match Exotel's expected format.
- Conversion uses the Python standard library ``audioop`` (deprecated in
  3.13) or a simple raw conversion path.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import struct
import tempfile
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default voice — Indian English, female, natural sounding
DEFAULT_VOICE: Final[str] = "en-IN-NeerjaNeural"

# Target audio format for Exotel AgentStream
# Exotel specification: Raw Linear PCM (slin8), 16-bit, little-endian, mono.
_TARGET_SAMPLE_RATE: Final[int] = 8000
_TARGET_CHANNELS: Final[int] = 1
_TARGET_SAMPLE_WIDTH: Final[int] = 2  # 16-bit = 2 bytes

# Exotel AgentStream chunk size constraints:
# - Minimum chunk size: 3.2 KB (3200 bytes, ~200ms at 8kHz/16-bit/mono)
# - Maximum chunk size: 100 KB
# - Must be an exact multiple of 320 bytes (e.g. 3200 = 10 * 320 bytes)
_EXOTEL_MIN_CHUNK_BYTES: Final[int] = 3200
_EXOTEL_CHUNK_ALIGNMENT: Final[int] = 320
_DEFAULT_CHUNK_SIZE: Final[int] = 3200  # 3.2 KB chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _edge_tts_to_raw_pcm(text: str, voice: str) -> bytes:
    """
    Generate speech from text using edge-tts and convert to raw PCM.

    edge-tts outputs MP3.  We convert to raw PCM (8kHz, 16-bit, mono)
    using a subprocess call to ffmpeg if available, otherwise fall back
    to the edge-tts raw output.
    """
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)

    # Collect MP3 bytes from edge-tts
    mp3_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buffer.write(chunk["data"])

    mp3_bytes = mp3_buffer.getvalue()
    if not mp3_bytes:
        logger.warning("edge-tts returned empty audio for text: %r", text[:50])
        return b""

    # Convert MP3 → raw PCM using ffmpeg
    pcm_bytes = await _mp3_to_pcm_ffmpeg(mp3_bytes)
    if pcm_bytes:
        return pcm_bytes

    # Fallback: return empty if ffmpeg not available
    logger.error(
        "ffmpeg not available for MP3→PCM conversion. "
        "Install ffmpeg: https://ffmpeg.org/download.html"
    )
    return b""


async def _mp3_to_pcm_ffmpeg(mp3_bytes: bytes) -> bytes | None:
    """
    Convert MP3 bytes to raw PCM (8kHz, 16-bit, mono) using ffmpeg.

    Returns None if ffmpeg is not available or conversion fails.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", "pipe:0",          # read from stdin
            "-f", "s16le",           # raw signed 16-bit little-endian
            "-ar", str(_TARGET_SAMPLE_RATE),
            "-ac", str(_TARGET_CHANNELS),
            "-acodec", "pcm_s16le",
            "pipe:1",                # write to stdout
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=mp3_bytes),
            timeout=10.0,
        )

        if process.returncode != 0:
            logger.warning(
                "ffmpeg conversion failed (code %d): %s",
                process.returncode,
                stderr.decode("utf-8", errors="replace")[:200],
            )
            return None

        return stdout

    except FileNotFoundError:
        logger.debug("ffmpeg not found on PATH")
        return None
    except asyncio.TimeoutError:
        logger.warning("ffmpeg conversion timed out")
        return None
    except Exception as exc:
        logger.warning("ffmpeg conversion error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_speech(
    text: str,
    voice: str = DEFAULT_VOICE,
) -> bytes:
    """
    Convert text to raw PCM audio bytes (8kHz, 16-bit, mono).

    Parameters
    ----------
    text:
        Plain text to convert to speech.
    voice:
        edge-tts voice identifier.  Defaults to Indian English female.

    Returns
    -------
    bytes
        Raw PCM audio bytes, or empty bytes on failure.
    """
    if not text or not text.strip():
        return b""

    try:
        pcm = await _edge_tts_to_raw_pcm(text.strip(), voice)
        if pcm:
            logger.info(
                "TTS speech generated",
                extra={
                    "text_chars": len(text),
                    "audio_bytes": len(pcm),
                    "voice": voice,
                },
            )
        return pcm
    except Exception as exc:
        logger.exception("TTS generation failed: %s", exc)
        return b""


async def generate_speech_base64_chunks(
    text: str,
    voice: str = DEFAULT_VOICE,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> list[str]:
    """
    Convert text to a list of base64-encoded PCM audio chunks.

    Each chunk is sized for Exotel's WebSocket media event format.
    Chunks are multiples of ``chunk_size`` bytes (default 640 = 40ms).

    Parameters
    ----------
    text:
        Plain text to convert to speech.
    voice:
        edge-tts voice identifier.
    chunk_size:
        Size of each audio chunk in bytes.  Must be a multiple of
        320 bytes (Exotel requirement).

    Returns
    -------
    list[str]
        List of base64-encoded audio chunk strings.
    """
    pcm = await generate_speech(text, voice)
    if not pcm:
        return []

    # Enforce Exotel AgentStream constraints:
    # 1. Minimum chunk size: 3200 bytes (3.2 KB)
    # 2. Must be an exact multiple of 320 bytes
    if chunk_size < _EXOTEL_MIN_CHUNK_BYTES:
        chunk_size = _EXOTEL_MIN_CHUNK_BYTES
    if chunk_size % _EXOTEL_CHUNK_ALIGNMENT != 0:
        chunk_size = (chunk_size // _EXOTEL_CHUNK_ALIGNMENT) * _EXOTEL_CHUNK_ALIGNMENT

    chunks: list[str] = []
    for offset in range(0, len(pcm), chunk_size):
        chunk_bytes = pcm[offset : offset + chunk_size]
        # Pad last chunk if needed
        if len(chunk_bytes) < chunk_size:
            chunk_bytes += b"\x00" * (chunk_size - len(chunk_bytes))
        chunks.append(base64.b64encode(chunk_bytes).decode("ascii"))

    logger.debug(
        "TTS chunked into %d pieces (%d bytes each)",
        len(chunks),
        chunk_size,
    )
    return chunks
