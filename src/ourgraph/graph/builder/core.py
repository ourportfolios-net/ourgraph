"""Core GraphBuilder class — constructor, connection, context manager, index setup."""

from __future__ import annotations

import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Self

from ourgraph.graph.schema import NodeLabel, Prop

if TYPE_CHECKING:
    from ourgraph.config import FalkorDBSettings
    from ourgraph.graph.builder import GraphBuilder

logger = logging.getLogger(__name__)


class _GraphBuilderCore:
    """Async graph builder backed by FalkorDB — core methods only.

    Domain methods (companies, financials, people, relations, dedup) are
    provided by mixin classes defined in sibling modules and combined
    in ``__init__.py``'s ``GraphBuilder``.
    """

    def __init__(self, client: object, graph_name: str) -> None:
        self._client = client
        self._graph_name = graph_name

    @classmethod
    def from_settings(cls: type[GraphBuilder], settings: FalkorDBSettings) -> GraphBuilder:
        """Create a GraphBuilder from FalkorDB settings."""
        from ourgraph.graph.builder import GraphBuilder

        return GraphBuilder(
            client=build_falkordb_client(settings),
            graph_name=settings.graph_name,
        )

    async def _graph(self) -> object:
        return self._client.select_graph(self._graph_name)  # type: ignore

    async def _run(self, query: str, params: dict | None = None) -> list:
        """Execute a Cypher query and return the result set."""
        g = await self._graph()
        query_method = getattr(g, "query")
        result = await query_method(query, params or {})
        return result.result_set

    async def query_raw(self, query: str, params: dict | None = None) -> list:
        """Public wrapper for running raw Cypher queries."""
        return await self._run(query, params)

    # ------------------------------------------------------------------
    # Index setup
    # ------------------------------------------------------------------

    async def ensure_indices(self) -> None:
        """Create indices for all node property lookups."""
        indices = [
            f"CREATE INDEX ON :{NodeLabel.COMPANY}({Prop.SYMBOL})",
            f"CREATE INDEX ON :{NodeLabel.COMPANY}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.PERSON}({Prop.PERSON_NAME})",
            f"CREATE INDEX ON :{NodeLabel.SECTOR}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.INDUSTRY}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.FINANCIAL_STATEMENT}({Prop.SYMBOL}, {Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.INDICATOR}({Prop.SYMBOL}, {Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.DATE}({Prop.DATE})",
            f"CREATE INDEX ON :{NodeLabel.QUARTER}({Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.YEAR}({Prop.YEAR})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.DATE})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.COUNTRY})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.CATEGORY})",
            f"CREATE INDEX ON :{NodeLabel.COUNTRY}({Prop.CODE})",
            f"CREATE INDEX ON :{NodeLabel.COUNTRY}({Prop.NAME})",
        ]
        for idx in indices:
            try:
                await self._run(idx)
            except Exception as exc:
                exc_str = str(exc).lower()
                if "already exists" not in exc_str and "already indexed" not in exc_str:
                    logger.warning("Index warning: %s — %s", idx, exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def clear_graph(self) -> dict[str, int]:
        """Delete all nodes and relationships in the graph."""
        node_rows = await self._run("MATCH (n) RETURN COUNT(n)")
        rel_rows = await self._run("MATCH ()-[r]->() RETURN COUNT(r)")
        nodes_before = int(node_rows[0][0]) if node_rows else 0
        rels_before = int(rel_rows[0][0]) if rel_rows else 0
        await self._run("MATCH (n) DETACH DELETE n")
        logger.warning(
            "Cleared graph '%s' (deleted nodes=%d, relationships=%d)",
            self._graph_name,
            nodes_before,
            rels_before,
        )
        return {"deleted_nodes": nodes_before, "deleted_relationships": rels_before}

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit async context manager."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying FalkorDB client."""
        with contextlib.suppress(Exception):
            close = getattr(self._client, "close", None)
            if callable(close):
                maybe_awaitable = close()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable


# Late import for from_settings to avoid circular dependency
def build_falkordb_client(settings: object) -> object:
    """Lazy import and build FalkorDB client."""
    from ourgraph.db.falkordb import build_falkordb_client as _build

    return _build(settings)  # type: ignore
