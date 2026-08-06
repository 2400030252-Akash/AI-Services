"""
app/models/admin_user.py
========================
AdminUser ORM model — maps to the ``admin_users`` table.

Schema (from architecture doc):
    id            UUID PK   gen_random_uuid()
    email         VARCHAR   unique, not null, indexed
    password_hash VARCHAR   bcrypt hash, not null
    created_at    TIMESTAMPTZ  server default now()
    updated_at    TIMESTAMPTZ  server default now(), refreshed on update
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKey


class AdminUser(UUIDPrimaryKey, TimestampMixin, Base):
    """
    Platform administrator.  There is no public signup; accounts are
    created via a seed script or the admin CLI.
    """
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<AdminUser id={self.id} email={self.email!r}>"
