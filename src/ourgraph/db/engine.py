"""SQLAlchemy async engine for cloud database (Tiger Data / TimescaleDB).

Minimal setup — will be expanded when Tiger Data connection is configured.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from ourgraph.config import get_settings

# Placeholder for Tiger Data URL (set in .env as TIGER_DATA_URL)
_raw_url = get_settings().tiger_data.url or None


if _raw_url:
    async_engine = create_async_engine(
        _raw_url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {"jit": "off"},
            "timeout": 10,
            "command_timeout": 20,
            "statement_cache_size": 0,
        },
    )
else:
    async_engine = None


class RetryingAsyncSession(AsyncSession):
    async def commit(self) -> None:
        await super().commit()


if async_engine:
    AsyncSessionFactory = async_sessionmaker(
        async_engine,
        class_=RetryingAsyncSession,
        expire_on_commit=False,
    )
else:
    AsyncSessionFactory = None


async def get_session():
    """Async context manager that yields a session."""
    if AsyncSessionFactory is None:
        error_msg = "No database configured. Set TIGER_DATA_URL in .env"
        raise RuntimeError(error_msg)
    session = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
