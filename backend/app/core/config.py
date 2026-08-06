"""
app/core/config.py
==================
Central application settings powered by Pydantic Settings v2.

All values are loaded exclusively from environment variables or the .env
file — nothing is hardcoded.  Required fields have no default; pydantic
will raise a clear ValidationError at import time if any of them are
missing, making misconfigured deployments fail fast before the app starts.

Usage everywhere in the project::

    from app.core.config import settings

    print(settings.app_name)
"""
from __future__ import annotations

import sys
from typing import Annotated

from pydantic import (
    AnyHttpUrl,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Helper type alias
# ---------------------------------------------------------------------------
_NonEmptyStr = Annotated[str, Field(min_length=1)]


class Settings(BaseSettings):
    """
    Application-wide settings.

    Reads from (in priority order):
      1. Real environment variables
      2. .env file in the project root

    Any field without a default is **required**.  Missing required fields
    produce a ValidationError at startup with the exact variable name(s).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # silently drop unknown env vars
        case_sensitive=False,    # DATABASE_URL == database_url
    )

    # -----------------------------------------------------------------------
    # Application metadata
    # -----------------------------------------------------------------------
    app_name: str = "AI Voice Calling Platform"
    app_version: str = "0.1.0"
    debug: bool = False

    # -----------------------------------------------------------------------
    # CORS
    # Accepts a comma-separated string in .env:
    #   CORS_ALLOWED_ORIGINS=http://localhost:3000,https://admin.example.com
    # -----------------------------------------------------------------------
    cors_allowed_origins: list[str] | str = Field(
        default=["http://localhost:3000"],
        description="Comma-separated list of allowed CORS origins.",
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """
        Accept both a raw comma-separated string (from .env) and a list
        (from test fixtures or programmatic construction).
        """
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # -----------------------------------------------------------------------
    # Database  (Supabase Postgres — asyncpg driver)
    # Env var:  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
    # -----------------------------------------------------------------------
    database_url: _NonEmptyStr = Field(
        description="Async Postgres DSN. Must use the postgresql+asyncpg scheme."
    )

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must start with 'postgresql+asyncpg://' "
                "(not 'postgresql://' — the asyncpg driver is required for async support)."
            )
        return v

    # -----------------------------------------------------------------------
    # Supabase  (direct REST / Storage / Auth calls)
    # -----------------------------------------------------------------------
    supabase_url: _NonEmptyStr = Field(
        description="Your Supabase project URL, e.g. https://<ref>.supabase.co"
    )
    supabase_key: _NonEmptyStr = Field(
        description="Supabase service-role secret key (never expose to clients)."
    )

    @field_validator("supabase_url")
    @classmethod
    def _validate_supabase_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("SUPABASE_URL must be an https:// URL.")
        return v.rstrip("/")   # normalise — no trailing slash

    # -----------------------------------------------------------------------
    # JWT
    # -----------------------------------------------------------------------
    jwt_secret: _NonEmptyStr = Field(
        description="Secret key used to sign and verify JWT tokens."
    )
    algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm.",
    )
    access_token_expire_minutes: int = Field(
        default=60,
        gt=0,
        description="JWT expiry in minutes (must be > 0).",
    )

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters long for security. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    # -----------------------------------------------------------------------
    # NVIDIA / DeepSeek AI
    # -----------------------------------------------------------------------
    nvidia_api_key: _NonEmptyStr = Field(
        description="NVIDIA API key for DeepSeek model access."
    )
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="NVIDIA OpenAI-compatible API base URL.",
    )
    nvidia_model: str = Field(
        default="deepseek-ai/deepseek-r1",
        description="Model identifier to use for AI completions.",
    )

    @field_validator("nvidia_api_key")
    @classmethod
    def _validate_nvidia_key(cls, v: str) -> str:
        if not v.startswith("nvapi-"):
            raise ValueError(
                "NVIDIA_API_KEY must start with 'nvapi-'. "
                "Obtain yours at https://build.nvidia.com"
            )
        return v

    # -----------------------------------------------------------------------
    # Twilio Voice
    # -----------------------------------------------------------------------
    twilio_account_sid: _NonEmptyStr = Field(
        description="Twilio Account SID (starts with 'AC')."
    )
    twilio_auth_token: _NonEmptyStr = Field(
        description="Twilio Auth Token — keep this secret."
    )
    twilio_phone_number: _NonEmptyStr = Field(
        description="Twilio purchased phone number in E.164 format, e.g. +15551234567."
    )
    twilio_skip_signature_validation: bool = Field(
        default=False,
        description="Skip Twilio request signature validation in local/testing environment.",
    )

    @field_validator("twilio_account_sid")
    @classmethod
    def _validate_twilio_sid(cls, v: str) -> str:
        if not v.startswith("AC"):
            raise ValueError(
                "TWILIO_ACCOUNT_SID must start with 'AC'. "
                "Find it in your Twilio Console dashboard."
            )
        return v

    @field_validator("twilio_phone_number")
    @classmethod
    def _validate_twilio_phone(cls, v: str) -> str:
        if not v.startswith("+"):
            raise ValueError(
                "TWILIO_PHONE_NUMBER must be in E.164 format, e.g. +15551234567."
            )
        return v

    # -----------------------------------------------------------------------
    # Cross-field startup guard
    # Runs after all individual fields are validated.
    # Add any invariants that span multiple fields here.
    # -----------------------------------------------------------------------
    @model_validator(mode="after")
    def _startup_guard(self) -> "Settings":
        """
        Final sanity-check executed once after all fields are validated.
        Keeps environment-specific rules together in one place.
        """
        if not self.debug and self.jwt_secret == "change-me-to-a-long-random-secret-string-at-least-32-chars":
            raise ValueError(
                "JWT_SECRET is still set to the example placeholder value. "
                "Set a real secret before running in production (DEBUG=false)."
            )
        return self


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
def _load_settings() -> Settings:
    """
    Instantiate Settings and convert any ValidationError into a readable
    startup message so developers see exactly which variables are missing.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:   # pydantic ValidationError or ValueError
        _lines = [
            "",
            "=" * 70,
            "  STARTUP ERROR — Invalid or missing environment variables",
            "=" * 70,
            str(exc),
            "",
            "  Fix the errors above, then restart the server.",
            "  Copy .env.example → .env and fill in the required values.",
            "=" * 70,
            "",
        ]
        print("\n".join(_lines), file=sys.stderr)
        sys.exit(1)


settings: Settings = _load_settings()
