"""
app/models/__init__.py
======================
Import all models here so that:
  1. Alembic's env.py can do ``from app.models import *`` to discover every
     table automatically.
  2. SQLAlchemy's relationship resolution works without forward-reference
     issues (all mappers are in the same registry by import time).
"""
from app.models.admin_user import AdminUser
from app.models.call import Call, Conversation

__all__ = ["AdminUser", "Call", "Conversation"]
