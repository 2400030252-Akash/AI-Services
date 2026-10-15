"""
tests/test_tts_service.py
=========================
Unit tests for app/services/tts_service.py.
Validates audio formatting, Exotel chunk constraints (>= 3.2KB, multiple of 320),
and padding with silence.
"""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch
import pytest

from app.services.tts_service import (
    generate_speech,
    generate_speech_base64_chunks,
    _EXOTEL_MIN_CHUNK_BYTES,
    _EXOTEL_CHUNK_ALIGNMENT,
)


@pytest.mark.asyncio
async def test_generate_speech_empty_text():
    assert await generate_speech("") == b""
    assert await generate_speech("   ") == b""
    assert await generate_speech_base64_chunks("") == []


@pytest.mark.asyncio
async def test_generate_speech_base64_chunks_exotel_constraints():
    # Simulate 7000 bytes of raw PCM audio (approx 437ms at 8kHz 16-bit mono)
    mock_pcm = b"\x01\x02" * 3500

    with patch("app.services.tts_service.generate_speech", new_callable=AsyncMock, return_value=mock_pcm):
        chunks = await generate_speech_base64_chunks("Hello test", chunk_size=3200)

    assert len(chunks) > 0
    for chunk_b64 in chunks:
        raw_bytes = base64.b64decode(chunk_b64)
        # Exotel requirement 1: Every chunk must be >= 3.2 KB (3200 bytes)
        assert len(raw_bytes) >= _EXOTEL_MIN_CHUNK_BYTES
        # Exotel requirement 2: Every chunk must be an exact multiple of 320 bytes
        assert len(raw_bytes) % _EXOTEL_CHUNK_ALIGNMENT == 0


@pytest.mark.asyncio
async def test_generate_speech_small_audio_padded_to_exotel_minimum():
    # Only 500 bytes of audio generated (smaller than 3200 bytes)
    mock_pcm = b"\x05" * 500

    with patch("app.services.tts_service.generate_speech", new_callable=AsyncMock, return_value=mock_pcm):
        chunks = await generate_speech_base64_chunks("Tiny text")

    assert len(chunks) == 1
    raw = base64.b64decode(chunks[0])
    # Must be padded to at least 3200 bytes and multiple of 320
    assert len(raw) == 3200
    assert raw[:500] == b"\x05" * 500
    assert raw[500:] == b"\x00" * 2700  # Silence padding
