"""RelationshipManager — validates and manages relationships in the graph.

Provides CRUD operations with validation against the relationship schema,
temporal support (validity periods), and conflict resolution.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from ourgraph.graph.relationship_schema import (
    allowed_properties,
    validate_relationship,
)

if TYPE_CHECKING:
    from ourgraph.graph.builder import GraphBuilder

logger = logging.getLogger(__name__)

# Default properties for temporal tracking
SINCE_DATE = "since_date"
UNTIL_DATE = "until_date"


class RelationshipError(Exception):
    """Raised when a relationship operation violates schema constraints."""


class RelationshipManager:
    """Validates and manages relationships through a GraphBuilder.

    Every relationship operation is validated against the schema registry
    before being executed. Temporal relationships support ``since_date``
    and ``until_date`` tracking.
    """

    def __init__(self, builder: GraphBuilder) -> None:
        self._builder = builder

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(  # noqa: PLR0913
        self,
        source_label: str,
        source_key: dict[str, Any],
        rel_type: str,
        target_label: str,
        target_key: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a relationship between two nodes.

        Args:
            source_label: NodeLabel of the source.
            source_key: Property dict to MATCH the source node
                (e.g. ``{symbol: "HPG"}``).
            rel_type: Relationship type string.
            target_label: NodeLabel of the target.
            target_key: Property dict to MATCH the target node.
            properties: Properties to set on the edge.

        Raises:
            RelationshipError: If the relationship is invalid per the schema.

        """
        valid, msg = validate_relationship(rel_type, source_label, target_label)
        if not valid:
            raise RelationshipError(msg)

        props = properties or {}
        allowed = allowed_properties(rel_type)

        # Filter out disallowed properties with a warning
        for key in list(props):
            if key not in allowed:
                logger.warning(
                    "Property '%s' is not allowed on %s edges, skipping",
                    key,
                    rel_type,
                )
                del props[key]

        # Build source/target match clauses
        source_match = self._match_clause(source_label, source_key, "src")
        target_match = self._match_clause(target_label, target_key, "tgt")

        set_clause = self._set_clause(props, "r")

        cypher = f"""
            {source_match}
            {target_match}
            MERGE (src)-[r:{rel_type}]->(tgt)
            {set_clause}
        """
        await self._builder._run(cypher)

    async def update(  # noqa: PLR0913
        self,
        source_label: str,
        source_key: dict[str, Any],
        rel_type: str,
        target_label: str,
        target_key: dict[str, Any],
        properties: dict[str, Any],
    ) -> None:
        """Update properties on an existing relationship."""
        valid, msg = validate_relationship(rel_type, source_label, target_label)
        if not valid:
            raise RelationshipError(msg)

        source_match = self._match_clause(source_label, source_key, "src")
        target_match = self._match_clause(target_label, target_key, "tgt")
        set_clause = self._set_clause(properties, "r")

        cypher = f"""
            {source_match}
            {target_match}
            MATCH (src)-[r:{rel_type}]->(tgt)
            {set_clause}
        """
        await self._builder._run(cypher)

    async def delete(
        self,
        source_label: str,
        source_key: dict[str, Any],
        rel_type: str,
        target_label: str,
        target_key: dict[str, Any],
    ) -> None:
        """Delete a relationship."""
        source_match = self._match_clause(source_label, source_key, "src")
        target_match = self._match_clause(target_label, target_key, "tgt")

        cypher = f"""
            {source_match}
            {target_match}
            MATCH (src)-[r:{rel_type}]->(tgt)
            DELETE r
        """
        await self._builder._run(cypher)

    async def invalidate(  # noqa: PLR0913
        self,
        source_label: str,
        source_key: dict[str, Any],
        rel_type: str,
        target_label: str,
        target_key: dict[str, Any],
        invalid_at: str | None = None,
    ) -> None:
        """Mark a relationship as invalid (set until_date).

        This does not delete the edge — it sets ``until_date`` for
        temporal tracking, allowing historical queries.
        """
        until = invalid_at or datetime.now(UTC).date().isoformat()
        await self.update(
            source_label,
            source_key,
            rel_type,
            target_label,
            target_key,
            {UNTIL_DATE: until},
        )

    async def find(
        self,
        rel_type: str,
        source_label: str | None = None,
        target_label: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Find relationships by type, optionally filtered by labels."""
        pattern = f"(src)-[r:{rel_type}]->(tgt)"
        where_parts: list[str] = []
        params: dict[str, Any] = {}

        if source_label:
            where_parts.append("src:$src_label")
            params["src_label"] = source_label
        if target_label:
            where_parts.append("tgt:$tgt_label")
            params["tgt_label"] = target_label

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        cypher = f"""
            MATCH {pattern}
            {where_clause}
            RETURN src, r, tgt
            LIMIT $limit
        """
        params["limit"] = limit

        rows = await self._builder._run(cypher, params)
        return [
            {
                "source": dict(row[0]),
                "relationship": dict(row[1]),
                "target": dict(row[2]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    async def validate(
        self,
        source_label: str,
        _source_key: dict[str, Any],
        rel_type: str,
        target_label: str,
        _target_key: dict[str, Any],
    ) -> tuple[bool, str]:
        """Check whether a relationship is valid per the schema.

        Returns (is_valid, message).
        """
        return validate_relationship(rel_type, source_label, target_label)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_clause(label: str, keys: dict[str, Any], var: str) -> str:
        """Build a MATCH clause for a node, e.g. ``MATCH (src:Company {symbol: $src_symbol})``."""
        params_str = ", ".join(f"{k}: ${var}_{k}" for k in keys)
        return f"MATCH ({var}:{label} {{{params_str}}})"

    @staticmethod
    def _set_clause(properties: dict[str, Any], var: str) -> str:
        """Build a SET clause with parameterised properties."""
        if not properties:
            return ""
        params_str = ", ".join(f"{var}.{k} = ${var}_{k}" for k in properties)
        return f"SET {params_str}"

    def _build_params(
        self,
        source_key: dict[str, Any],
        target_key: dict[str, Any],
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for k, v in source_key.items():
            params[f"src_{k}"] = v.isoformat() if isinstance(v, (datetime, date)) else v
        for k, v in target_key.items():
            params[f"tgt_{k}"] = v.isoformat() if isinstance(v, (datetime, date)) else v
        for k, v in properties.items():
            params[f"r_{k}"] = v.isoformat() if isinstance(v, (datetime, date)) else v
        return params
