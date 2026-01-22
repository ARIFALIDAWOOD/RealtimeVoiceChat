# database.py
"""Database configuration and session management using SQLAlchemy async."""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)

# Load database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./voicechat.db")  # Default to SQLite for development

# Check if using SQLite (for special handling)
IS_SQLITE = DATABASE_URL.startswith("sqlite")


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for all models."""

    pass


# Global engine and session factory (initialized in init_db)
_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Get the database engine, raising an error if not initialized."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory, raising an error if not initialized."""
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _async_session_factory


async def init_db(database_url: Optional[str] = None) -> None:
    """
    Initialize the database engine and create all tables.

    Args:
        database_url: Optional database URL override. If not provided,
                     uses the DATABASE_URL environment variable.
    """
    global _engine, _async_session_factory

    url = database_url or DATABASE_URL
    is_sqlite = url.startswith("sqlite")

    logger.info(f"Initializing database connection: {url.split('@')[-1] if '@' in url else url}")

    # Configure engine options based on database type
    engine_kwargs = {
        "echo": os.getenv("DATABASE_ECHO", "false").lower() == "true",
    }

    if is_sqlite:
        # SQLite-specific configuration
        engine_kwargs.update(
            {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,  # Use static pool for SQLite
            }
        )
    else:
        # PostgreSQL/other async databases
        engine_kwargs.update(
            {
                "pool_size": int(os.getenv("DATABASE_POOL_SIZE", "5")),
                "max_overflow": int(os.getenv("DATABASE_MAX_OVERFLOW", "10")),
                "pool_pre_ping": True,
            }
        )

    _engine = create_async_engine(url, **engine_kwargs)

    # Enable foreign keys for SQLite
    if is_sqlite:

        @event.listens_for(_engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    # Create all tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized and tables created successfully")


async def close_db() -> None:
    """Close the database connection."""
    global _engine, _async_session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
        logger.info("Database connection closed")


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Yields:
        AsyncSession: A database session that will be automatically
                     committed on success or rolled back on error.

    Example:
        async with get_db_session() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Yields:
        AsyncSession: A database session for the request.

    Example:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    """
    async with get_db_session() as session:
        yield session
