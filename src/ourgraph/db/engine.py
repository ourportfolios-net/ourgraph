"""
SQLAlchemy async + sync engines for the Supabase database.

Mirrors the pattern from ourportfolios/utils/database/database.py:
  - NullPool for serverless-safe connections
  - RetryingAsyncSession wraps commit with retry logic
  - Both async (for the pipeline) and sync (for polars pl.read_database) engines

Environment variables:
  SUPABASE_DB_URL  — standard postgresql:// URL (sync driver auto-detected)
                     asyncpg driver is injected automatically for async engines.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from ourgraph.config import get_settings
from ourgraph.utils.retry import retry_async, retry_sync


def _strip_query_params(url: str) -> str:
    return url.split("?", maxsplit=1)[0] if "?" in url else url


def _to_async_pg(url: str | None) -> str:
    """Inject asyncpg driver into a postgresql:// URL."""
    if url is None:
        raise ValueError(
            "SUPABASE_DB_URL is not set. "
            "Add it to your .env: "
            "SUPABASE_DB_URL=postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres"
        )
    url = _strip_query_params(url)
    if "postgresql+asyncpg" in url:
        return url
    if "postgresql+psycopg2" in url:
        return url.replace("postgresql+psycopg2", "postgresql+asyncpg")
    if "postgresql://" in url and "+" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://")
    return url


def _to_sync_pg(url: str | None) -> str:
    """Strip async drivers from URL for sync psycopg2 usage."""
    if url is None:
        raise ValueError("SUPABASE_DB_URL is not set.")
    url = _strip_query_params(url)
    if "postgresql+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql")
    return url


_raw_url = get_settings().supabase.supabase_db_url or None
_neon_url = get_settings().supabase.neon_db_url or None

async_engine = create_async_engine(
    _to_async_pg(_raw_url),
    poolclass=NullPool,
    connect_args={
        "server_settings": {"jit": "off"},
        "timeout": 10,
        "command_timeout": 20,
        "statement_cache_size": 0,
    },
)

neon_async_engine = create_async_engine(
    _to_async_pg(_neon_url) if _neon_url else _to_async_pg(_raw_url),
    poolclass=NullPool,
    connect_args={
        "server_settings": {"jit": "off"},
        "timeout": 10,
        "command_timeout": 20,
        "statement_cache_size": 0,
    },
)

sync_engine = create_engine(
    _to_sync_pg(_raw_url),
    poolclass=NullPool,
    connect_args={"sslmode": "require", "connect_timeout": 10},
)


class RetryingAsyncSession(AsyncSession):
    async def commit(self) -> None:
        await retry_async(super().commit)


AsyncSessionFactory = async_sessionmaker(
    async_engine,
    class_=RetryingAsyncSession,
    expire_on_commit=False,
)

NeonSessionFactory = async_sessionmaker(
    neon_async_engine,
    class_=RetryingAsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager that yields a session with auto-commit + rollback."""
    session = retry_sync(AsyncSessionFactory, max_attempts=5, wait_ms=1000)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def get_neon_session() -> AsyncIterator[AsyncSession]:
    """Async context manager that yields a session to Neon DB."""
    session = retry_sync(NeonSessionFactory, max_attempts=5, wait_ms=1000)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
