import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT email, password_hash FROM admin_users"))
        for row in res:
            print(f"Email: {row[0]}, Hash: {row[1]}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
