# api/models.py
"""Pydantic models for API request/response validation."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

# =============================================================================
# Authentication Models
# =============================================================================


class UserCreate(BaseModel):
    """Request model for user registration."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


class UserLogin(BaseModel):
    """Request model for user login."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")


class UserResponse(BaseModel):
    """Response model for user data."""

    id: str = Field(..., description="User's unique identifier")
    email: str = Field(..., description="User's email address")
    is_active: bool = Field(..., description="Whether the user is active")
    created_at: datetime = Field(..., description="Account creation timestamp")

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Response model for JWT token."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")


class TokenRefresh(BaseModel):
    """Request model for token refresh."""

    refresh_token: str = Field(..., description="Refresh token")


# =============================================================================
# Session Configuration Models
# =============================================================================


class SessionConfigCreate(BaseModel):
    """Request model for session configuration."""

    llm_provider: str = Field(
        default="openai",
        description="LLM provider (openai, ollama, lmstudio)",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="LLM model identifier",
    )
    tts_engine: str = Field(
        default="kokoro",
        description="TTS engine (kokoro, coqui, orpheus)",
    )
    tts_voice: str = Field(
        default="af_heart",
        description="TTS voice identifier",
    )
    persona: str = Field(
        default="default",
        description="Persona name from system_prompts.json",
    )
    verbosity: str = Field(
        default="normal",
        description="Verbosity level (brief, normal, detailed)",
    )
    language: str = Field(
        default="en",
        description="Language code for STT/TTS",
    )
    no_think: bool = Field(
        default=False,
        description="Strip thinking tags from LLM output",
    )


class SessionConfigUpdate(BaseModel):
    """Request model for updating session configuration (all fields optional)."""

    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    tts_engine: Optional[str] = None
    tts_voice: Optional[str] = None
    persona: Optional[str] = None
    verbosity: Optional[str] = None
    language: Optional[str] = None
    no_think: Optional[bool] = None


class SessionConfigResponse(BaseModel):
    """Response model for session configuration."""

    llm_provider: str
    llm_model: str
    tts_engine: str
    tts_voice: str
    persona: str
    verbosity: str
    language: str
    no_think: bool


# =============================================================================
# Session Models
# =============================================================================


class SessionCreate(BaseModel):
    """Request model for creating a new session."""

    config: Optional[SessionConfigCreate] = Field(
        default=None,
        description="Optional initial configuration",
    )
    initial_history: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Optional initial chat history (OpenAI format)",
    )


class SessionResponse(BaseModel):
    """Response model for session data."""

    id: str = Field(..., description="Session unique identifier")
    user_id: Optional[str] = Field(None, description="Owner user ID (if authenticated)")
    state: str = Field(..., description="Session state")
    config: SessionConfigResponse = Field(..., description="Session configuration")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: datetime = Field(..., description="Expiration timestamp")
    websocket_connected: bool = Field(..., description="WebSocket connection status")
    message_count: int = Field(default=0, description="Number of messages in history")

    class Config:
        from_attributes = True


class SessionListResponse(BaseModel):
    """Response model for listing sessions."""

    sessions: List[SessionResponse] = Field(..., description="List of sessions")
    total: int = Field(..., description="Total number of sessions")


# =============================================================================
# Chat History Models
# =============================================================================


class ChatMessageCreate(BaseModel):
    """Request model for adding a chat message."""

    role: str = Field(
        ...,
        description="Message role (user, assistant, system)",
        pattern="^(user|assistant|system)$",
    )
    content: str = Field(..., description="Message content")


class ChatMessageResponse(BaseModel):
    """Response model for a chat message."""

    id: int = Field(..., description="Message ID")
    role: str = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(..., description="Message timestamp")

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    """Response model for chat history."""

    session_id: str = Field(..., description="Session ID")
    messages: List[ChatMessageResponse] = Field(..., description="Chat messages")
    total: int = Field(..., description="Total number of messages")


class ChatHistoryCreate(BaseModel):
    """Request model for adding multiple messages to history."""

    messages: List[ChatMessageCreate] = Field(
        ...,
        description="Messages to add",
        min_length=1,
    )


class ChatHistoryReplace(BaseModel):
    """Request model for replacing entire history."""

    messages: List[ChatMessageCreate] = Field(
        ...,
        description="New history messages",
    )


# =============================================================================
# Configuration Discovery Models
# =============================================================================


class PersonaInfo(BaseModel):
    """Information about an available persona."""

    id: str = Field(..., description="Persona identifier")
    name: str = Field(..., description="Display name")
    description: Optional[str] = Field(None, description="Brief description")


class PersonasResponse(BaseModel):
    """Response model for listing personas."""

    personas: List[PersonaInfo] = Field(..., description="Available personas")


class LLMProviderInfo(BaseModel):
    """Information about an LLM provider."""

    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Display name")
    models: List[str] = Field(..., description="Available models")
    available: bool = Field(..., description="Whether provider is available")


class LLMProvidersResponse(BaseModel):
    """Response model for listing LLM providers."""

    providers: List[LLMProviderInfo] = Field(..., description="Available providers")


class TTSEngineInfo(BaseModel):
    """Information about a TTS engine."""

    id: str = Field(..., description="Engine identifier")
    name: str = Field(..., description="Display name")
    voices: List[str] = Field(..., description="Available voices")
    available: bool = Field(..., description="Whether engine is available")


class TTSEnginesResponse(BaseModel):
    """Response model for listing TTS engines."""

    engines: List[TTSEngineInfo] = Field(..., description="Available TTS engines")


class VerbosityLevel(BaseModel):
    """Information about a verbosity level."""

    id: str = Field(..., description="Verbosity identifier")
    name: str = Field(..., description="Display name")
    description: Optional[str] = Field(None, description="Brief description")


class VerbosityLevelsResponse(BaseModel):
    """Response model for listing verbosity levels."""

    levels: List[VerbosityLevel] = Field(..., description="Available verbosity levels")


# =============================================================================
# Health Check Models
# =============================================================================


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Health status (healthy, degraded, unhealthy)")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(..., description="Current server timestamp")


class ReadinessResponse(BaseModel):
    """Response model for readiness check."""

    ready: bool = Field(..., description="Whether the service is ready")
    database: str = Field(..., description="Database connection status")
    redis: str = Field(..., description="Redis connection status")
    tts_engine: str = Field(..., description="TTS engine status")
    llm_provider: str = Field(..., description="LLM provider status")


# =============================================================================
# Error Models
# =============================================================================


class ErrorResponse(BaseModel):
    """Response model for errors."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
