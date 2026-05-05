"""
Core knowledge graph builder.

Uses the FalkorDB async Python client directly via Cypher queries.
All upserts use MERGE to make operations idempotent — safe to re-run daily.

Design principles:
  - One method per node/edge type → easy to extend or override.
  - All data arrives as polars DataFrames → converted to dicts before Cypher.
  - Parameters are always passed via the `params` dict → no SQL injection.
  - No business logic here — only graph write operations.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import date

import polars as pl
from falkordb.asyncio import FalkorDB

from ourgraph.config import FalkorDBSettings
from ourgraph.graph.schema import NodeLabel, Prop, RelType

logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    Async graph builder backed by FalkorDB.

    Usage::

        async with GraphBuilder.from_settings(settings) as builder:
            await builder.ensure_indices()
            await builder.upsert_company(df_companies)
    """

    def __init__(self, client: FalkorDB, graph_name: str) -> None:
        self._client = client
        self._graph_name = graph_name

    @classmethod
    def from_settings(cls, settings: FalkorDBSettings) -> GraphBuilder:
        """Convenience constructor that wires settings → client."""
        from ourgraph.db.falkordb import build_falkordb_client

        client = build_falkordb_client(settings)
        return cls(client=client, graph_name=settings.graph_name)

    async def _graph(self):
        return self._client.select_graph(self._graph_name)

    async def _run(self, query: str, params: dict | None = None) -> list:
        g = await self._graph()
        result = await g.query(query, params or {})
        return result.result_set

    # ------------------------------------------------------------------
    # Index setup (run once on first install)
    # ------------------------------------------------------------------

    async def ensure_indices(self) -> None:
        """Create indices required for fast MERGE and lookups."""
        indices = [
            f"CREATE INDEX ON :{NodeLabel.COMPANY}({Prop.SYMBOL})",
            f"CREATE INDEX ON :{NodeLabel.SECTOR}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.INDUSTRY}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.STOCK_PRICE}({Prop.SYMBOL}, {Prop.DATE})",
            f"CREATE INDEX ON :{NodeLabel.FINANCIAL_STATEMENT}({Prop.SYMBOL}, {Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.FINANCIAL_INDICATOR}({Prop.SYMBOL})",
            f"CREATE INDEX ON :{NodeLabel.OFFICER}({Prop.OFFICER_NAME})",
        ]
        for idx in indices:
            try:
                await self._run(idx)
                logger.debug("Index created: %s", idx)
            except Exception as exc:
                exc_str = str(exc).lower()
                if "already exists" in exc_str or "already indexed" in exc_str:
                    logger.debug("Index already exists (ok): %s", idx)
                else:
                    logger.warning("Index creation warning: %s — %s", idx, exc)

    # ------------------------------------------------------------------
    # Company nodes
    # ------------------------------------------------------------------

    async def upsert_companies(self, df: pl.DataFrame) -> None:
        """
        Upsert Company nodes from a DataFrame with columns:
        symbol, short_name, exchange, industry, market_cap,
        no_employees, established_year, website,
        outstanding_share, foreign_percent
        """
        records = df.to_dicts()
        for row in records:
            params = {
                "symbol": row.get(Prop.SYMBOL, ""),
                "name": row.get("short_name") or row.get(Prop.SYMBOL, ""),
                "exchange": row.get(Prop.EXCHANGE) or "",
                "market_cap": row.get(Prop.MARKET_CAP) or 0,
                "no_employees": row.get(Prop.NO_EMPLOYEES) or 0,
                "established_year": str(row.get(Prop.ESTABLISHED_YEAR) or ""),
                "website": row.get(Prop.WEBSITE) or "",
                "outstanding_share": float(row.get(Prop.OUTSTANDING_SHARE) or 0),
                "foreign_percent": float(row.get(Prop.FOREIGN_PERCENT) or 0),
            }
            await self._run(
                f"""
                MERGE (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                SET c.{Prop.NAME} = $name,
                    c.{Prop.EXCHANGE} = $exchange,
                    c.{Prop.MARKET_CAP} = $market_cap,
                    c.{Prop.NO_EMPLOYEES} = $no_employees,
                    c.{Prop.ESTABLISHED_YEAR} = $established_year,
                    c.{Prop.WEBSITE} = $website,
                    c.{Prop.OUTSTANDING_SHARE} = $outstanding_share,
                    c.{Prop.FOREIGN_PERCENT} = $foreign_percent
                """,
                params,
            )
        logger.info("Upserted %d Company nodes", len(records))

    # ------------------------------------------------------------------
    # Sector / Industry hierarchy
    # ------------------------------------------------------------------

    async def upsert_sector_industry(self, df: pl.DataFrame) -> None:
        """
        Upsert Sector and Industry nodes and link companies.

        Expected columns: symbol, industry (ICB name).
        Sector is derived from the industry string (top-level ICB name).
        """
        for row in df.to_dicts():
            symbol = row.get(Prop.SYMBOL, "")
            industry = row.get("industry") or ""
            if not industry:
                continue

            params = {"symbol": symbol, "industry": industry}
            await self._run(
                f"""
                MERGE (ind:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry}})
                WITH ind
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (c)-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind)
                """,
                params,
            )
        logger.info("Upserted industry links for %d symbols", len(df))

    # ------------------------------------------------------------------
    # Stock price nodes
    # ------------------------------------------------------------------

    async def upsert_stock_prices(self, df: pl.DataFrame) -> None:
        """
        Upsert StockPrice nodes and HAS_PRICE edges.

        Expected columns: symbol, date, open, high, low, close, volume
        """
        records = df.to_dicts()
        for row in records:
            date_val = row.get(Prop.DATE)
            if isinstance(date_val, date):
                date_str = date_val.isoformat()
            else:
                date_str = str(date_val)

            params = {
                "symbol": row[Prop.SYMBOL],
                "date": date_str,
                "open": float(row.get(Prop.OPEN) or 0),
                "high": float(row.get(Prop.HIGH) or 0),
                "low": float(row.get(Prop.LOW) or 0),
                "close": float(row.get(Prop.CLOSE) or 0),
                "volume": int(row.get(Prop.VOLUME) or 0),
            }
            await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (p:{NodeLabel.STOCK_PRICE} {{{Prop.SYMBOL}: $symbol, {Prop.DATE}: $date}})
                SET p.{Prop.OPEN}   = $open,
                    p.{Prop.HIGH}   = $high,
                    p.{Prop.LOW}    = $low,
                    p.{Prop.CLOSE}  = $close,
                    p.{Prop.VOLUME} = $volume
                MERGE (c)-[:{RelType.HAS_PRICE}]->(p)
                """,
                params,
            )
        symbols = sorted(
            {
                str(r.get(Prop.SYMBOL, ""))
                for r in records
                if str(r.get(Prop.SYMBOL, "")).strip()
            }
        )
        if len(symbols) == 1:
            logger.info(
                "Upserted %d StockPrice nodes for %s",
                len(records),
                symbols[0],
            )
        else:
            logger.info(
                "Upserted %d StockPrice nodes across %d symbols",
                len(records),
                len(symbols),
            )

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    async def upsert_financial_statement(
        self,
        df: pl.DataFrame,
        symbol: str,
        statement_type: str,
        period: str,
    ) -> None:
        """
        Upsert FinancialStatement nodes (balance_sheet | income_statement | cash_flow).

        The full metric dict is serialised to JSON and stored in the `payload`
        property so no schema migration is needed when vnstock adds new metrics.

        Expected DataFrame format from vnstock Finance.*():
          - columns: year, quarter (or year for annual), plus metric columns
        """
        if df is None or df.is_empty():
            return

        # vnstock Finance returns rows per period — iterate each row
        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0))
            quarter = int(row.get(Prop.QUARTER, 0)) if period == "quarter" else 0

            # Exclude year/quarter from the payload
            payload_dict = {
                k: (v.isoformat() if isinstance(v, date) else v)
                for k, v in row.items()
                if k not in (Prop.YEAR, Prop.QUARTER, Prop.SYMBOL) and v is not None
            }
            payload_json = json.dumps(payload_dict, ensure_ascii=False)

            params = {
                "symbol": symbol,
                "statement_type": statement_type,
                "period": period,
                "year": year,
                "quarter": quarter,
                "payload": payload_json,
            }
            await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (s:{NodeLabel.FINANCIAL_STATEMENT} {{
                    {Prop.SYMBOL}: $symbol,
                    {Prop.STATEMENT_TYPE}: $statement_type,
                    {Prop.PERIOD}: $period,
                    {Prop.YEAR}: $year,
                    {Prop.QUARTER}: $quarter
                }})
                SET s.{Prop.PAYLOAD} = $payload
                MERGE (c)-[:{RelType.HAS_STATEMENT}]->(s)
                """,
                params,
            )
        logger.debug("Upserted %d %s rows for %s", len(df), statement_type, symbol)

    # ------------------------------------------------------------------
    # Financial indicators (ratios)
    # ------------------------------------------------------------------

    async def upsert_financial_indicators(self, df: pl.DataFrame, symbol: str) -> None:
        """
        Upsert FinancialIndicator nodes from a wide-format ratio DataFrame.

        Each column (except symbol, year, quarter) becomes a separate metric node.
        """
        if df is None or df.is_empty():
            return

        metric_cols = [
            c for c in df.columns if c not in (Prop.SYMBOL, Prop.YEAR, Prop.QUARTER)
        ]

        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0))
            quarter = int(row.get(Prop.QUARTER, 0))

            for metric in metric_cols:
                value = row.get(metric)
                if value is None:
                    continue
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue

                params = {
                    "symbol": symbol,
                    "metric": metric,
                    "year": year,
                    "quarter": quarter,
                    "value": value,
                }
                await self._run(
                    f"""
                    MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                    MERGE (i:{NodeLabel.FINANCIAL_INDICATOR} {{
                        {Prop.SYMBOL}: $symbol,
                        {Prop.METRIC}: $metric,
                        {Prop.YEAR}: $year,
                        {Prop.QUARTER}: $quarter
                    }})
                    SET i.{Prop.VALUE} = $value
                    MERGE (c)-[:{RelType.HAS_INDICATOR}]->(i)
                    """,
                    params,
                )
        logger.debug("Upserted indicators for %s", symbol)

    # ------------------------------------------------------------------
    # Officers
    # ------------------------------------------------------------------

    async def upsert_officers(self, df: pl.DataFrame, symbol: str) -> None:
        """
        Upsert Officer nodes and LED_BY edges.

        Expected columns: officer_name, officer_position, officer_own_percent
        """
        if df is None or df.is_empty():
            return

        for row in df.to_dicts():
            name = row.get("officer_name") or ""
            if not name:
                continue
            params = {
                "symbol": symbol,
                "officer_name": name,
                "position": row.get("officer_position") or "",
                "own_percent": float(row.get("officer_own_percent") or 0),
            }
            await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (o:{NodeLabel.OFFICER} {{{Prop.OFFICER_NAME}: $officer_name}})
                SET o.{Prop.POSITION}    = $position,
                    o.{Prop.OWN_PERCENT} = $own_percent
                MERGE (c)-[:{RelType.LED_BY}]->(o)
                """,
                params,
            )
        logger.debug("Upserted %d officers for %s", len(df), symbol)

    # ------------------------------------------------------------------
    # Corporate ownership — subsidiaries
    # ------------------------------------------------------------------

    async def upsert_subsidiaries(self, df: pl.DataFrame, parent_symbol: str) -> None:
        """
        Upsert SUBSIDIARY_OF edges.

        Expected columns from vnstock company.subsidiaries():
          id, sub_organ_code, ownership_percent, organ_name, type
        """
        if df is None or df.is_empty():
            return

        for row in df.to_dicts():
            sub_code = row.get("sub_organ_code") or ""
            ownership = float(row.get("ownership_percent") or 0)
            organ_name = row.get("organ_name") or sub_code
            rel_type = row.get("type") or ""

            if not sub_code:
                continue

            params = {
                "parent_symbol": parent_symbol,
                "sub_code": sub_code,
                "sub_name": organ_name,
                "ownership_percent": ownership,
                "relation_type": rel_type,
            }
            # The subsidiary may not be a listed company — create Company node if needed
            await self._run(
                f"""
                MATCH (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent_symbol}})
                MERGE (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sub_code}})
                ON CREATE SET child.{Prop.NAME} = $sub_name
                MERGE (child)-[r:{RelType.SUBSIDIARY_OF}]->(parent)
                SET r.{Prop.OWNERSHIP_PERCENT} = $ownership_percent,
                    r.{Prop.RELATION_TYPE}      = $relation_type
                """,
                params,
            )
        logger.debug("Upserted %d subsidiaries for %s", len(df), parent_symbol)

    # ------------------------------------------------------------------
    # Shareholders → HOLDS_STAKE_IN edges
    # ------------------------------------------------------------------

    async def upsert_shareholders(self, df: pl.DataFrame, symbol: str) -> None:
        """
        Upsert HOLDS_STAKE_IN edges for major shareholders.

        If the shareholder is a listed ticker, we link Company → Company.
        Otherwise, the shareholder is represented as a generic node keyed by name.

        Expected columns: share_holder, share_own_percent
        (plus optional: id, quantity, update_date from vnstock)
        """
        if df is None or df.is_empty():
            return

        for row in df.to_dicts():
            holder_name = row.get("share_holder") or ""
            stake = float(row.get("share_own_percent") or 0)

            if not holder_name:
                continue

            params = {
                "target_symbol": symbol,
                "holder_name": holder_name,
                "stake_percent": stake,
            }
            # Use a generic Company node keyed by name for unlisted holders
            await self._run(
                f"""
                MATCH (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $target_symbol}})
                MERGE (holder:{NodeLabel.COMPANY} {{{Prop.NAME}: $holder_name}})
                ON CREATE SET holder.{Prop.SYMBOL} = $holder_name
                MERGE (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target)
                SET r.{Prop.STAKE_PERCENT} = $stake_percent
                """,
                params,
            )
        logger.debug("Upserted %d shareholders for %s", len(df), symbol)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> GraphBuilder:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying FalkorDB connection."""
        with contextlib.suppress(Exception):
            await self._client.close()
