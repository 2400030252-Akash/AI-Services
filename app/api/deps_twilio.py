"""
app/api/deps_twilio.py
=======================
FastAPI dependency for Twilio request signature validation.

Twilio signs every webhook request with an HMAC-SHA1 signature derived from:
  - The Auth Token
  - The full request URL (including query string)
  - The sorted POST parameters

We validate this on every incoming webhook call.  Requests that fail
validation are rejected with HTTP 403 before any business logic runs.

Usage
-----
    from app.api.deps_twilio import validate_twilio_signature

    @router.post("/voice")
    async def voice(request: Request, _: None = Depends(validate_twilio_signature)):
        ...

Security notes
--------------
- ``RequestValidator`` is from the official Twilio Python SDK.
- The URL passed to the validator must match *exactly* what Twilio uses,
  including the scheme and host.  We reconstruct it from the incoming
  ``Request`` object.
- In local dev / test, set ``TWILIO_SKIP_SIGNATURE_VALIDATION=true`` in
  .env to bypass this check.  Never do this in production.
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status
from twilio.request_validator import RequestValidator

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy singleton validator
# ---------------------------------------------------------------------------

_validator: RequestValidator | None = None


def _get_validator() -> RequestValidator:
    global _validator
    if _validator is None:
        _validator = RequestValidator(settings.twilio_auth_token)
    return _validator


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

async def validate_twilio_signature(request: Request) -> None:
    """
    FastAPI dependency — validates that the incoming request carries a valid
    Twilio HMAC-SHA1 signature.

    Raises HTTP 403 if:
    - The ``X-Twilio-Signature`` header is missing.
    - The signature does not match the expected HMAC for this request.

    Pass as ``Depends(validate_twilio_signature)`` on every Twilio webhook.
    Returns ``None`` on success (the endpoint receives nothing from it).
    """
    # -----------------------------------------------------------------------
    # Dev bypass — never allow in production
    # -----------------------------------------------------------------------
    if getattr(settings, "twilio_skip_signature_validation", False):
        logger.warning(
            "Twilio signature validation BYPASSED — not safe for production!"
        )
        return

    # -----------------------------------------------------------------------
    # Extract the signature header
    # -----------------------------------------------------------------------
    twilio_sig = request.headers.get("X-Twilio-Signature", "")
    if not twilio_sig:
        logger.warning("Twilio webhook received with no X-Twilio-Signature header")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": True,
                "message": "Missing Twilio signature.",
                "code": "TWILIO_SIGNATURE_MISSING",
            },
        )

    # -----------------------------------------------------------------------
    # Reconstruct the exact URL Twilio signed
    # -----------------------------------------------------------------------
    url = str(request.url)

    # -----------------------------------------------------------------------
    # Read form-encoded POST parameters (Twilio always sends form data)
    # -----------------------------------------------------------------------
    try:
        params = dict(await request.form())
    except Exception:
        params = {}

    # -----------------------------------------------------------------------
    # Validate
    # -----------------------------------------------------------------------
    validator = _get_validator()
    is_valid = validator.validate(url, params, twilio_sig)

    if not is_valid:
        logger.warning(
            "Twilio signature validation failed",
            extra={"url": url, "sig_prefix": twilio_sig[:8]},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": True,
                "message": "Invalid Twilio signature.",
                "code": "TWILIO_SIGNATURE_INVALID",
            },
        )
