"""
app/api/deps_exotel.py
=======================
FastAPI dependency for Exotel webhook request validation.

Exotel signs webhook requests using HTTP Basic Authentication with
API Key and API Token.  We validate this on incoming status callbacks.

For WebSocket connections (AgentStream), validation is performed
during the initial handshake via query parameters or headers.

Usage
-----
    from app.api.deps_exotel import validate_exotel_request

    @router.post("/status")
    async def status(request: Request, _: None = Depends(validate_exotel_request)):
        ...

Security notes
--------------
- In local dev / test, set ``TELEPHONY_PROVIDER=exotel`` and the
  validation can be skipped by leaving credentials empty in debug mode.
- Never skip validation in production.
"""
from __future__ import annotations

import base64
import logging

from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)


async def validate_exotel_request(request: Request) -> None:
    """
    FastAPI dependency — validates that the incoming request carries
    valid Exotel credentials via HTTP Basic Authentication.

    Raises HTTP 403 if:
    - The ``Authorization`` header is missing.
    - The credentials do not match the configured API key/token.

    Returns ``None`` on success.
    """
    # -----------------------------------------------------------------------
    # Dev bypass — skip if no Exotel credentials configured in debug mode
    # -----------------------------------------------------------------------
    if settings.debug and (not settings.exotel_api_key or not settings.exotel_api_token):
        logger.warning(
            "Exotel request validation BYPASSED — "
            "no credentials configured in debug mode. Not safe for production!"
        )
        return

    # -----------------------------------------------------------------------
    # Extract the Authorization header
    # -----------------------------------------------------------------------
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        logger.warning("Exotel webhook received with no Authorization header")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": True,
                "message": "Missing Exotel authorization.",
                "code": "EXOTEL_AUTH_MISSING",
            },
        )

    # -----------------------------------------------------------------------
    # Validate Basic Auth credentials
    # -----------------------------------------------------------------------
    try:
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() != "basic":
            raise ValueError("Not Basic auth")

        decoded = base64.b64decode(credentials).decode("utf-8")
        api_key, _, api_token = decoded.partition(":")

        if api_key != settings.exotel_api_key or api_token != settings.exotel_api_token:
            raise ValueError("Credentials mismatch")

    except Exception:
        logger.warning("Exotel authorization validation failed")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": True,
                "message": "Invalid Exotel authorization.",
                "code": "EXOTEL_AUTH_INVALID",
            },
        )
