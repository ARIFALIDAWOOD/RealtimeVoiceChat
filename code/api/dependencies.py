# api/dependencies.py
"""FastAPI dependency injection utilities."""

import logging
from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth_service import AuthService
from services.session_manager import SessionManager

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)


async def get_auth_service(
    db: AsyncSession = Depends(get_db),
) -> AuthService:
    """
    Dependency that provides an AuthService instance.

    Args:
        db: Database session from get_db dependency.

    Returns:
        AuthService instance.
    """
    return AuthService(db)


async def get_session_manager(
    db: AsyncSession = Depends(get_db),
) -> SessionManager:
    """
    Dependency that provides a SessionManager instance.

    Args:
        db: Database session from get_db dependency.

    Returns:
        SessionManager instance.
    """
    return SessionManager(db)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_service: AuthService = Depends(get_auth_service),
) -> Optional[User]:
    """
    Dependency that extracts and validates the current user from JWT token.

    This dependency is optional - returns None if no token provided.

    Args:
        credentials: HTTP Authorization header with Bearer token.
        auth_service: AuthService for token validation.

    Returns:
        User object if valid token, None if no token provided.

    Raises:
        HTTPException: If token is invalid or user not found.
    """
    if credentials is None:
        return None

    token = credentials.credentials
    user = await auth_service.get_current_user(token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def require_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """
    Dependency that requires a valid authenticated user.

    Args:
        credentials: HTTP Authorization header with Bearer token.
        auth_service: AuthService for token validation.

    Returns:
        User object.

    Raises:
        HTTPException: If token is missing, invalid, or user not found.
    """
    token = credentials.credentials
    user = await auth_service.get_current_user(token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_session_id_from_query(
    session_id: Optional[str] = Query(
        default=None,
        description="Session ID for existing session",
    ),
) -> Optional[str]:
    """
    Dependency that extracts session_id from query parameters.

    Args:
        session_id: Optional session ID query parameter.

    Returns:
        Session ID string or None.
    """
    return session_id


class SessionDependency:
    """
    Dependency class for session validation in routes.

    Can be used to verify session ownership and access.
    """

    def __init__(self, require_ownership: bool = True):
        """
        Initialize the dependency.

        Args:
            require_ownership: If True, verifies user owns the session.
        """
        self.require_ownership = require_ownership

    async def __call__(
        self,
        session_id: str,
        session_manager: SessionManager = Depends(get_session_manager),
        current_user: Optional[User] = Depends(get_current_user),
    ):
        """
        Validate and retrieve session.

        Args:
            session_id: Session ID from path parameter.
            session_manager: SessionManager instance.
            current_user: Current authenticated user (optional).

        Returns:
            Session object.

        Raises:
            HTTPException: If session not found or user not authorized.
        """
        user_id = current_user.id if current_user and self.require_ownership else None

        session = await session_manager.get_session(session_id, user_id)

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or access denied",
            )

        return session


# Pre-configured dependency instances
require_session = SessionDependency(require_ownership=True)
get_session_any = SessionDependency(require_ownership=False)
