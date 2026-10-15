"""
app/api/exotel_status.py
=========================
Exotel StatusCallback webhook — POST endpoint.

Called by Exotel when a call reaches a terminal state (completed, failed,
busy, no-answer).  Updates the Call record in the database.

Mounts at /api/v1/exotel/call-status.

Exotel sends the following key parameters as form data or query params:
  - CallSid:    Unique call identifier
  - Status:     completed | failed | busy | no-answer
  - Direction:  incoming | outgoing
  - From:       Caller phone number
  - To:         Called phone number
  - StartTime:  Call start timestamp
  - EndTime:    Call end timestamp
  - Duration:   Call duration in seconds
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps_exotel import validate_exotel_request
from app.database.repositories.call_repo import CallRepository
from app.database.session import get_db
from app.services.call_service import CallService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/call-status",
    status_code=status.HTTP_200_OK,
    summary="Exotel call status lifecycle callback",
)
async def exotel_call_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(validate_exotel_request),
) -> JSONResponse:
    """
    Called by Exotel when the status of a call changes.

    Exotel may send parameters as form data or query parameters.
    We read from both sources.
    """
    # Exotel sends data as form-encoded or query params
    try:
        form_data = dict(await request.form())
    except Exception:
        form_data = {}

    query_params = dict(request.query_params)

    # Merge — form data takes priority
    params = {**query_params, **form_data}

    call_sid = params.get("CallSid", "")
    call_status = params.get("Status", "").lower()
    duration_str = params.get("Duration", "")

    if not call_sid:
        logger.warning("Exotel status callback missing CallSid")
        return JSONResponse({"status": "ignored", "reason": "missing CallSid"})

    logger.info(
        "Exotel call status update: CallSid=%s, Status=%s, Duration=%s",
        call_sid, call_status, duration_str,
    )

    # Look up the call
    call_repo = CallRepository(db)
    call = await call_repo.get_by_sid(call_sid)

    if not call:
        logger.warning("Call not found for Exotel CallSid=%s", call_sid)
        return JSONResponse({"status": "ignored", "reason": "call not found"})

    # Only update if not already in terminal state
    if call.status not in ("completed", "failed"):
        call_service = CallService(db)
        try:
            if call_status in ("completed",):
                await call_service.end_call(call.id)
            elif call_status in ("failed", "busy", "no-answer"):
                await call_service.mark_call_failed(call.id)
            await db.commit()
            logger.info("Call %s updated to status: %s", call_sid, call_status)
        except Exception as exc:
            logger.exception("Failed to update call status: %s", exc)
            await db.rollback()

    return JSONResponse({"status": "ok"})
