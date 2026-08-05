"""
app/api/calls.py
================
Calls router — mounts at /api/v1/calls.

All endpoints require a valid admin JWT (Depends(get_current_admin)).

Endpoints:
  GET /api/v1/calls                        — paginated list, sortable by start_time
  GET /api/v1/calls/{id}                   — full call detail with conversation turns
  GET /api/v1/calls/{id}/conversation      — full transcript (display + LLM format)

Write operations (create_call / end_call / mark_call_failed) are
intentionally NOT exposed as HTTP endpoints here — they will be called
internally by the Twilio webhook module in a later module.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.database.session import get_db
from app.schemas.auth import AdminProfile
from app.schemas.call import (
    CallDetailOut,
    PaginatedCallsOut,
    SortOrderLiteral,
)
from app.schemas.conversation import ConversationTranscriptOut
from app.services.call_service import CallService
from app.services.conversation_service import ConversationService

router = APIRouter()

# Shared 401 / 404 OpenAPI response examples
_AUTH_RESPONSE = {
    401: {
        "description": "Missing or invalid JWT.",
        "content": {
            "application/json": {
                "example": {
                    "error": True,
                    "message": "Authentication required.",
                    "code": "NOT_AUTHENTICATED",
                }
            }
        },
    }
}

_NOT_FOUND_RESPONSE = {
    404: {
        "description": "Call not found.",
        "content": {
            "application/json": {
                "example": {
                    "error": True,
                    "message": "Call '<id>' not found.",
                    "code": "CALL_NOT_FOUND",
                }
            }
        },
    }
}


# ---------------------------------------------------------------------------
# GET /calls
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=PaginatedCallsOut,
    status_code=status.HTTP_200_OK,
    summary="List all calls (paginated)",
    responses=_AUTH_RESPONSE,
)
async def list_calls(
    limit: int = Query(default=50, ge=1, le=200, description="Rows per page."),
    offset: int = Query(default=0, ge=0, description="Number of rows to skip."),
    sort_by: str = Query(
        default="started_at",
        pattern="^(started_at|created_at)$",
        description="Column to sort by: ``started_at`` or ``created_at``.",
    ),
    sort_order: SortOrderLiteral = Query(
        default="desc",
        description="Sort direction: ``asc`` or ``desc``.",
    ),
    db: AsyncSession = Depends(get_db),
    _admin: AdminProfile = Depends(get_current_admin),
) -> PaginatedCallsOut:
    """
    Return a paginated list of all calls, newest first by default.

    Use ``offset`` + ``limit`` for cursor-free pagination.
    The ``pagination.has_more`` flag tells you whether another page exists.
    """
    service = CallService(db)
    return await service.list_calls(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
    )


# ---------------------------------------------------------------------------
# GET /calls/{call_id}/conversation
# IMPORTANT: This route is defined BEFORE /{call_id} so FastAPI does not
# try to parse the literal "conversation" string as a UUID path parameter.
# ---------------------------------------------------------------------------

@router.get(
    "/{call_id}/conversation",
    response_model=ConversationTranscriptOut,
    status_code=status.HTTP_200_OK,
    summary="Get call transcript",
    responses={
        **_AUTH_RESPONSE,
        **_NOT_FOUND_RESPONSE,
        200: {
            "description": (
                "Full transcript with both display-friendly turns and a "
                "bare {role, content} list ready for the AI service."
            ),
        },
    },
)
async def get_conversation(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: AdminProfile = Depends(get_current_admin),
) -> ConversationTranscriptOut:
    """
    Return the full conversation transcript for a call.

    Response contains two representations of the same data:

    - **turns** — ordered list with full metadata (id, role, content,
      created_at); use this for display in the admin UI.
    - **llm_messages** — bare ``{role, content}`` list; pass directly
      to the AI service's chat completions endpoint.

    Raises **404** if the call does not exist.
    Returns an empty ``turns`` / ``llm_messages`` if the call exists
    but has no conversation turns yet.
    """
    service = ConversationService(db)
    return await service.get_transcript(call_id)


# ---------------------------------------------------------------------------
# GET /calls/{call_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{call_id}",
    response_model=CallDetailOut,
    status_code=status.HTTP_200_OK,
    summary="Get call detail",
    responses={**_AUTH_RESPONSE, **_NOT_FOUND_RESPONSE},
)
async def get_call(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: AdminProfile = Depends(get_current_admin),
) -> CallDetailOut:
    """
    Return full detail for a single call, including all conversation turns
    in chronological order.

    Raises **404** if no call with that UUID exists.
    """
    service = CallService(db)
    call = await service.get_call(call_id)
    return CallDetailOut.model_validate(call)
