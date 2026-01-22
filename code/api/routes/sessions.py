# api/routes/sessions.py
"""Session management routes for creating and managing voice chat sessions."""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    get_current_user,
    get_session_manager,
    require_current_user,
)
from api.models import (
    ErrorResponse,
    SessionConfigCreate,
    SessionConfigResponse,
    SessionConfigUpdate,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
)
from models.session import SessionConfig
from models.user import User
from services.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _session_to_response(session, message_count: int = 0) -> SessionResponse:
    """Convert database Session to SessionResponse."""
    config = session.config
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        state=session.state.value,
        config=SessionConfigResponse(
            llm_provider=config.llm_provider,
            llm_model=config.llm_model,
            tts_engine=config.tts_engine,
            tts_voice=config.tts_voice,
            persona=config.persona,
            verbosity=config.verbosity,
            language=config.language,
            no_think=config.no_think,
        ),
        created_at=session.created_at,
        expires_at=session.expires_at,
        websocket_connected=session.websocket_connected,
        message_count=message_count,
    )


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Session limit reached"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def create_session(
    session_data: SessionCreate = None,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> SessionResponse:
    """
    Create a new voice chat session.

    Creates a session with optional initial configuration and history.
    If authenticated, the session is associated with the user.
    If not authenticated, creates an ephemeral session.

    Args:
        session_data: Optional session creation data.
        session_manager: SessionManager instance.
        current_user: Current user (optional).

    Returns:
        Created session information.

    Raises:
        HTTPException: If user has reached maximum session limit.
    """
    session_data = session_data or SessionCreate()

    # Convert config if provided
    config = None
    if session_data.config:
        config = SessionConfig(
            llm_provider=session_data.config.llm_provider,
            llm_model=session_data.config.llm_model,
            tts_engine=session_data.config.tts_engine,
            tts_voice=session_data.config.tts_voice,
            persona=session_data.config.persona,
            verbosity=session_data.config.verbosity,
            language=session_data.config.language,
            no_think=session_data.config.no_think,
        )

    try:
        session = await session_manager.create_session(
            user_id=current_user.id if current_user else None,
            config=config,
            initial_history=session_data.initial_history,
        )
        message_count = len(session_data.initial_history) if session_data.initial_history else 0
        return _session_to_response(session, message_count)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "",
    response_model=SessionListResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_sessions(
    include_expired: bool = False,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: User = Depends(require_current_user),
) -> SessionListResponse:
    """
    List all sessions for the current user.

    Args:
        include_expired: Whether to include expired/terminated sessions.
        session_manager: SessionManager instance.
        current_user: Current authenticated user.

    Returns:
        List of user's sessions.
    """
    sessions = await session_manager.list_sessions(
        user_id=current_user.id,
        include_expired=include_expired,
    )

    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=len(sessions),
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def get_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> SessionResponse:
    """
    Get session information by ID.

    Args:
        session_id: Session unique identifier.
        session_manager: SessionManager instance.
        current_user: Current user (optional, for ownership check).

    Returns:
        Session information.

    Raises:
        HTTPException: If session not found or access denied.
    """
    user_id = current_user.id if current_user else None
    session = await session_manager.get_session_with_history(session_id, user_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied",
        )

    return _session_to_response(session, len(session.messages))


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def update_session(
    session_id: str,
    config_update: SessionConfigUpdate,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> SessionResponse:
    """
    Update session configuration.

    Only updates fields that are provided (non-null).

    Args:
        session_id: Session unique identifier.
        config_update: Configuration updates.
        session_manager: SessionManager instance.
        current_user: Current user (optional, for ownership check).

    Returns:
        Updated session information.

    Raises:
        HTTPException: If session not found or access denied.
    """
    user_id = current_user.id if current_user else None
    updates = config_update.model_dump(exclude_unset=True, exclude_none=True)

    session = await session_manager.update_session_config(
        session_id=session_id,
        config_updates=updates,
        user_id=user_id,
    )

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied",
        )

    return _session_to_response(session)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def terminate_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> None:
    """
    Terminate a session.

    This ends the session and cleans up associated resources.
    The session history is preserved but the session cannot be reconnected.

    Args:
        session_id: Session unique identifier.
        session_manager: SessionManager instance.
        current_user: Current user (optional, for ownership check).

    Raises:
        HTTPException: If session not found or access denied.
    """
    user_id = current_user.id if current_user else None
    success = await session_manager.terminate_session(session_id, user_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied",
        )
