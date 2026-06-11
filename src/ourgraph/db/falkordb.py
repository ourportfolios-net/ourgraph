"""FalkorDB async connection factory.

Returns the async FalkorDB client using settings from config.
The graph (database) name is also set here — never hardcoded downstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from falkordb.asyncio import FalkorDB

if TYPE_CHECKING:
    from ourgraph.config import FalkorDBSettings


def build_falkordb_client(settings: FalkorDBSettings) -> FalkorDB:
    """Create an async FalkorDB client.

    Uses a connection pool (BlockingConnectionPool) automatically managed
    by the falkordb-py async client.

    Prefers connection URL (settings.url) over individual host/port fields.
    """
    if settings.url:
        return FalkorDB.from_url(settings.url)

    kwargs: dict = {
        "host": settings.host,
        "port": settings.port,
    }
    if settings.username:
        kwargs["username"] = settings.username
    if settings.password:
        kwargs["password"] = settings.password

    return FalkorDB(**kwargs)
