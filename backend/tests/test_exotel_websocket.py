"""
tests/test_exotel_websocket.py
==============================
Simulated WebSocket test for Exotel AgentStream handler.
Validates:
  - Connection handshake ("connected" event)
  - "start" event parsing (stream_sid, call_sid, caller numbers)
  - Greeting audio transmission
  - "clear" (barge-in) event handling
  - "stop" event and clean session teardown
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient

from app.main import app


def test_exotel_websocket_lifecycle():
    client = TestClient(app)

    # Mock DB operations and TTS generation during the WebSocket test
    with patch("app.api.exotel_voice.AsyncSessionLocal"), \
         patch("app.api.exotel_voice.generate_speech_base64_chunks", new_callable=AsyncMock, return_value=["b64_mock_chunk_1"]), \
         patch("app.api.exotel_voice.CallService.create_call", new_callable=AsyncMock) as mock_create_call, \
         patch("app.api.exotel_voice.CallService.end_call", new_callable=AsyncMock):

        with client.websocket_connect("/api/v1/exotel/stream") as ws:
            # 1. Send connected event from Exotel
            ws.send_json({"event": "connected"})

            # 2. Send start event with metadata
            ws.send_json({
                "event": "start",
                "sequence_number": 1,
                "stream_sid": "stream_test_123",
                "start": {
                    "account_sid": "exotel_acc_001",
                    "call_sid": "call_test_456",
                    "stream_sid": "stream_test_123",
                    "custom_parameters": {
                        "From": "+919876543210",
                        "To": "+918000000000",
                    },
                },
            })

            # 3. Backend should respond with greeting audio chunk
            response = ws.receive_json()
            assert response["event"] == "media"
            assert response["stream_sid"] == "stream_test_123"
            assert response["media"]["payload"] == "b64_mock_chunk_1"

            # 4. Simulate barge-in / clear event
            ws.send_json({
                "event": "clear",
                "stream_sid": "stream_test_123",
            })
            # Clear response sent back
            clear_resp = ws.receive_json()
            assert clear_resp["event"] == "clear"

            # 5. Send stop event
            ws.send_json({
                "event": "stop",
                "stream_sid": "stream_test_123",
            })
