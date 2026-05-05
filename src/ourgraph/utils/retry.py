"""Retry utilities for database operations.

Mirrors ourportfolios/utils/retry.py interface so engine.py is drop-in compatible.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

RETRIABLE_EXCEPTIONS = (
    ConnectionError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


async def retry_async[**P, T](
    fn: Callable[P, Awaitable[T]],
    *args: P.args,
    max_attempts: int = 3,
    wait_ms: int = 500,
    **kwargs: P.kwargs,
) -> T:
    """Retry an async callable up to max_attempts times with linear backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except RETRIABLE_EXCEPTIONS as exc:
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
    if last_exc is not None:
        raise last_exc
    message = "retry_async failed without capturing an exception"
    raise RuntimeError(message)


def retry_sync[**P, T](
    fn: Callable[P, T],
    *args: P.args,
    max_attempts: int = 3,
    wait_ms: int = 500,
    **kwargs: P.kwargs,
) -> T:
    """Retry a sync callable up to max_attempts times with linear backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except RETRIABLE_EXCEPTIONS as exc:
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
    if last_exc is not None:
        raise last_exc
    message = "retry_sync failed without capturing an exception"
    raise RuntimeError(message)
