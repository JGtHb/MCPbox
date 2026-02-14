"""MCPbox Database Configuration - Async SQLAlchemy."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.core.config import settings

# Connection pool settings are configurable via environment variables:
# - DB_POOL_SIZE: Number of connections to keep in the pool (default: 20)
# - DB_MAX_OVERFLOW: Additional connections allowed beyond pool_size during high load (default: 20)
# - DB_POOL_TIMEOUT: Seconds to wait before giving up on getting a connection (default: 30)
# - DB_POOL_RECYCLE: Recycle connections after this many seconds (default: 1800 = 30 min)

# Create async engine with connection pool settings
engine = create_async_engine(
    str(settings.database_url),
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,  # Verify connection before use
    # Only echo SQL when debug is explicitly enabled
    echo=settings.debug and settings.log_level == "DEBUG",
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except (Exception, BaseException):
            # Catch both regular exceptions and BaseExceptions (e.g., asyncio.CancelledError)
            # to ensure rollback happens even on cancellation
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connection() -> bool:
    """Check if database is reachable."""
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
            return True
    except (OSError, ConnectionError) as e:
        # Expected network/connection errors
        from app.core.logging import get_logger

        get_logger("database").debug(f"Database connection check failed: {e}")
        return False
    except Exception as e:
        # Unexpected errors - log them
        from app.core.logging import get_logger

        get_logger("database").warning(f"Unexpected error checking database connection: {e}")
        return False
