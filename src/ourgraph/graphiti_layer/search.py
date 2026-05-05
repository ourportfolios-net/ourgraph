"""
GraphRAG search interface.

Provides a high-level search API over Graphiti's temporal knowledge graph.
The LLM receives graph context automatically via Graphiti's hybrid retrieval.

Key features provided by Graphiti:
  - Hybrid search: BM25 (full-text) + vector (semantic) + graph traversal
  - Temporal awareness: answers reflect what was true at a given point in time
  - Provenance: every result traces back to the episode that produced it
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config import SearchConfig

from ourgraph.config import AppSettings
from ourgraph.graphiti_layer.client import (
    GRAPHITI_GRAPH_SUFFIX,
    build_graphiti_client,
)

logger = logging.getLogger(__name__)


class GraphRAGSearch:
    """
    High-level GraphRAG search over the stock knowledge graph.

    Usage::

        search = await GraphRAGSearch.create(settings)
        results = await search.query("What are VCB's main subsidiaries?")
        await search.close()
    """

    def __init__(self, client: Graphiti, group_id: str) -> None:
        self._client = client
        self._group_id = group_id

    @classmethod
    async def create(cls, settings: AppSettings) -> GraphRAGSearch:
        """Build, initialise indices, and return a ready-to-use instance."""
        client = build_graphiti_client(settings)
        await client.build_indices_and_constraints()
        group_id = settings.falkordb.graph_name + GRAPHITI_GRAPH_SUFFIX
        return cls(client=client, group_id=group_id)

    # ------------------------------------------------------------------
    # Episode ingestion (add knowledge to Graphiti)
    # ------------------------------------------------------------------

    async def add_text_episode(
        self,
        name: str,
        body: str,
        reference_time: datetime | None = None,
        source_description: str = "ourgraph",
    ) -> None:
        """
        Add a free-text episode (e.g. analyst report, financial summary).

        Graphiti extracts entities and relationships automatically using the
        configured LLM. For small local models, keep `body` concise (<500 words)
        to improve structured output reliability.

        Args:
            name: Short descriptive name for the episode.
            body: The text content.
            reference_time: When this information was true. Defaults to now.
            source_description: Free-form provenance label.
        """
        if reference_time is None:
            reference_time = datetime.now(UTC)

        await self._client.add_episode(
            name=name,
            episode_body=body,
            source=EpisodeType.text,
            reference_time=reference_time,
            source_description=source_description,
            group_id=self._group_id,
        )
        logger.debug("Added episode: %s", name)

    async def add_json_episode(
        self,
        name: str,
        data: dict,
        reference_time: datetime | None = None,
        source_description: str = "ourgraph",
    ) -> None:
        """
        Add a structured JSON episode (e.g. financial statement snapshot).

        JSON episodes are ingested without LLM extraction — the structure
        is preserved as-is. This is the recommended path for structured data
        when using small local models.
        """
        import json

        if reference_time is None:
            reference_time = datetime.now(UTC)

        await self._client.add_episode(
            name=name,
            episode_body=json.dumps(data, ensure_ascii=False),
            source=EpisodeType.json,
            reference_time=reference_time,
            source_description=source_description,
            group_id=self._group_id,
        )
        logger.debug("Added JSON episode: %s", name)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        num_results: int = 10,
    ) -> list[dict]:
        """
        Run a hybrid GraphRAG search.

        Returns a list of fact dicts from Graphiti's knowledge graph,
        ranked by relevance. The LLM can then synthesise an answer
        from these facts.

        Args:
            question: Natural language question.
            num_results: Maximum number of facts to return.

        Returns:
            List of result dicts with keys: fact, valid_at, invalid_at, ...
        """
        results = await self._client.search(
            query=question,
            num_results=num_results,
            group_ids=[self._group_id],
        )
        # Graphiti returns EdgeResult objects — convert to plain dicts
        return [
            {
                "fact": r.fact,
                "valid_at": r.valid_at.isoformat() if r.valid_at else None,
                "invalid_at": r.invalid_at.isoformat() if r.invalid_at else None,
                "uuid": str(r.uuid),
            }
            for r in results
        ]

    async def get_nodes(self, query: str, num_results: int = 10) -> list[dict]:
        """
        Retrieve entity nodes matching a query.

        Useful for finding companies, sectors, or officers by name.
        """
        results = await self._client.search_(
            query=query,
            config=SearchConfig(limit=num_results),
            group_ids=[self._group_id],
        )
        return [
            {
                "name": n.name,
                "summary": getattr(n, "summary", ""),
                "uuid": str(n.uuid),
            }
            for n in results.nodes
        ]

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.close()
