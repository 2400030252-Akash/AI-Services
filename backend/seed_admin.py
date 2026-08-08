import asyncio
import sys
import os

# Ensure the app module can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.session import AsyncSessionLocal
from app.services.auth_service import AuthService

async def seed():
    # You can change these credentials to whatever you want
    email = "admin@example.com"
    password = "securepassword123"
    
    print(f"Attempting to create admin user: {email}...")
    
    async with AsyncSessionLocal() as db:
        service = AuthService(db)
        try:
            admin = await service.create_admin(
                email=email, 
                password=password
            )
            await db.commit()
            print("========================================")
            print("SUCCESS! Admin user created.")
            print(f"Email: {email}")
            print(f"Password: {password}")
            print("========================================")
            print("You can now log in using these credentials.")
        except Exception as e:
            await db.rollback()
            if "ADMIN_ALREADY_EXISTS" in str(e):
                print(f"Notice: Admin user '{email}' already exists in the database.")
            else:
                print(f"FAILED to create admin. Error: {e}")

if __name__ == "__main__":
    asyncio.run(seed())
