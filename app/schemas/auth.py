"""
app/schemas/auth.py
===================
Pydantic v2 request/response schemas for the auth endpoints.

Only what is needed for login — no signup, no password-reset.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Body for POST /api/v1/auth/login."""
    email: EmailStr = Field(
        ...,
        examples=["admin@example.com"],
        description="Admin account email address.",
    )
    password: str = Field(
        ...,
        min_length=1,
        examples=["s3cur3P@ssword"],
        description="Admin account plain-text password.",
    )


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    """Successful login response — contains the JWT access token."""
    access_token: str = Field(
        ...,
        description="JWT bearer token to include in Authorization: Bearer <token> header.",
    )
    token_type: str = Field(default="bearer")
    expires_in: int = Field(
        ...,
        description="Token lifetime in seconds.",
    )


class AdminProfile(BaseModel):
    """
    Minimal admin profile returned alongside the token.
    Never expose password_hash here.
    """
    id: uuid.UUID
    email: EmailStr
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    """Full login response: token + profile."""
    token: TokenResponse
    admin: AdminProfile
