# api/routes/history.py
"""Chat history management routes."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_current_user, get_session_manager
from api.models import (
    ChatHistoryCreate,
    ChatHistoryReplace,
    ChatHistoryResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    ErrorResponse,
)
from models.user import User
from services.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/history", tags=["History"])


@router.get(
    "",
    response_model=ChatHistoryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def get_history(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> ChatHistoryResponse:
    """
    Get chat history for a session.

    Returns all messages in the session's conversation history,
    ordered by sequence (oldest first).

    Args:
        session_id: Session unique identifier.
        session_manager: SessionManager instance.
        current_user: Current user (optional, for ownership check).

    Returns:
        Chat history with all messages.

    Raises:
        HTTPException: If session not found or access denied.
    """
    user_id = current_user.id if current_user else None

    # First verify session exists and user has access
    session = await session_manager.get_session(session_id, user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied",
        )

    messages = await session_manager.get_history(session_id, user_id)

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            ChatMessageResponse(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp,
            )
            for msg in messages
        ],
        total=len(messages),
    )


@router.post(
    "",
    response_model=ChatHistoryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def add_messages(
    session_id: str,
    history_data: ChatHistoryCreate,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> ChatHistoryResponse:
    """
    Add messages to session history.

    Appends new messages to the existing conversation history.
    Messages are added in the order provided.

    Args:
        session_id: Session unique identifier.
        history_data: Messages to add.
        session_manager: SessionManager instance.
        current_user: Current user (optional, for ownership check).

    Returns:
        Updated chat history.

    Raises:
        HTTPException: If session not found or access denied.
    """
    user_id = current_user.id if current_user else None

    # First verify session exists
    session = await session_manager.get_session(session_id, user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied",
        )

    # Convert to dict format
    messages_to_add = [{"role": msg.role, "content": msg.content} for msg in history_data.messages]

    await session_manager.add_messages(session_id, messages_to_add, user_id)

    # Return updated history
    all_messages = await session_manager.get_history(session_id, user_id)

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            ChatMessageResponse(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp,
            )
            for msg in all_messages
        ],
        total=len(all_messages),
    )


@router.put(
    "",
    response_model=ChatHistoryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def replace_history(
    session_id: str,
    history_data: ChatHistoryReplace,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> ChatHistoryResponse:
    """
    Replace entire session history.

    Deletes all existing messages and replaces them with the provided history.
    Use with caution - this is destructive.

    Args:
        session_id: Session unique identifier.
        history_data: New history to set.
        session_manager: SessionManager instance.
        current_user: Current user (optional, for ownership check).

    Returns:
        New chat history.

    Raises:
        HTTPException: If session not found or access denied.
    """
    user_id = current_user.id if current_user else None

    # First verify session exists
    session = await session_manager.get_session(session_id, user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied",
        )

    # Convert to dict format
    new_messages = [{"role": msg.role, "content": msg.content} for msg in history_data.messages]

    await session_manager.replace_history(session_id, new_messages, user_id)

    # Return updated history
    all_messages = await session_manager.get_history(session_id, user_id)

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            ChatMessageResponse(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp,
            )
            for msg in all_messages
        ],
        total=len(all_messages),
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def clear_history(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    current_user: Optional[User] = Depends(get_current_user),
) -> None:
    """
    Clear all messages from session history.

    Deletes all messages but keeps the session active.

    Args:
        session_id: Session unique identifier.
        session_manager: SessionManager instance.
        current_user: Current user (optional, for ownership check).

    Raises:
        HTTPException: If session not found or access denied.
    """
    user_id = current_user.id if current_user else None

    success = await session_manager.clear_history(session_id, user_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied",
        )
