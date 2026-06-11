"""Graph query helpers for stock analysis.

All queries are read-only (ro_query) and return raw result sets.
Callers can convert to polars DataFrames as needed.
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Any, Self

import polars as pl

from ourgraph.constants import (
    GRAPH_QUERY_COMPANY_NETWORK_LIMIT,
    GRAPH_QUERY_CROSS_SHAREHOLDING_LIMIT,
    GRAPH_QUERY_SECTOR_PEERS_LIMIT,
    GRAPH_QUERY_SHARED_INSIDERS_LIMIT,
)
from ourgraph.graph.schema import NodeLabel, Prop, RelType

if TYPE_CHECKING:
    from falkordb.asyncio import FalkorDB

    from ourgraph.config import FalkorDBSettings

logger = logging.getLogger(__name__)


class GraphQueries:
    """Read-only query interface for the stock knowledge graph."""

    def __init__(self, client: FalkorDB, graph_name: str) -> None:
        self._client = client
        self._graph_name = graph_name

    @classmethod
    def from_settings(cls, settings: FalkorDBSettings) -> GraphQueries:
        from ourgraph.db.falkordb import build_falkordb_client

        client = build_falkordb_client(settings)
        return cls(client=client, graph_name=settings.graph_name)

    async def query_raw(self, query: str, params: dict | None = None) -> list:
        """Execute a raw read-only Cypher query and return the result set."""
        g = self._client.select_graph(self._graph_name)
        result = await g.ro_query(query, params or {})
        return result.result_set

    async def _ro(self, query: str, params: dict | None = None) -> list:
        return await self.query_raw(query, params)

    # ------------------------------------------------------------------
    # Company network (ownership + competition only — no price/fin noise)
    # ------------------------------------------------------------------

    async def get_company_network(
        self,
        symbol: str | None = None,
        limit: int = GRAPH_QUERY_COMPANY_NETWORK_LIMIT,
    ) -> pl.DataFrame:
        """Return inter-company edges: HOLDS_STAKE_IN, SUBSIDIARY_OF, COMPETES_WITH.

        Use this as the base for graph visualisation — it only includes
        Company↔Company relationships, no price/indicator/date noise.
        """
        where = (
            f"WHERE a.{Prop.SYMBOL} = $symbol OR b.{Prop.SYMBOL} = $symbol"
            if symbol
            else ""
        )
        params: dict = {"limit": limit}
        if symbol:
            params["symbol"] = symbol

        rows = await self._ro(
            f"""
            MATCH (a:{NodeLabel.COMPANY})-[r:{RelType.HOLDS_STAKE_IN}|{RelType.SUBSIDIARY_OF}|{RelType.COMPETES_WITH}]->(b:{NodeLabel.COMPANY})
            {where}
            RETURN a.{Prop.SYMBOL}             AS source,
                   a.{Prop.NAME}               AS source_name,
                   type(r)                     AS rel_type,
                   b.{Prop.SYMBOL}             AS target,
                   b.{Prop.NAME}               AS target_name,
                   r.{Prop.STAKE_PERCENT}      AS stake_pct,
                   r.{Prop.OWNERSHIP_PERCENT}  AS ownership_pct
            ORDER BY type(r), source, target
            LIMIT $limit
            """,
            params,
        )
        return pl.DataFrame(
            {
                "source": [r[0] for r in rows],
                "source_name": [r[1] for r in rows],
                "rel_type": [r[2] for r in rows],
                "target": [r[3] for r in rows],
                "target_name": [r[4] for r in rows],
                "stake_pct": [r[5] for r in rows],
                "ownership_pct": [r[6] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Person-centric queries (officers + individual shareholders)
    # ------------------------------------------------------------------

    async def get_person_roles(self, person_name: str) -> pl.DataFrame:
        """Return all roles a person holds: officer positions and shareholdings.

        This reveals dual roles — e.g. someone who is both a board member
        and a significant shareholder across multiple companies.
        """
        rows = await self._ro(
            f"""
            MATCH (p:{NodeLabel.PERSON} {{{Prop.PERSON_NAME}: $name}})
            OPTIONAL MATCH (p)-[off:{RelType.IS_OFFICER}]->(c1:{NodeLabel.COMPANY})
            OPTIONAL MATCH (p)-[hold:{RelType.HOLDS_STAKE_IN}]->(c2:{NodeLabel.COMPANY})
            RETURN p.{Prop.PERSON_NAME}     AS person,
                   c1.{Prop.SYMBOL}         AS officer_at,
                   off.{Prop.POSITION}      AS position,
                   c2.{Prop.SYMBOL}         AS shareholder_at,
                   hold.{Prop.STAKE_PERCENT} AS stake_pct
            """,
            {"name": person_name},
        )
        return pl.DataFrame(
            {
                "person": [r[0] for r in rows],
                "officer_at": [r[1] for r in rows],
                "position": [r[2] for r in rows],
                "shareholder_at": [r[3] for r in rows],
                "stake_pct": [r[4] for r in rows],
            },
        )

    async def get_company_insiders(self, symbol: str) -> pl.DataFrame:
        """Return all people connected to a company: officers and individual shareholders.

        Dual-role people (officer + shareholder) appear once with both columns populated.
        """
        rows = await self._ro(
            f"""
            // People who are officers (may or may not also be shareholders)
            MATCH (p:{NodeLabel.PERSON})-[off:{RelType.IS_OFFICER}]->(c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            OPTIONAL MATCH (p)-[hold:{RelType.HOLDS_STAKE_IN}]->(c)
            RETURN p.{Prop.PERSON_NAME}      AS person_name,
                   off.{Prop.POSITION}       AS officer_position,
                   off.{Prop.OWN_PERCENT}    AS officer_own_pct,
                   hold.{Prop.STAKE_PERCENT} AS stake_pct

            UNION ALL

            // People who are shareholders but NOT officers
            MATCH (p:{NodeLabel.PERSON})-[hold:{RelType.HOLDS_STAKE_IN}]->(c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            WHERE NOT (p)-[:{RelType.IS_OFFICER}]->(c)
            RETURN p.{Prop.PERSON_NAME}      AS person_name,
                   null                       AS officer_position,
                   null                       AS officer_own_pct,
                   hold.{Prop.STAKE_PERCENT} AS stake_pct

            ORDER BY stake_pct DESC
            """,
            {"symbol": symbol},
        )
        return pl.DataFrame(
            {
                "person_name": [r[0] for r in rows],
                "officer_position": [r[1] for r in rows],
                "officer_own_pct": [r[2] for r in rows],
                "stake_pct": [r[3] for r in rows],
            },
        )

    async def find_shared_insiders(
        self,
        limit: int = GRAPH_QUERY_SHARED_INSIDERS_LIMIT,
    ) -> pl.DataFrame:
        """Find people who are insiders (officer or shareholder) at multiple companies.

        Useful for detecting hidden influence networks — a person sitting on
        boards of competing companies, or holding stakes across a sector.
        """
        rows = await self._ro(
            f"""
            MATCH (p:{NodeLabel.PERSON})-[r:{RelType.IS_OFFICER}|{RelType.HOLDS_STAKE_IN}]->(c:{NodeLabel.COMPANY})
            WITH p.{Prop.PERSON_NAME} AS person, collect(DISTINCT c.{Prop.SYMBOL}) AS companies, COUNT(DISTINCT c) AS n
            WHERE n > 1
            RETURN person, companies, n
            ORDER BY n DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )
        return pl.DataFrame(
            {
                "person": [r[0] for r in rows],
                "companies": [r[1] for r in rows],
                "n_companies": [r[2] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Peer / competitor analysis
    # ------------------------------------------------------------------

    async def get_sector_peers(
        self,
        symbol: str,
        limit: int = GRAPH_QUERY_SECTOR_PEERS_LIMIT,
    ) -> pl.DataFrame:
        rows = await self._ro(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
                  <-[:{RelType.BELONGS_TO_INDUSTRY}]-(peer:{NodeLabel.COMPANY})
            WHERE peer.{Prop.SYMBOL} <> $symbol
            RETURN peer.{Prop.SYMBOL}     AS symbol,
                   peer.{Prop.NAME}       AS name,
                   peer.{Prop.MARKET_CAP} AS market_cap
            ORDER BY market_cap DESC
            LIMIT $limit
            """,
            {"symbol": symbol, "limit": limit},
        )
        return pl.DataFrame(
            {
                "symbol": [r[0] for r in rows],
                "name": [r[1] for r in rows],
                "market_cap": [r[2] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Ownership graph
    # ------------------------------------------------------------------

    async def get_subsidiaries(self, symbol: str) -> pl.DataFrame:
        rows = await self._ro(
            f"""
            MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->
                  (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN child.{Prop.SYMBOL}        AS sub_symbol,
                   child.{Prop.NAME}          AS sub_name,
                   r.{Prop.OWNERSHIP_PERCENT} AS ownership_pct,
                   r.{Prop.RELATION_TYPE}     AS rel_type
            """,
            {"symbol": symbol},
        )
        return pl.DataFrame(
            {
                "sub_symbol": [r[0] for r in rows],
                "sub_name": [r[1] for r in rows],
                "ownership_pct": [r[2] for r in rows],
                "rel_type": [r[3] for r in rows],
            },
        )

    async def get_shareholders(self, symbol: str) -> pl.DataFrame:
        """Return major shareholders — both corporate and individual."""
        rows = await self._ro(
            f"""
            MATCH (holder)-[r:{RelType.HOLDS_STAKE_IN}]->
                  (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN coalesce(holder.{Prop.NAME}, holder.{Prop.PERSON_NAME}) AS holder_name,
                   labels(holder)[0]       AS holder_type,
                   coalesce(holder.{Prop.SYMBOL}, '')                      AS holder_symbol,
                   r.{Prop.STAKE_PERCENT}  AS stake_pct
            ORDER BY stake_pct DESC
            """,
            {"symbol": symbol},
        )
        return pl.DataFrame(
            {
                "holder_name": [r[0] for r in rows],
                "holder_type": [r[1] for r in rows],
                "holder_symbol": [r[2] for r in rows],
                "stake_pct": [r[3] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Financial indicators
    # ------------------------------------------------------------------

    async def get_latest_indicators(self, symbol: str) -> pl.DataFrame:
        rows = await self._ro(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.HAS_INDICATOR}]->(i:{NodeLabel.INDICATOR})
            RETURN i.{Prop.PBR}     AS pbr,
                   i.{Prop.PER}     AS per,
                   i.{Prop.EPS}     AS eps,
                   i.{Prop.YEAR}    AS year,
                   i.{Prop.QUARTER} AS quarter,
                   i.{Prop.PAYLOAD} AS payload
            ORDER BY year DESC, quarter DESC
            """,
            {"symbol": symbol},
        )
        return pl.DataFrame(
            {
                "pbr": [r[0] for r in rows],
                "per": [r[1] for r in rows],
                "eps": [r[2] for r in rows],
                "year": [r[3] for r in rows],
                "quarter": [r[4] for r in rows],
                "payload": [r[5] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Cross-shareholding detection
    # ------------------------------------------------------------------

    async def find_cross_shareholding(
        self,
        limit: int = GRAPH_QUERY_CROSS_SHAREHOLDING_LIMIT,
    ) -> pl.DataFrame:
        rows = await self._ro(
            f"""
            MATCH (a:{NodeLabel.COMPANY})-[r1:{RelType.HOLDS_STAKE_IN}]->(b:{NodeLabel.COMPANY})
                  -[r2:{RelType.HOLDS_STAKE_IN}]->(a)
            RETURN a.{Prop.SYMBOL}          AS symbol_a,
                   b.{Prop.SYMBOL}          AS symbol_b,
                   r1.{Prop.STAKE_PERCENT}  AS a_holds_b_pct,
                   r2.{Prop.STAKE_PERCENT}  AS b_holds_a_pct
            LIMIT $limit
            """,
            {"limit": limit},
        )
        return pl.DataFrame(
            {
                "symbol_a": [r[0] for r in rows],
                "symbol_b": [r[1] for r in rows],
                "a_holds_b_pct": [r[2] for r in rows],
                "b_holds_a_pct": [r[3] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Macro indicator queries
    # ------------------------------------------------------------------

    async def get_macro_indicators(
        self,
        country: str | None = None,
        category: str | None = None,
        name: str | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """Query macro indicators with optional filters."""
        where_clauses = []
        params: dict[str, Any] = {"limit": limit}

        if country:
            where_clauses.append(f"m.{Prop.COUNTRY} = $country")
            params["country"] = country
        if category:
            where_clauses.append(f"m.{Prop.CATEGORY} = $category")
            params["category"] = category
        if name:
            where_clauses.append(f"m.{Prop.NAME} CONTAINS $name")
            params["name"] = name

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        rows = await self._ro(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR})
            {where}
            RETURN m.{Prop.NAME}      AS name,
                   m.{Prop.VALUE}     AS value,
                   m.{Prop.UNIT}      AS unit,
                   m.{Prop.DATE}      AS date,
                   m.{Prop.COUNTRY}   AS country,
                   m.{Prop.CATEGORY}  AS category,
                   m.{Prop.FREQUENCY} AS frequency,
                   m.{Prop.SOURCE}    AS source
            ORDER BY m.{Prop.DATE} DESC
            LIMIT $limit
            """,
            params,
        )
        return pl.DataFrame(
            {
                "name": [r[0] for r in rows],
                "value": [r[1] for r in rows],
                "unit": [r[2] for r in rows],
                "date": [r[3] for r in rows],
                "country": [r[4] for r in rows],
                "category": [r[5] for r in rows],
                "frequency": [r[6] for r in rows],
                "source": [r[7] for r in rows],
            },
        )

    async def get_macro_by_country(self, country: str) -> pl.DataFrame:
        """Get all macro indicators for a specific country."""
        return await self.get_macro_indicators(country=country)

    async def get_macro_impact_on_sector(self, sector_name: str) -> pl.DataFrame:
        """Get macro indicators that affect a sector."""
        rows = await self._ro(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR})-[r:{RelType.AFFECTS_SECTOR}]->(s:{NodeLabel.SECTOR})
            WHERE s.{Prop.NAME} = $sector_name
            RETURN m.{Prop.NAME}      AS indicator_name,
                   m.{Prop.VALUE}     AS value,
                   m.{Prop.UNIT}      AS unit,
                   m.{Prop.DATE}      AS date,
                   r.{Prop.REASON}     AS reason
            ORDER BY m.{Prop.DATE} DESC
            """,
            {"sector_name": sector_name},
        )
        return pl.DataFrame(
            {
                "indicator_name": [r[0] for r in rows],
                "value": [r[1] for r in rows],
                "unit": [r[2] for r in rows],
                "date": [r[3] for r in rows],
                "reason": [r[4] for r in rows],
            },
        )

    async def get_macro_stats(self) -> dict[str, int | dict]:
        """Return macro indicator counts by country and category."""
        total_rows = await self._ro(
            f"MATCH (m:{NodeLabel.MACRO_INDICATOR}) RETURN COUNT(m)",
        )
        by_country_rows = await self._ro(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR})
            RETURN m.{Prop.COUNTRY} AS country, COUNT(m) AS cnt
            ORDER BY cnt DESC
            """,
        )
        by_category_rows = await self._ro(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR})
            RETURN m.{Prop.CATEGORY} AS category, COUNT(m) AS cnt
            ORDER BY cnt DESC
            """,
        )
        return {
            "total": int(total_rows[0][0]) if total_rows else 0,
            "by_country": {r[0]: int(r[1]) for r in by_country_rows},
            "by_category": {r[0]: int(r[1]) for r in by_category_rows},
        }

    # ------------------------------------------------------------------
    # Graph stats
    # ------------------------------------------------------------------

    async def get_graph_stats(self) -> dict[str, int]:
        company_count_rows = await self._ro(
            f"MATCH (c:{NodeLabel.COMPANY}) RETURN COUNT(c)",
        )
        person_count_rows = await self._ro(
            f"MATCH (p:{NodeLabel.PERSON}) RETURN COUNT(p)",
        )
        statement_count_rows = await self._ro(
            f"MATCH (s:{NodeLabel.FINANCIAL_STATEMENT}) RETURN COUNT(s)",
        )
        indicator_count_rows = await self._ro(
            f"MATCH (i:{NodeLabel.INDICATOR}) RETURN COUNT(i)",
        )
        macro_count_rows = await self._ro(
            f"MATCH (m:{NodeLabel.MACRO_INDICATOR}) RETURN COUNT(m)",
        )
        country_count_rows = await self._ro(
            f"MATCH (c:{NodeLabel.COUNTRY}) RETURN COUNT(c)",
        )

        return {
            "companies": int(company_count_rows[0][0]) if company_count_rows else 0,
            "persons": int(person_count_rows[0][0]) if person_count_rows else 0,
            "financial_statements": int(statement_count_rows[0][0])
            if statement_count_rows
            else 0,
            "financial_indicators": int(indicator_count_rows[0][0])
            if indicator_count_rows
            else 0,
            "macro_indicators": int(macro_count_rows[0][0]) if macro_count_rows else 0,
            "countries": int(country_count_rows[0][0]) if country_count_rows else 0,
        }

    # ------------------------------------------------------------------
    # Graph export (for frontend visualization)
    # ------------------------------------------------------------------

    async def export_graph_json(
        self,
        symbol: str | None = None,
        *,
        max_edges: int = 200,
        include_macro: bool = False,
    ) -> dict:
        """Export the full graph as nodes+edges JSON for frontend visualization.

        Returns a dict with 'nodes' and 'edges' lists, each node/edge
        carrying all its properties for rich display.

        If symbol is provided, returns only the ego-network around that
        symbol (1-hop neighborhood).
        """
        if symbol:
            return await self._export_egonet_json(symbol, max_edges=max_edges)

        exclude_labels = [NodeLabel.DATE, NodeLabel.QUARTER, NodeLabel.YEAR]
        if not include_macro:
            exclude_labels.append(NodeLabel.MACRO_INDICATOR)

        # Exclude Person→Company role edges from the overview graph.
        # Role details are visible in the node detail panel; including
        # officer/board/executive edges crowds out the more interesting
        # inter-company relationships (LENDS_TO, HOLDS_STAKE_IN, etc.)
        # and sector/industry connections (BELONGS_TO).
        exclude_rels = ["IS_OFFICER", "IS_BOARD_MEMBER", "IS_EXECUTIVE", "IS_FOUNDER"]
        rel_exclude = " AND ".join(f"type(r) <> '{r}'" for r in exclude_rels)

        edge_exclude = " AND ".join(
            f"NOT a:{label} AND NOT b:{label}" for label in exclude_labels
        )

        # First pass: always include BELONGS_TO edges (needed for sector
        # grouping in the frontend concentric layout), then fill remaining
        # edge budget with other relationship types.
        belongs_query = f"""
            MATCH (a)-[r:BELONGS_TO|BELONGS_TO_INDUSTRY]->(b)
            WHERE {edge_exclude}
            RETURN labels(a) AS source_labels, properties(a) AS source_props,
                   type(r) AS relationship, properties(r) AS edge_props,
                   labels(b) AS target_labels, properties(b) AS target_props
            LIMIT 200
        """

        remaining = max_edges - 200  # reserve 200 slots for BELONGS_TO
        other_query = f"""
            MATCH (a)-[r]->(b)
            WHERE {edge_exclude}
              AND {rel_exclude}
              AND type(r) <> 'BELONGS_TO'
              AND type(r) <> 'BELONGS_TO_INDUSTRY'
            RETURN labels(a) AS source_labels, properties(a) AS source_props,
                   type(r) AS relationship, properties(r) AS edge_props,
                   labels(b) AS target_labels, properties(b) AS target_props
            LIMIT $remaining
        """

        belongs_rows = await self._ro(belongs_query)
        other_rows = (
            await self._ro(other_query, {"remaining": max(remaining, 0)})
            if remaining > 0
            else []
        )

        edge_rows = list(belongs_rows) + list(other_rows)

        seen_nodes: dict[str, dict] = {}
        edges: list[dict] = []
        for row in edge_rows:
            src_labels, src_props, rel_type, edge_props, tgt_labels, tgt_props = row
            src_id = self._node_key(src_labels, src_props)
            tgt_id = self._node_key(tgt_labels, tgt_props)
            if src_id not in seen_nodes:
                seen_nodes[src_id] = {
                    "id": src_id,
                    "labels": src_labels,
                    "properties": src_props,
                }
            if tgt_id not in seen_nodes:
                seen_nodes[tgt_id] = {
                    "id": tgt_id,
                    "labels": tgt_labels,
                    "properties": tgt_props,
                }
            edges.append(
                {
                    "source": src_id,
                    "target": tgt_id,
                    "relationship": rel_type,
                    "properties": edge_props,
                },
            )

        return {"nodes": list(seen_nodes.values()), "edges": edges}

    async def _export_egonet_json(
        self,
        symbol: str,
        *,
        max_edges: int = 200,
    ) -> dict:
        """Export the ego-network around a given symbol."""
        nodes_query = f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})-[r]-(n)
            WHERE NOT n:Date AND NOT n:Quarter AND NOT n:Year
            RETURN labels(c) AS labels, properties(c) AS props
            UNION
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})-[r]-(n)
            WHERE NOT n:Date AND NOT n:Quarter AND NOT n:Year
            RETURN labels(n) AS labels, properties(n) AS props
            LIMIT 200
        """
        edges_query = f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})-[r]-(n)
            WHERE NOT n:Date AND NOT n:Quarter AND NOT n:Year
            RETURN labels(c) AS source_labels, properties(c) AS source_props,
                   type(r) AS relationship, properties(r) AS edge_props,
                   labels(n) AS target_labels, properties(n) AS target_props
            LIMIT $max_edges
        """

        node_rows = await self._ro(nodes_query, {"symbol": symbol})
        edge_rows = await self._ro(
            edges_query, {"symbol": symbol, "max_edges": max_edges},
        )

        seen_nodes: dict[str, dict] = {}
        for labels, props in node_rows:
            node_id = self._node_key(labels, props)
            seen_nodes[node_id] = {
                "id": node_id,
                "labels": labels,
                "properties": props,
            }

        edges: list[dict] = []
        for row in edge_rows:
            src_labels, src_props, rel_type, edge_props, tgt_labels, tgt_props = row
            src_id = self._node_key(src_labels, src_props)
            tgt_id = self._node_key(tgt_labels, tgt_props)
            if src_id not in seen_nodes:
                seen_nodes[src_id] = {
                    "id": src_id,
                    "labels": src_labels,
                    "properties": src_props,
                }
            if tgt_id not in seen_nodes:
                seen_nodes[tgt_id] = {
                    "id": tgt_id,
                    "labels": tgt_labels,
                    "properties": tgt_props,
                }
            edges.append(
                {
                    "source": src_id,
                    "target": tgt_id,
                    "relationship": rel_type,
                    "properties": edge_props,
                },
            )

        return {"nodes": list(seen_nodes.values()), "edges": edges}

    @staticmethod
    def _node_key(labels: list[str], props: dict) -> str:
        """Build a stable node ID from labels and key properties."""
        label = labels[0] if labels else "Unknown"
        if label == "Company":
            return f"Company:{props.get('symbol', '')}"
        if label == "Person":
            return f"Person:{props.get('person_name', '')}"
        if label == "Sector":
            return f"Sector:{props.get('name', '')}"
        if label == "Industry":
            return f"Industry:{props.get('name', '')}"
        if label == "MacroIndicator":
            return f"Macro:{props.get('name', '')}:{props.get('date', '')}"
        if label == "Country":
            return f"Country:{props.get('code', '')}"
        if label == "Indicator":
            return f"Indicator:{props.get('symbol', '')}:{props.get('year', '')}:{props.get('quarter', '')}"
        if label == "FinancialStatement":
            return f"FS:{props.get('symbol', '')}:{props.get('statement_type', '')}:{props.get('year', '')}:{props.get('quarter', '')}"
        return f"{label}:{hash(frozenset(props.items()))}"

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit async context manager."""
        await self.close()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            close = getattr(self._client, "close", None)
            if callable(close):
                maybe_awaitable = close()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
