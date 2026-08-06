"""
tests/test_conversations.py
============================
Tests for the conversation service and transcript endpoint.

All DB interactions are mocked — no live Postgres needed.

Coverage:
  Service layer
    - add_message persists a turn with correct role + content
    - add_message raises 422 for invalid role
    - get_conversation_history returns LLMMessage list in order
    - get_conversation_history returns empty list when no turns
    - get_transcript raises 404 when call not found
    - get_transcript returns both turns and llm_messages from one query

  API layer
    - GET /calls/{id}/conversation requires auth (401)
    - GET /calls/{id}/conversation returns 200 with transcript body
    - GET /calls/{id}/conversation returns 404 for unknown call
    - GET /calls/{id}/conversation returns empty transcript for call with no turns
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.call import Call, Conversation
from app.models.admin_user import AdminUser
from app.schemas.conversation import LLMMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin() -> AdminUser:
    from app.core.security import hash_password
    admin = AdminUser()
    admin.id = uuid.uuid4()
    admin.email = "admin@example.com"
    admin.password_hash = hash_password("password")
    admin.created_at = datetime.now(timezone.utc)
    admin.updated_at = datetime.now(timezone.utc)
    return admin


def _make_call() -> Call:
    call = Call()
    call.id = uuid.uuid4()
    call.call_sid = f"CA{uuid.uuid4().hex[:30]}"
    call.from_number = "+15550001111"
    call.to_number = "+15559998888"
    call.status = "active"
    call.direction = "inbound"
    call.duration = None
    call.started_at = datetime.now(timezone.utc)
    call.ended_at = None
    call.created_at = datetime.now(timezone.utc)
    call.conversations = []
    return call


def _make_turn(call_id: uuid.UUID, role: str, content: str, idx: int = 0) -> Conversation:
    turn = Conversation()
    turn.id = uuid.uuid4()
    turn.call_id = call_id
    turn.role = role
    turn.content = content
    turn.created_at = datetime(2024, 1, 1, 12, 0, idx, tzinfo=timezone.utc)
    return turn


def _auth_headers() -> dict[str, str]:
    from app.core.security import create_access_token
    return {"Authorization": f"Bearer {create_access_token('admin@example.com')}"}


# ---------------------------------------------------------------------------
# Service layer unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_message_persists_turn() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.conversation_service import ConversationService

    session = AsyncMock(spec=AsyncSession)
    service = ConversationService(session)

    call_id = uuid.uuid4()
    expected_turn = _make_turn(call_id, "user", "Hello!")

    with patch(
        "app.database.repositories.conversation_repo.ConversationRepository.create",
        new_callable=AsyncMock,
        return_value=expected_turn,
    ):
        result = await service.add_message(call_id, "user", "Hello!")

    assert result.role == "user"
    assert result.content == "Hello!"
    assert result.call_id == call_id


@pytest.mark.asyncio
async def test_add_message_strips_whitespace() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.conversation_service import ConversationService

    session = AsyncMock(spec=AsyncSession)
    service = ConversationService(session)

    call_id = uuid.uuid4()
    expected_turn = _make_turn(call_id, "assistant", "Response text")

    with patch(
        "app.database.repositories.conversation_repo.ConversationRepository.create",
        new_callable=AsyncMock,
        return_value=expected_turn,
    ) as mock_create:
        await service.add_message(call_id, "assistant", "  Response text  ")

    # Verify stripped content was passed to the repo
    _, kwargs = mock_create.call_args
    assert kwargs["content"] == "Response text"


@pytest.mark.asyncio
async def test_add_message_rejects_invalid_role() -> None:
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.conversation_service import ConversationService

    session = AsyncMock(spec=AsyncSession)
    service = ConversationService(session)

    with pytest.raises(HTTPException) as exc_info:
        await service.add_message(uuid.uuid4(), "system", "Injected!")  # type: ignore[arg-type]

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "INVALID_ROLE"


@pytest.mark.asyncio
async def test_get_conversation_history_returns_llm_messages() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.conversation_service import ConversationService

    session = AsyncMock(spec=AsyncSession)
    service = ConversationService(session)

    call_id = uuid.uuid4()
    turns = [
        _make_turn(call_id, "user", "Hi there", 0),
        _make_turn(call_id, "assistant", "Hello! How can I help?", 1),
    ]

    with patch(
        "app.database.repositories.conversation_repo.ConversationRepository.list_by_call",
        new_callable=AsyncMock,
        return_value=turns,
    ):
        result = await service.get_conversation_history(call_id)

    assert len(result) == 2
    assert isinstance(result[0], LLMMessage)
    assert result[0].role == "user"
    assert result[0].content == "Hi there"
    assert result[1].role == "assistant"


@pytest.mark.asyncio
async def test_get_conversation_history_empty() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.conversation_service import ConversationService

    session = AsyncMock(spec=AsyncSession)
    service = ConversationService(session)

    with patch(
        "app.database.repositories.conversation_repo.ConversationRepository.list_by_call",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await service.get_conversation_history(uuid.uuid4())

    assert result == []


@pytest.mark.asyncio
async def test_get_transcript_raises_404_when_call_missing() -> None:
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.conversation_service import ConversationService

    session = AsyncMock(spec=AsyncSession)
    service = ConversationService(session)

    with patch(
        "app.database.repositories.call_repo.CallRepository.get_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_transcript(uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "CALL_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_transcript_returns_both_formats() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.conversation_service import ConversationService

    session = AsyncMock(spec=AsyncSession)
    service = ConversationService(session)

    call = _make_call()
    turns = [
        _make_turn(call.id, "user", "Hello?", 0),
        _make_turn(call.id, "assistant", "Hi! How can I help?", 1),
    ]

    with (
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.database.repositories.conversation_repo.ConversationRepository.list_by_call",
            new_callable=AsyncMock,
            return_value=turns,
        ),
    ):
        result = await service.get_transcript(call.id)

    assert result.call_id == call.id
    assert result.turn_count == 2
    assert len(result.turns) == 2
    assert len(result.llm_messages) == 2
    # Display turns have full metadata
    assert result.turns[0].id is not None
    assert result.turns[0].created_at is not None
    # LLM messages are bare
    assert result.llm_messages[0].role == "user"
    assert result.llm_messages[0].content == "Hello?"


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_conversation_requires_auth(client: AsyncClient) -> None:
    fake_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/calls/{fake_id}/conversation")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.asyncio
async def test_get_conversation_success(client: AsyncClient) -> None:
    admin = _make_admin()
    call = _make_call()
    turns = [
        _make_turn(call.id, "user", "Hello?", 0),
        _make_turn(call.id, "assistant", "Hi!", 1),
    ]

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.database.repositories.conversation_repo.ConversationRepository.list_by_call",
            new_callable=AsyncMock,
            return_value=turns,
        ),
    ):
        resp = await client.get(
            f"/api/v1/calls/{call.id}/conversation",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["call_id"] == str(call.id)
    assert body["turn_count"] == 2
    assert len(body["turns"]) == 2
    assert len(body["llm_messages"]) == 2
    assert body["turns"][0]["role"] == "user"
    assert body["llm_messages"][1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_get_conversation_returns_404_for_unknown_call(client: AsyncClient) -> None:
    admin = _make_admin()

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        resp = await client.get(
            f"/api/v1/calls/{uuid.uuid4()}/conversation",
            headers=_auth_headers(),
        )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "CALL_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_conversation_empty_turns(client: AsyncClient) -> None:
    """A call that exists but has no turns should return empty lists, not a 404."""
    admin = _make_admin()
    call = _make_call()

    with (
        patch(
            "app.database.repositories.admin_user_repo.AdminUserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=admin,
        ),
        patch(
            "app.database.repositories.call_repo.CallRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=call,
        ),
        patch(
            "app.database.repositories.conversation_repo.ConversationRepository.list_by_call",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        resp = await client.get(
            f"/api/v1/calls/{call.id}/conversation",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["turn_count"] == 0
    assert body["turns"] == []
    assert body["llm_messages"] == []
