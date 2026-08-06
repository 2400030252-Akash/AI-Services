"""Initial schema — admin_users, calls, conversations

Revision ID: 0001_initial
Revises: (none — first migration)
Create Date: 2026-08-04

Creates the three tables defined in the architecture doc:
  - admin_users
  - calls
  - conversations  (FK → calls.id, CASCADE DELETE)

Requires Postgres extension: pgcrypto (for gen_random_uuid()).
On Supabase this is already enabled in every project.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers — used by Alembic
# ---------------------------------------------------------------------------
revision: str = "0001_initial"
down_revision: str | None = None   # first migration, no parent
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # admin_users
    # ------------------------------------------------------------------
    op.create_table(
        "admin_users",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_users"),
        sa.UniqueConstraint("email", name="uq_admin_users_email"),
    )
    op.create_index("ix_admin_users_email", "admin_users", ["email"], unique=True)

    # ------------------------------------------------------------------
    # calls
    # ------------------------------------------------------------------
    op.create_table(
        "calls",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("call_sid", sa.String(64), nullable=False),
        sa.Column("from_number", sa.String(20), nullable=False),
        sa.Column("to_number", sa.String(20), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calls"),
        sa.UniqueConstraint("call_sid", name="uq_calls_call_sid"),
    )
    op.create_index("ix_calls_call_sid", "calls", ["call_sid"], unique=True)

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "call_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name="fk_conversations_call_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_conversations_call_id", "conversations", ["call_id"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_index("ix_conversations_call_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_calls_call_sid", table_name="calls")
    op.drop_table("calls")

    op.drop_index("ix_admin_users_email", table_name="admin_users")
    op.drop_table("admin_users")
