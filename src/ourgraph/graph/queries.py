"""Graph query helpers for stock analysis.

All queries are read-only (ro_query) and return raw result sets.
Callers can convert to polars DataFrames as needed.

These are domain-specific queries — not generic graph traversal.
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Self

import polars as pl

from ourgraph.graph.schema import NodeLabel, Prop, RelType

if TYPE_CHECKING:
    from falkordb.asyncio import FalkorDB

    from ourgraph.config import FalkorDBSettings

logger = logging.getLogger(__name__)


class GraphQueries:
    """Read-only query interface for the stock knowledge graph.

    Usage::

        async with GraphQueries.from_settings(settings) as q:
            df = await q.get_sector_peers("VCB")
    """

    def __init__(self, client: FalkorDB, graph_name: str) -> None:
        self._client = client
        self._graph_name = graph_name

    @classmethod
    def from_settings(cls, settings: FalkorDBSettings) -> GraphQueries:
        from ourgraph.db.falkordb import build_falkordb_client

        client = build_falkordb_client(settings)
        return cls(client=client, graph_name=settings.graph_name)

    async def _ro(self, query: str, params: dict | None = None) -> list:
        g = self._client.select_graph(self._graph_name)
        result = await g.ro_query(query, params or {})
        return result.result_set

    # ------------------------------------------------------------------
    # Peer / competitor analysis
    # ------------------------------------------------------------------

    async def get_sector_peers(self, symbol: str, limit: int = 20) -> pl.DataFrame:
        """Return companies in the same industry as `symbol`."""
        rows = await self._ro(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
                  <-[:{RelType.BELONGS_TO_INDUSTRY}]-(peer:{NodeLabel.COMPANY})
            WHERE peer.{Prop.SYMBOL} <> $symbol
            RETURN peer.{Prop.SYMBOL}   AS symbol,
                   peer.{Prop.NAME}     AS name,
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
        """Return all subsidiaries (direct) of a company."""
        rows = await self._ro(
            f"""
            MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->
                  (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN child.{Prop.SYMBOL}    AS sub_symbol,
                   child.{Prop.NAME}      AS sub_name,
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
        """Return major shareholders of a company."""
        rows = await self._ro(
            f"""
            MATCH (holder:{NodeLabel.COMPANY})-[r:{RelType.HOLDS_STAKE_IN}]->
                  (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN holder.{Prop.NAME}     AS holder_name,
                   holder.{Prop.SYMBOL}   AS holder_symbol,
                   r.{Prop.STAKE_PERCENT} AS stake_pct
            ORDER BY stake_pct DESC
            """,
            {"symbol": symbol},
        )
        return pl.DataFrame(
            {
                "holder_name": [r[0] for r in rows],
                "holder_symbol": [r[1] for r in rows],
                "stake_pct": [r[2] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    async def get_price_history(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pl.DataFrame:
        """Return OHLCV price history for a symbol, optionally date-filtered."""
        where = ""
        params: dict = {"symbol": symbol}
        if start:
            where += f" AND p.{Prop.DATE} >= $start"
            params["start"] = start
        if end:
            where += f" AND p.{Prop.DATE} <= $end"
            params["end"] = end

        rows = await self._ro(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                -[:{RelType.HAS_STOCK_PRICE}]->(p:{NodeLabel.STOCK_PRICE})
            WHERE 1=1{where}
            RETURN p.{Prop.DATE}   AS date,
                   p.{Prop.OPEN}   AS open,
                   p.{Prop.HIGH}   AS high,
                   p.{Prop.LOW}    AS low,
                   p.{Prop.CLOSE}  AS close,
                   p.{Prop.VOLUME} AS volume
            ORDER BY date ASC
            """,
            params,
        )
        return pl.DataFrame(
            {
                "date": [r[0] for r in rows],
                "open": [r[1] for r in rows],
                "high": [r[2] for r in rows],
                "low": [r[3] for r in rows],
                "close": [r[4] for r in rows],
                "volume": [r[5] for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # Financial indicators
    # ------------------------------------------------------------------

    async def get_latest_indicators(self, symbol: str) -> pl.DataFrame:
        """Return the most recent financial indicator values for a company."""
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

    async def get_graph_stats(self) -> dict[str, int]:
        """Return high-level graph counts used to validate ingestion progress."""
        company_count_rows = await self._ro(
            f"MATCH (c:{NodeLabel.COMPANY}) RETURN COUNT(c)",
        )
        distinct_symbols_rows = await self._ro(
            f"MATCH (c:{NodeLabel.COMPANY})-[:{RelType.HAS_STOCK_PRICE}]->(:{NodeLabel.STOCK_PRICE}) RETURN COUNT(DISTINCT c.{Prop.SYMBOL})",
        )
        price_count_rows = await self._ro(
            f"MATCH (p:{NodeLabel.STOCK_PRICE}) RETURN COUNT(p)",
        )
        distinct_price_symbol_rows = await self._ro(
            f"MATCH (p:{NodeLabel.STOCK_PRICE}) RETURN COUNT(DISTINCT p.{Prop.SYMBOL})",
        )
        statement_count_rows = await self._ro(
            f"MATCH (s:{NodeLabel.FINANCIAL_STATEMENT}) RETURN COUNT(s)",
        )
        indicator_count_rows = await self._ro(
            f"MATCH (i:{NodeLabel.INDICATOR}) RETURN COUNT(i)",
        )

        return {
            "companies": int(company_count_rows[0][0]) if company_count_rows else 0,
            "distinct_symbols": int(distinct_symbols_rows[0][0])
            if distinct_symbols_rows
            else 0,
            "stock_prices": int(price_count_rows[0][0]) if price_count_rows else 0,
            "stock_price_symbols": int(distinct_price_symbol_rows[0][0])
            if distinct_price_symbol_rows
            else 0,
            "financial_statements": int(statement_count_rows[0][0])
            if statement_count_rows
            else 0,
            "financial_indicators": int(indicator_count_rows[0][0])
            if indicator_count_rows
            else 0,
        }

    # ------------------------------------------------------------------
    # Cross-shareholding detection (2-hop ownership)
    # ------------------------------------------------------------------

    async def find_cross_shareholding(self, limit: int = 50) -> pl.DataFrame:
        """Find companies that mutually hold stakes in each other.

        Returns pairs (A → B) where B also holds a stake in A.
        """
        rows = await self._ro(
            f"""
            MATCH (a:{NodeLabel.COMPANY})-[r1:{RelType.HOLDS_STAKE_IN}]->(b:{NodeLabel.COMPANY})
                  -[r2:{RelType.HOLDS_STAKE_IN}]->(a)
            RETURN a.{Prop.SYMBOL} AS symbol_a,
                   b.{Prop.SYMBOL} AS symbol_b,
                   r1.{Prop.STAKE_PERCENT} AS a_holds_b_pct,
                   r2.{Prop.STAKE_PERCENT} AS b_holds_a_pct
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
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        """Return this instance for async context-manager usage."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close the underlying client when exiting async context manager."""
        await self.close()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            close = getattr(self._client, "close", None)
            if callable(close):
                maybe_awaitable = close()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
