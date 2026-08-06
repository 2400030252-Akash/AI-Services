"""
app/database/__init__.py
Exposes get_db for easy import across the project.
"""
from app.database.session import get_db

__all__ = ["get_db"]
