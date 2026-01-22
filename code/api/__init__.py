# api/__init__.py
"""FastAPI API routes and dependencies."""

# Note: Import routes directly to avoid circular imports
# Use: from api.routes import auth, config, health, history, sessions

__all__ = [
    "auth",
    "config",
    "health",
    "history",
    "sessions",
]
