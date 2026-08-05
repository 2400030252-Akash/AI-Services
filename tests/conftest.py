"""
tests/conftest.py
=================
Pytest configuration and shared fixtures.

Test isolation strategy
-----------------------
- The FastAPI app is imported once per session.
- ``get_db`` is overridden with a no-op override so tests that mock the
  repository layer don't need a real Postgres connection.
- Each test that needs DB interactions patches the relevant repository
  method with ``unittest.mock.AsyncMock``.
"""
import os

# Set dummy environment variables for test execution if not present in env
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:pass@localhost:5432/postgres")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key-placeholder")
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("NVIDIA_API_KEY", "nvapi-test-key")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "ACtestaccountsid0000000000000000000")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "testauthtoken")
os.environ.setdefault("TWILIO_PHONE_NUMBER", "+15550001111")
os.environ.setdefault("TWILIO_SKIP_SIGNATURE_VALIDATION", "true")

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.main import app


# ---------------------------------------------------------------------------
# Override get_db for all tests — returns a MagicMock session so repos
# can be patched without needing a real DB connection.
# ---------------------------------------------------------------------------

async def _mock_get_db() -> AsyncGenerator[AsyncSession, None]:
    yield AsyncMock(spec=AsyncSession)


app.dependency_overrides[get_db] = _mock_get_db


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client backed by the FastAPI app (no real server)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
