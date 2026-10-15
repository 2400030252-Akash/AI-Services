"""
tests/test_stt_service.py
=========================
Unit tests for app/services/stt_service.py.
Validates AudioBuffer chunk decoding, size tracking, and Deepgram REST batch parameters.
"""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.stt_service import AudioBuffer, transcribe_audio_batch


def test_audio_buffer_operations():
    buf = AudioBuffer()
    assert not buf.has_audio
    assert buf.size_bytes == 0
    assert buf.chunk_count == 0

    chunk1 = base64.b64encode(b"chunk1_data").decode("ascii")
    chunk2 = base64.b64encode(b"chunk2_data").decode("ascii")

    buf.add_chunk(chunk1)
    buf.add_chunk(chunk2)

    assert buf.has_audio
    assert buf.chunk_count == 2
    assert buf.size_bytes == len(b"chunk1_data") + len(b"chunk2_data")
    assert buf.get_audio() == b"chunk1_datachunk2_data"

    buf.clear()
    assert not buf.has_audio
    assert buf.size_bytes == 0
    assert buf.chunk_count == 0


@pytest.mark.asyncio
async def test_transcribe_audio_batch_empty():
    assert await transcribe_audio_batch(b"") == ""


@pytest.mark.asyncio
async def test_transcribe_audio_batch_missing_key():
    with patch("app.services.stt_service.settings.deepgram_api_key", ""):
        res = await transcribe_audio_batch(b"audio_bytes")
        assert res == ""


@pytest.mark.asyncio
async def test_transcribe_audio_batch_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Hello, I am calling about the service."
                        }
                    ]
                }
            ]
        }
    }

    raw_pcm = b"\x00\x01" * 800  # 1600 bytes of audio

    with patch("app.services.stt_service.settings.deepgram_api_key", "mock-dg-key"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
        transcript = await transcribe_audio_batch(raw_pcm)

    assert transcript == "Hello, I am calling about the service."
    # Validate Deepgram audio configuration parameters
    call_kwargs = mock_post.call_args.kwargs
    params = call_kwargs["params"]
    assert params["encoding"] == "linear16"
    assert params["sample_rate"] == "8000"
    assert params["channels"] == "1"
    assert params["model"] == "nova-2"
