import urllib.request
import json
import os
import sys

# Add parent dir to path so app modules work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.security import hash_password

def update_admin(email, plain_password):
    pw_hash = hash_password(plain_password)
    print(f"Generated full bcrypt hash ({len(pw_hash)} chars): {pw_hash}")
    
    url = f"{settings.supabase_url}/admin_users?email=eq.{email}"
    data = json.dumps({"password_hash": pw_hash}).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=data,
        method="PATCH",
        headers={
            "apikey": settings.supabase_key,
            "Authorization": f"Bearer {settings.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
    )
    
    try:
        with urllib.request.urlopen(req) as res:
            resp_data = res.read().decode("utf-8")
            print("Successfully updated Supabase DB:")
            print(resp_data)
    except Exception as e:
        print("Failed to update:", e)

if __name__ == "__main__":
    email = "akashrao4887@gmail.com"
    password = "securepassword123"  # Standard default password
    if len(sys.argv) > 1:
        password = sys.argv[1]
    update_admin(email, password)
