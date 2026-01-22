# api/routes/auth.py
"""Authentication routes for user registration, login, and token management."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_auth_service, require_current_user
from api.models import (
    ErrorResponse,
    TokenRefresh,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from models.user import User
from services.auth_service import AuthService, JWT_ACCESS_TOKEN_EXPIRE_MINUTES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Email already registered"},
    },
)
async def register(
    user_data: UserCreate,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """
    Register a new user account.

    Args:
        user_data: User registration data (email, password).
        auth_service: AuthService instance.

    Returns:
        Created user information.

    Raises:
        HTTPException: If email is already registered.
    """
    try:
        user = await auth_service.create_user(
            email=user_data.email,
            password=user_data.password,
        )
        return UserResponse(
            id=user.id,
            email=user.email,
            is_active=user.is_active,
            created_at=user.created_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
    },
)
async def login(
    credentials: UserLogin,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """
    Authenticate user and return JWT tokens.

    Args:
        credentials: User login credentials (email, password).
        auth_service: AuthService instance.

    Returns:
        JWT access token and metadata.

    Raises:
        HTTPException: If credentials are invalid.
    """
    user = await auth_service.authenticate_user(
        email=credentials.email,
        password=credentials.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = auth_service.create_access_token(user.id)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid refresh token"},
    },
)
async def refresh_token(
    token_data: TokenRefresh,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """
    Refresh an access token using a refresh token.

    Args:
        token_data: Refresh token data.
        auth_service: AuthService instance.

    Returns:
        New JWT access token.

    Raises:
        HTTPException: If refresh token is invalid.
    """
    new_access_token = await auth_service.refresh_access_token(token_data.refresh_token)

    if new_access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_current_user_info(
    current_user: User = Depends(require_current_user),
) -> UserResponse:
    """
    Get current authenticated user's information.

    Args:
        current_user: Current authenticated user from JWT.

    Returns:
        Current user information.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
