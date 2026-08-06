"""
scripts/create_admin.py
=======================
One-time CLI script to create the first (or any subsequent) admin user.

Usage
-----
From the project root with the venv active::

    # Interactive (prompts for password securely)
    python scripts/create_admin.py --email admin@example.com

    # Non-interactive (for CI/CD — avoid exposing password in shell history)
    python scripts/create_admin.py --email admin@example.com --password "s3cr3t"

The script reads DATABASE_URL (and other required env vars) from .env
via the normal pydantic settings mechanism.

Exit codes
----------
0 — admin created successfully
1 — admin already exists (idempotent — safe to re-run)
2 — unexpected error
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.database.repositories.admin_user_repo import AdminUserRepository


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------

async def _create_admin(email: str, password: str) -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        repo = AdminUserRepository(session)

        existing = await repo.get_by_email(email)
        if existing:
            print(f"[!] Admin with email '{email}' already exists. Nothing changed.")
            await engine.dispose()
            sys.exit(1)

        pw_hash = hash_password(password)
        admin = await repo.create(email=email, password_hash=pw_hash)
        await session.commit()
        await session.refresh(admin)

        print(f"[✓] Admin created successfully.")
        print(f"    ID    : {admin.id}")
        print(f"    Email : {admin.email}")
        print(f"    At    : {admin.created_at.isoformat()}")

    await engine.dispose()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an admin user for the AI Voice Calling Platform.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Admin email address (must be unique).",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Admin password. If omitted, you will be prompted securely.",
    )
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass(f"Password for {args.email}: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("[✗] Passwords do not match. Aborting.")
            sys.exit(2)

    if len(password) < 8:
        print("[✗] Password must be at least 8 characters. Aborting.")
        sys.exit(2)

    try:
        asyncio.run(_create_admin(email=args.email, password=password))
    except Exception as exc:
        print(f"[✗] Unexpected error: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    main()
