# services/session_manager.py
"""Session management service for voice chat sessions."""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.session import ChatMessage, Session, SessionConfig, SessionState

if TYPE_CHECKING:
    from speech_pipeline_manager import SpeechPipelineManager
    from audio_in import AudioInputProcessor

logger = logging.getLogger(__name__)

# Configuration
MAX_SESSIONS_PER_USER = int(os.getenv("MAX_SESSIONS_PER_USER", "10"))
SESSION_EXPIRE_HOURS = int(os.getenv("SESSION_EXPIRE_HOURS", "24"))
CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "15"))


class ActiveSession:
    """
    Runtime state for an active session.

    This class holds references to runtime components that cannot be
    stored in the database, such as the SpeechPipelineManager and
    AudioInputProcessor instances.

    Attributes:
        session_id: The database session ID.
        pipeline_manager: The SpeechPipelineManager instance for this session.
        audio_processor: The AudioInputProcessor instance for this session.
        websocket_connected: Whether a WebSocket is currently connected.
        last_activity: Timestamp of last activity.
    """

    def __init__(
        self,
        session_id: str,
        config: SessionConfig,
    ):
        self.session_id = session_id
        self.config = config
        self.pipeline_manager: Optional["SpeechPipelineManager"] = None
        self.audio_processor: Optional["AudioInputProcessor"] = None
        self.websocket_connected: bool = False
        self.last_activity: datetime = datetime.utcnow()
        self._history: List[Dict[str, str]] = []

    @property
    def history(self) -> List[Dict[str, str]]:
        """Get the in-memory chat history."""
        return self._history

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the in-memory history."""
        self._history.append({"role": role, "content": content})
        self.last_activity = datetime.utcnow()

    def clear_history(self) -> None:
        """Clear the in-memory history."""
        self._history.clear()
        self.last_activity = datetime.utcnow()

    def update_config(self, new_config: SessionConfig) -> None:
        """Update the session configuration."""
        self.config = new_config
        self.last_activity = datetime.utcnow()


class SessionManager:
    """
    Service for managing voice chat sessions.

    Provides methods for:
    - Creating, retrieving, and terminating sessions
    - Managing chat history
    - Session expiration and cleanup
    - Runtime resource management (pipeline managers, audio processors)
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the SessionManager.

        Args:
            db: AsyncSession for database operations.
        """
        self.db = db
        # In-memory cache of active sessions with runtime resources
        self._active_sessions: Dict[str, ActiveSession] = {}

    # =========================================================================
    # Session CRUD Operations
    # =========================================================================

    async def create_session(
        self,
        user_id: Optional[str] = None,
        config: Optional[SessionConfig] = None,
        initial_history: Optional[List[Dict[str, str]]] = None,
    ) -> Session:
        """
        Create a new voice chat session.

        Args:
            user_id: Optional owner user ID.
            config: Optional session configuration.
            initial_history: Optional initial chat history.

        Returns:
            Newly created Session object.

        Raises:
            ValueError: If user has reached maximum session limit.
        """
        # Check session limit for authenticated users
        if user_id:
            count = await self._count_user_sessions(user_id)
            if count >= MAX_SESSIONS_PER_USER:
                raise ValueError(f"Maximum session limit ({MAX_SESSIONS_PER_USER}) reached")

        # Create session with default or provided config
        session_config = config or SessionConfig()
        session_id = str(uuid.uuid4())

        session = Session(
            id=session_id,
            user_id=user_id,
            state=SessionState.CREATED,
            config_json=json.dumps(session_config.to_dict()),
            expires_at=datetime.utcnow() + timedelta(hours=SESSION_EXPIRE_HOURS),
        )
        self.db.add(session)
        await self.db.flush()

        # Add initial history if provided
        if initial_history:
            for i, msg in enumerate(initial_history):
                chat_msg = ChatMessage(
                    session_id=session_id,
                    sequence=i,
                    role=msg["role"],
                    content=msg["content"],
                )
                self.db.add(chat_msg)
            await self.db.flush()

        await self.db.refresh(session)

        # Create active session entry
        active = ActiveSession(session_id, session_config)
        if initial_history:
            active._history = list(initial_history)
        self._active_sessions[session_id] = active

        logger.info(f"Created session {session_id} for user {user_id}")
        return session

    async def get_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Session]:
        """
        Get a session by ID.

        Args:
            session_id: Session unique identifier.
            user_id: Optional user ID for ownership verification.

        Returns:
            Session object if found and authorized, None otherwise.
        """
        query = select(Session).where(Session.id == session_id)
        if user_id:
            query = query.where(Session.user_id == user_id)

        result = await self.db.execute(query)
        session = result.scalar_one_or_none()

        if session and session.is_expired:
            await self._expire_session(session)
            return None

        return session

    async def get_session_with_history(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Session]:
        """
        Get a session with its chat history loaded.

        Args:
            session_id: Session unique identifier.
            user_id: Optional user ID for ownership verification.

        Returns:
            Session object with messages loaded, None if not found.
        """
        query = select(Session).options(selectinload(Session.messages)).where(Session.id == session_id)
        if user_id:
            query = query.where(Session.user_id == user_id)

        result = await self.db.execute(query)
        session = result.scalar_one_or_none()

        if session and session.is_expired:
            await self._expire_session(session)
            return None

        return session

    async def list_sessions(
        self,
        user_id: str,
        include_expired: bool = False,
    ) -> List[Session]:
        """
        List all sessions for a user.

        Args:
            user_id: User's unique identifier.
            include_expired: Whether to include expired sessions.

        Returns:
            List of Session objects.
        """
        query = select(Session).where(Session.user_id == user_id)

        if not include_expired:
            query = query.where(Session.state != SessionState.EXPIRED)
            query = query.where(Session.state != SessionState.TERMINATED)

        query = query.order_by(Session.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_session_config(
        self,
        session_id: str,
        config_updates: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Optional[Session]:
        """
        Update session configuration.

        Args:
            session_id: Session unique identifier.
            config_updates: Dictionary of config fields to update.
            user_id: Optional user ID for ownership verification.

        Returns:
            Updated Session object, None if not found.
        """
        session = await self.get_session(session_id, user_id)
        if not session:
            return None

        # Update config
        current_config = session.config
        for key, value in config_updates.items():
            if value is not None and hasattr(current_config, key):
                setattr(current_config, key, value)

        session.config = current_config
        session.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(session)

        # Update active session cache
        if session_id in self._active_sessions:
            self._active_sessions[session_id].update_config(current_config)

        logger.info(f"Updated config for session {session_id}")
        return session

    async def terminate_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Terminate a session.

        Args:
            session_id: Session unique identifier.
            user_id: Optional user ID for ownership verification.

        Returns:
            True if session was terminated, False if not found.
        """
        session = await self.get_session(session_id, user_id)
        if not session:
            return False

        session.state = SessionState.TERMINATED
        session.updated_at = datetime.utcnow()
        await self.db.flush()

        # Cleanup active session
        await self._cleanup_active_session(session_id)

        logger.info(f"Terminated session {session_id}")
        return True

    # =========================================================================
    # History Operations
    # =========================================================================

    async def get_history(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> List[ChatMessage]:
        """
        Get chat history for a session.

        Args:
            session_id: Session unique identifier.
            user_id: Optional user ID for ownership verification.

        Returns:
            List of ChatMessage objects ordered by sequence.
        """
        session = await self.get_session(session_id, user_id)
        if not session:
            return []

        result = await self.db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.sequence)
        )
        return list(result.scalars().all())

    async def add_messages(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        user_id: Optional[str] = None,
    ) -> List[ChatMessage]:
        """
        Add messages to session history.

        Args:
            session_id: Session unique identifier.
            messages: List of messages in OpenAI format (role, content).
            user_id: Optional user ID for ownership verification.

        Returns:
            List of newly created ChatMessage objects.
        """
        session = await self.get_session(session_id, user_id)
        if not session:
            return []

        # Get current max sequence
        result = await self.db.execute(
            select(ChatMessage.sequence)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
        max_seq = result.scalar_one_or_none() or -1

        # Add new messages
        new_messages = []
        for i, msg in enumerate(messages):
            chat_msg = ChatMessage(
                session_id=session_id,
                sequence=max_seq + 1 + i,
                role=msg["role"],
                content=msg["content"],
            )
            self.db.add(chat_msg)
            new_messages.append(chat_msg)

        await self.db.flush()

        # Update active session cache
        if session_id in self._active_sessions:
            for msg in messages:
                self._active_sessions[session_id].add_message(msg["role"], msg["content"])

        logger.info(f"Added {len(messages)} messages to session {session_id}")
        return new_messages

    async def replace_history(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        user_id: Optional[str] = None,
    ) -> List[ChatMessage]:
        """
        Replace entire session history.

        Args:
            session_id: Session unique identifier.
            messages: New history in OpenAI format.
            user_id: Optional user ID for ownership verification.

        Returns:
            List of new ChatMessage objects.
        """
        session = await self.get_session(session_id, user_id)
        if not session:
            return []

        # Delete existing messages
        await self.db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))

        # Add new messages
        new_messages = []
        for i, msg in enumerate(messages):
            chat_msg = ChatMessage(
                session_id=session_id,
                sequence=i,
                role=msg["role"],
                content=msg["content"],
            )
            self.db.add(chat_msg)
            new_messages.append(chat_msg)

        await self.db.flush()

        # Update active session cache
        if session_id in self._active_sessions:
            self._active_sessions[session_id].clear_history()
            for msg in messages:
                self._active_sessions[session_id].add_message(msg["role"], msg["content"])

        logger.info(f"Replaced history for session {session_id}")
        return new_messages

    async def clear_history(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Clear session history.

        Args:
            session_id: Session unique identifier.
            user_id: Optional user ID for ownership verification.

        Returns:
            True if history was cleared, False if session not found.
        """
        session = await self.get_session(session_id, user_id)
        if not session:
            return False

        await self.db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
        await self.db.flush()

        # Update active session cache
        if session_id in self._active_sessions:
            self._active_sessions[session_id].clear_history()

        logger.info(f"Cleared history for session {session_id}")
        return True

    # =========================================================================
    # WebSocket Connection Management
    # =========================================================================

    async def connect_websocket(
        self,
        session_id: str,
    ) -> Optional[ActiveSession]:
        """
        Mark a session as having an active WebSocket connection.

        Args:
            session_id: Session unique identifier.

        Returns:
            ActiveSession if successful, None if session not found.
        """
        session = await self.get_session(session_id)
        if not session:
            return None

        # Update database state
        session.state = SessionState.ACTIVE
        session.websocket_connected = True
        session.updated_at = datetime.utcnow()
        await self.db.flush()

        # Get or create active session
        if session_id not in self._active_sessions:
            active = ActiveSession(session_id, session.config)
            # Load history from database
            messages = await self.get_history(session_id)
            active._history = [{"role": m.role, "content": m.content} for m in messages]
            self._active_sessions[session_id] = active
        else:
            active = self._active_sessions[session_id]

        active.websocket_connected = True
        logger.info(f"WebSocket connected for session {session_id}")
        return active

    async def disconnect_websocket(
        self,
        session_id: str,
    ) -> None:
        """
        Mark a session as having disconnected WebSocket.

        Args:
            session_id: Session unique identifier.
        """
        session = await self.get_session(session_id)
        if session:
            session.state = SessionState.PAUSED
            session.websocket_connected = False
            session.updated_at = datetime.utcnow()
            await self.db.flush()

        if session_id in self._active_sessions:
            self._active_sessions[session_id].websocket_connected = False

        logger.info(f"WebSocket disconnected for session {session_id}")

    def get_active_session(self, session_id: str) -> Optional[ActiveSession]:
        """
        Get the active session runtime state.

        Args:
            session_id: Session unique identifier.

        Returns:
            ActiveSession if exists, None otherwise.
        """
        return self._active_sessions.get(session_id)

    # =========================================================================
    # Cleanup Operations
    # =========================================================================

    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.

        Returns:
            Number of sessions cleaned up.
        """
        result = await self.db.execute(
            select(Session)
            .where(Session.state.not_in([SessionState.EXPIRED, SessionState.TERMINATED]))
            .where(Session.expires_at < datetime.utcnow())
        )
        expired_sessions = result.scalars().all()

        for session in expired_sessions:
            await self._expire_session(session)

        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")

        return len(expired_sessions)

    async def _count_user_sessions(self, user_id: str) -> int:
        """Count active sessions for a user."""
        result = await self.db.execute(
            select(Session)
            .where(Session.user_id == user_id)
            .where(Session.state.not_in([SessionState.EXPIRED, SessionState.TERMINATED]))
        )
        return len(result.scalars().all())

    async def _expire_session(self, session: Session) -> None:
        """Mark a session as expired and cleanup resources."""
        session.state = SessionState.EXPIRED
        session.updated_at = datetime.utcnow()
        await self.db.flush()
        await self._cleanup_active_session(session.id)

    async def _cleanup_active_session(self, session_id: str) -> None:
        """Cleanup active session resources."""
        if session_id in self._active_sessions:
            active = self._active_sessions[session_id]
            # Cleanup pipeline manager if exists
            if active.pipeline_manager:
                try:
                    active.pipeline_manager.abort_generation(reason="session_cleanup")
                except Exception as e:
                    logger.warning(f"Error cleaning up pipeline manager: {e}")
            # Cleanup audio processor if exists
            if active.audio_processor:
                try:
                    active.audio_processor.shutdown()
                except Exception as e:
                    logger.warning(f"Error cleaning up audio processor: {e}")
            del self._active_sessions[session_id]
            logger.info(f"Cleaned up active session resources for {session_id}")


# Background cleanup task
async def session_cleanup_task(db_factory) -> None:
    """
    Background task for periodic session cleanup.

    Args:
        db_factory: Async session factory for creating database sessions.
    """
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)
            async with db_factory() as db:
                manager = SessionManager(db)
                cleaned = await manager.cleanup_expired_sessions()
                if cleaned > 0:
                    logger.info(f"Session cleanup task removed {cleaned} expired sessions")
        except asyncio.CancelledError:
            logger.info("Session cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in session cleanup task: {e}")
