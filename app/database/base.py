"""
app/database/base.py
====================
SQLAlchemy declarative base and shared column mixins.

Rules:
- Import ``Base`` into every model module.
- Apply ``UUIDPrimaryKey`` and/or ``TimestampMixin`` to avoid boilerplate.
- Never import models here — do that in app/models/__init__.py so Alembic
  can discover them without circular imports.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


class UUIDPrimaryKey:
    """
    Mixin: UUID primary key, generated server-side by ``gen_random_uuid()``.
    Place first in the MRO so it appears before Base.
    """
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """
    Mixin: created_at (immutable) and updated_at (auto-refreshed on update).
    Both use timezone-aware timestamps.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
