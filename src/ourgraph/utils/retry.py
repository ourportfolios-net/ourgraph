"""
Retry utilities for database operations.

Mirrors ourportfolios/utils/retry.py interface so engine.py is drop-in compatible.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    fn: Callable,
    *args,
    max_attempts: int = 3,
    wait_ms: int = 500,
    **kwargs,
):
    """Retry an async callable up to max_attempts times with linear backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Retry %d/%d for %s: %s",
                attempt,
                max_attempts,
                getattr(fn, "__name__", fn),
                exc,
            )
            if attempt < max_attempts:
                await asyncio.sleep(wait_ms / 1000)
    raise last_exc  # type: ignore[misc]


def retry_sync(
    fn: Callable,
    *args,
    max_attempts: int = 3,
    wait_ms: int = 500,
    **kwargs,
):
    """Retry a sync callable up to max_attempts times with linear backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Retry %d/%d for %s: %s",
                attempt,
                max_attempts,
                getattr(fn, "__name__", fn),
                exc,
            )
            if attempt < max_attempts:
                time.sleep(wait_ms / 1000)
    raise last_exc  # type: ignore[misc]
