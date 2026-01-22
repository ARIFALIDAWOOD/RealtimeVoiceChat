# services/auth_service.py
"""Authentication service for JWT token management and user authentication."""

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

logger = logging.getLogger(__name__)

# Configuration from environment
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """
    Service for handling authentication operations.

    Provides methods for:
    - User registration and login
    - Password hashing and verification
    - JWT token creation and validation
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the AuthService.

        Args:
            db: AsyncSession for database operations.
        """
        self.db = db

    # =========================================================================
    # Password Operations
    # =========================================================================

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password.

        Returns:
            Hashed password string.
        """
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            plain_password: Plain text password to verify.
            hashed_password: Stored hashed password.

        Returns:
            True if password matches, False otherwise.
        """
        return pwd_context.verify(plain_password, hashed_password)

    # =========================================================================
    # Token Operations
    # =========================================================================

    @staticmethod
    def create_access_token(
        user_id: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """
        Create a JWT access token.

        Args:
            user_id: User's unique identifier to encode in token.
            expires_delta: Optional custom expiration time.

        Returns:
            Encoded JWT token string.
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        expire = datetime.utcnow() + expires_delta
        to_encode = {
            "sub": user_id,
            "exp": expire,
            "type": "access",
            "iat": datetime.utcnow(),
        }
        return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def create_refresh_token(user_id: str) -> str:
        """
        Create a JWT refresh token.

        Args:
            user_id: User's unique identifier to encode in token.

        Returns:
            Encoded JWT refresh token string.
        """
        expire = datetime.utcnow() + timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode = {
            "sub": user_id,
            "exp": expire,
            "type": "refresh",
            "iat": datetime.utcnow(),
        }
        return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        """
        Decode and validate a JWT token.

        Args:
            token: JWT token string to decode.

        Returns:
            Decoded token payload if valid, None otherwise.
        """
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except JWTError as e:
            logger.warning(f"JWT decode error: {e}")
            return None

    @staticmethod
    def get_user_id_from_token(token: str) -> Optional[str]:
        """
        Extract user ID from a JWT token.

        Args:
            token: JWT token string.

        Returns:
            User ID if token is valid, None otherwise.
        """
        payload = AuthService.decode_token(token)
        if payload is None:
            return None
        return payload.get("sub")

    # =========================================================================
    # User Operations
    # =========================================================================

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get a user by email address.

        Args:
            email: User's email address.

        Returns:
            User object if found, None otherwise.
        """
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get a user by their ID.

        Args:
            user_id: User's unique identifier.

        Returns:
            User object if found, None otherwise.
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user(self, email: str, password: str) -> User:
        """
        Create a new user.

        Args:
            email: User's email address.
            password: User's plain text password (will be hashed).

        Returns:
            Newly created User object.

        Raises:
            ValueError: If email already exists.
        """
        # Check if user already exists
        existing = await self.get_user_by_email(email)
        if existing:
            raise ValueError("User with this email already exists")

        # Create new user
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            hashed_password=self.hash_password(password),
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)

        logger.info(f"Created new user: {email}")
        return user

    async def authenticate_user(
        self,
        email: str,
        password: str,
    ) -> Optional[User]:
        """
        Authenticate a user by email and password.

        Args:
            email: User's email address.
            password: User's plain text password.

        Returns:
            User object if authentication successful, None otherwise.
        """
        user = await self.get_user_by_email(email)
        if user is None:
            logger.warning(f"Authentication failed: user not found for {email}")
            return None

        if not user.is_active:
            logger.warning(f"Authentication failed: user inactive for {email}")
            return None

        if not self.verify_password(password, user.hashed_password):
            logger.warning(f"Authentication failed: invalid password for {email}")
            return None

        logger.info(f"User authenticated successfully: {email}")
        return user

    async def get_current_user(self, token: str) -> Optional[User]:
        """
        Get the current user from a JWT token.

        Args:
            token: JWT access token.

        Returns:
            User object if token is valid, None otherwise.
        """
        user_id = self.get_user_id_from_token(token)
        if user_id is None:
            return None

        user = await self.get_user_by_id(user_id)
        if user is None or not user.is_active:
            return None

        return user

    async def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        """
        Create a new access token from a valid refresh token.

        Args:
            refresh_token: JWT refresh token.

        Returns:
            New access token if refresh token is valid, None otherwise.
        """
        payload = self.decode_token(refresh_token)
        if payload is None:
            return None

        if payload.get("type") != "refresh":
            logger.warning("Token refresh failed: not a refresh token")
            return None

        user_id = payload.get("sub")
        if user_id is None:
            return None

        # Verify user still exists and is active
        user = await self.get_user_by_id(user_id)
        if user is None or not user.is_active:
            return None

        return self.create_access_token(user_id)
