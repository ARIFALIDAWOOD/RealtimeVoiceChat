# services/__init__.py
"""Service layer for business logic."""

# Note: Import services directly to avoid circular imports
# Use: from services.auth_service import AuthService
# Use: from services.session_manager import SessionManager

__all__ = [
    "AuthService",
    "SessionManager",
]
