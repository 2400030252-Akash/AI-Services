"""
alembic/env.py
==============
Alembic migration environment — configured for:
  - Async SQLAlchemy (asyncpg driver)
  - Autogenerate from ORM models (target_metadata wired to Base.metadata)
  - DATABASE_URL loaded from app settings (reads .env automatically)

Run migrations:
    alembic upgrade head          # apply all pending migrations
    alembic revision --autogenerate -m "description"   # generate new one
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ---------------------------------------------------------------------------
# Load application settings — reads DATABASE_URL from .env
# ---------------------------------------------------------------------------
from app.core.config import settings

# ---------------------------------------------------------------------------
# Import all models so autogenerate can detect every table.
# Importing the package __init__ is enough because it imports each model.
# ---------------------------------------------------------------------------
import app.models  # noqa: F401  — side-effect: registers all mappers
from app.database.base import Base

# ---------------------------------------------------------------------------
# Alembic config object
# ---------------------------------------------------------------------------
config = context.config

# Override sqlalchemy.url with the value from our pydantic settings so we
# never need to duplicate the URL inside alembic.ini.
# Alembic needs a *sync* URL for its internal plumbing; replace asyncpg with psycopg2
# for the URL it stores in the ini (env.py uses async_engine_from_config anyway).
config.set_main_option("sqlalchemy.url", settings.database_url)

# Set up loggers from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tell Alembic autogenerate which metadata to compare against
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline mode — emit SQL to stdout without a live DB connection
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """
    Offline mode: generate migration SQL without connecting to the DB.
    Useful for review or applying via a DBA.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,         # detect column type changes
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online async mode — connects to Supabase Postgres via asyncpg
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync wrapper."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration runs."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
