"""Core knowledge graph builder — aligned with the paper's schema.

Node hierarchy:
  Company → HAS_STOCK_PRICE → StockPrice → RECORDED_ON → Date → IN_QUARTER → Quarter → IN_YEAR → Year
  Company → HAS_INDICATOR   → Indicator  → MEASURED_ON → Quarter
  Company → HAS_FINANCIAL_STATEMENTS → FinancialStatement → FOR_QUARTER → Quarter
                                                           → FOR_YEAR   → Year
  Company → BELONGS_TO → Sector
  Company → BELONGS_TO_INDUSTRY → Industry
  Company → COMPETES_WITH → Company
  Company → SUBSIDIARY_OF → Company
  Company → HOLDS_STAKE_IN → Company
  Company → LED_BY → Officer
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Self

from ourgraph.graph.schema import NodeLabel, Prop, RelType

if TYPE_CHECKING:
    import polars as pl
    from falkordb.asyncio import FalkorDB

    from ourgraph.config import FalkorDBSettings

logger = logging.getLogger(__name__)


def _quarter_of(month: int) -> int:
    return (month - 1) // 3 + 1


def _serialize_for_json(obj: dict) -> dict:
    """Convert datetime/date objects in dict to ISO format strings for JSON serialization."""
    return {
        k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
        for k, v in obj.items()
    }


class GraphBuilder:
    """Async graph builder backed by FalkorDB."""

    def __init__(self, client: FalkorDB, graph_name: str) -> None:
        self._client = client
        self._graph_name = graph_name

    @classmethod
    def from_settings(cls, settings: FalkorDBSettings) -> GraphBuilder:
        from ourgraph.db.falkordb import build_falkordb_client

        return cls(
            client=build_falkordb_client(settings),
            graph_name=settings.graph_name,
        )

    async def _graph(self) -> object:
        return self._client.select_graph(self._graph_name)

    async def _run(self, query: str, params: dict | None = None) -> list:
        g = await self._graph()
        result = await g.query(query, params or {})
        return result.result_set

    # ------------------------------------------------------------------
    # Index setup
    # ------------------------------------------------------------------

    async def ensure_indices(self) -> None:
        indices = [
            f"CREATE INDEX ON :{NodeLabel.COMPANY}({Prop.SYMBOL})",
            f"CREATE INDEX ON :{NodeLabel.SECTOR}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.INDUSTRY}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.STOCK_PRICE}({Prop.SYMBOL}, {Prop.DATE})",
            f"CREATE INDEX ON :{NodeLabel.FINANCIAL_STATEMENT}({Prop.SYMBOL}, {Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.INDICATOR}({Prop.SYMBOL}, {Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.OFFICER}({Prop.OFFICER_NAME})",
            f"CREATE INDEX ON :{NodeLabel.DATE}({Prop.DATE})",
            f"CREATE INDEX ON :{NodeLabel.QUARTER}({Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.YEAR}({Prop.YEAR})",
        ]
        for idx in indices:
            try:
                await self._run(idx)
            except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                exc_str = str(exc).lower()
                if "already exists" not in exc_str and "already indexed" not in exc_str:
                    logger.warning("Index warning: %s — %s", idx, exc)

    # ------------------------------------------------------------------
    # Company nodes
    # ------------------------------------------------------------------

    async def upsert_companies(self, df: pl.DataFrame) -> None:
        for row in df.to_dicts():
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
                SET c.{Prop.NAME}             = $name,
                    c.{Prop.EXCHANGE}         = $exchange,
                    c.{Prop.MARKET_CAP}       = $market_cap,
                    c.{Prop.NO_EMPLOYEES}     = $no_employees,
                    c.{Prop.ESTABLISHED_YEAR} = $established_year,
                    c.{Prop.WEBSITE}          = $website,
                    c.{Prop.OUTSTANDING_SHARE}= $outstanding_share,
                    c.{Prop.FOREIGN_PERCENT}  = $foreign_percent
                """,
                params,
            )

    # ------------------------------------------------------------------
    # Sector / Industry + COMPETES_WITH
    # ------------------------------------------------------------------

    async def upsert_sector_industry(self, df: pl.DataFrame) -> None:
        for row in df.to_dicts():
            symbol = row.get(Prop.SYMBOL, "")
            industry = row.get("industry") or ""
            if not industry:
                continue
            await self._run(
                f"""
                MERGE (ind:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry}})
                WITH ind
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (c)-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind)
                """,
                {"symbol": symbol, "industry": industry},
            )

        # Sector from the industry string (top-level)
        for row in df.to_dicts():
            symbol = row.get(Prop.SYMBOL, "")
            industry = row.get("industry") or ""
            if not industry:
                continue
            # Use industry as sector too if no separate sector field
            sector = (
                row.get("sector") or industry.split(" - ")[0]
                if " - " in industry
                else industry
            )
            await self._run(
                f"""
                MERGE (s:{NodeLabel.SECTOR} {{{Prop.NAME}: $sector}})
                WITH s
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (c)-[:{RelType.BELONGS_TO}]->(s)
                """,
                {"symbol": symbol, "sector": sector},
            )

    async def upsert_competes_with(self) -> None:
        """Create COMPETES_WITH edges between all companies in the same sector.

        Run once after all companies and sectors are upserted.
        """
        await self._run(
            f"""
            MATCH (a:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO}]->(s:{NodeLabel.SECTOR})
                  <-[:{RelType.BELONGS_TO}]-(b:{NodeLabel.COMPANY})
            WHERE a.{Prop.SYMBOL} < b.{Prop.SYMBOL}
            MERGE (a)-[:{RelType.COMPETES_WITH}]->(b)
            MERGE (b)-[:{RelType.COMPETES_WITH}]->(a)
            """,
        )

    # ------------------------------------------------------------------
    # Stock price nodes — with Date/Quarter/Year hierarchy
    # ------------------------------------------------------------------

    async def upsert_stock_prices(self, df: pl.DataFrame) -> None:
        for row in df.to_dicts():
            date_val = row.get(Prop.DATE)
            if isinstance(date_val, date):
                date_str = date_val.isoformat()
                d = date_val
            else:
                date_str = str(date_val)
                try:
                    d = date.fromisoformat(date_str)
                except ValueError:
                    logger.debug("Skipping invalid date: %s", date_str)
                    continue

            year = d.year
            month = d.month
            day = d.day
            quarter = _quarter_of(month)

            params = {
                "symbol": row[Prop.SYMBOL],
                "date": date_str,
                "open": float(row.get(Prop.OPEN) or 0),
                "high": float(row.get(Prop.HIGH) or 0),
                "low": float(row.get(Prop.LOW) or 0),
                "close": float(row.get(Prop.CLOSE) or 0),
                "volume": int(row.get(Prop.VOLUME) or 0),
                "year": year,
                "month": month,
                "day": day,
                "quarter": quarter,
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
                MERGE (c)-[:{RelType.HAS_STOCK_PRICE}]->(p)
                MERGE (d:{NodeLabel.DATE} {{{Prop.DATE}: $date}})
                SET d.{Prop.YEAR}  = $year,
                    d.{Prop.MONTH} = $month,
                    d.{Prop.DAY}   = $day
                MERGE (q:{NodeLabel.QUARTER} {{{Prop.YEAR}: $year, {Prop.QUARTER}: $quarter}})
                MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: $year}})
                MERGE (d)-[:{RelType.IN_QUARTER}]->(q)
                MERGE (q)-[:{RelType.IN_YEAR}]->(y)
                MERGE (p)-[:{RelType.RECORDED_ON}]->(d)
                """,
                params,
            )

    # ------------------------------------------------------------------
    # Financial statements — linked to Quarter and Year
    # ------------------------------------------------------------------

    async def upsert_financial_statement(
        self,
        df: pl.DataFrame,
        symbol: str,
        statement_type: str,
        period: str,
    ) -> None:
        if df is None or df.is_empty():
            return

        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0))
            quarter = int(row.get(Prop.QUARTER, 0)) if period == "quarter" else 0

            payload_dict = {
                k: v
                for k, v in row.items()
                if k not in (Prop.YEAR, Prop.QUARTER, Prop.SYMBOL) and v is not None
            }
            payload_json = json.dumps(
                _serialize_for_json(payload_dict),
                ensure_ascii=False,
            )

            params = {
                "symbol": symbol,
                "statement_type": statement_type,
                "period": period,
                "year": year,
                "quarter": quarter,
                "payload": payload_json,
            }

            if period == "quarter" and quarter > 0:
                await self._run(
                    f"""
                    MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                    MERGE (fs:{NodeLabel.FINANCIAL_STATEMENT} {{
                        {Prop.SYMBOL}: $symbol,
                        {Prop.STATEMENT_TYPE}: $statement_type,
                        {Prop.PERIOD}: $period,
                        {Prop.YEAR}: $year,
                        {Prop.QUARTER}: $quarter
                    }})
                    SET fs.{Prop.PAYLOAD} = $payload
                    MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs)
                    MERGE (q:{NodeLabel.QUARTER} {{{Prop.YEAR}: $year, {Prop.QUARTER}: $quarter}})
                    MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: $year}})
                    MERGE (q)-[:{RelType.IN_YEAR}]->(y)
                    MERGE (fs)-[:{RelType.FOR_QUARTER}]->(q)
                    MERGE (fs)-[:{RelType.FOR_YEAR}]->(y)
                    """,
                    params,
                )
            else:
                await self._run(
                    f"""
                    MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                    MERGE (fs:{NodeLabel.FINANCIAL_STATEMENT} {{
                        {Prop.SYMBOL}: $symbol,
                        {Prop.STATEMENT_TYPE}: $statement_type,
                        {Prop.PERIOD}: $period,
                        {Prop.YEAR}: $year,
                        {Prop.QUARTER}: $quarter
                    }})
                    SET fs.{Prop.PAYLOAD} = $payload
                    MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs)
                    MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: $year}})
                    MERGE (fs)-[:{RelType.FOR_YEAR}]->(y)
                    """,
                    params,
                )

    # ------------------------------------------------------------------
    # Financial indicators — Indicator node per company per quarter
    # ------------------------------------------------------------------

    async def upsert_financial_indicators(self, df: pl.DataFrame, symbol: str) -> None:
        """Upsert indicator nodes with key ratios and full payload.

        Paper schema: Indicator {pbr, per, eps} -> MEASURED_ON -> Quarter.
        """
        if df is None or df.is_empty():
            return

        metric_map = {
            # Common vnstock ratio column names → paper property names
            "pb": Prop.PBR,
            "price_to_book": Prop.PBR,
            "pbr": Prop.PBR,
            "pe": Prop.PER,
            "price_to_earning": Prop.PER,
            "per": Prop.PER,
            "eps": Prop.EPS,
            "earning_per_share": Prop.EPS,
        }

        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0))
            quarter = int(row.get(Prop.QUARTER, 0))

            # Extract paper's key metrics
            pbr = next(
                (
                    float(row[k])
                    for k in metric_map
                    if metric_map[k] == Prop.PBR and k in row and row[k] is not None
                ),
                None,
            )
            per = next(
                (
                    float(row[k])
                    for k in metric_map
                    if metric_map[k] == Prop.PER and k in row and row[k] is not None
                ),
                None,
            )
            eps = next(
                (
                    float(row[k])
                    for k in metric_map
                    if metric_map[k] == Prop.EPS and k in row and row[k] is not None
                ),
                None,
            )

            payload_dict = {
                k: (v.isoformat() if isinstance(v, date) else v)
                for k, v in row.items()
                if k not in (Prop.YEAR, Prop.QUARTER, Prop.SYMBOL) and v is not None
            }

            params = {
                "symbol": symbol,
                "year": year,
                "quarter": quarter,
                "pbr": pbr,
                "per": per,
                "eps": eps,
                "payload": json.dumps(
                    _serialize_for_json(payload_dict),
                    ensure_ascii=False,
                ),
            }
            await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (i:{NodeLabel.INDICATOR} {{
                    {Prop.SYMBOL}: $symbol,
                    {Prop.YEAR}: $year,
                    {Prop.QUARTER}: $quarter
                }})
                SET i.{Prop.PBR}     = $pbr,
                    i.{Prop.PER}     = $per,
                    i.{Prop.EPS}     = $eps,
                    i.{Prop.PAYLOAD} = $payload
                MERGE (c)-[:{RelType.HAS_INDICATOR}]->(i)
                MERGE (q:{NodeLabel.QUARTER} {{{Prop.YEAR}: $year, {Prop.QUARTER}: $quarter}})
                MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: $year}})
                MERGE (q)-[:{RelType.IN_YEAR}]->(y)
                MERGE (i)-[:{RelType.MEASURED_ON}]->(q)
                """,
                params,
            )

    # ------------------------------------------------------------------
    # Officers
    # ------------------------------------------------------------------

    async def upsert_officers(self, df: pl.DataFrame, symbol: str) -> None:
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

    # ------------------------------------------------------------------
    # Subsidiaries
    # ------------------------------------------------------------------

    async def upsert_subsidiaries(self, df: pl.DataFrame, parent_symbol: str) -> None:
        if df is None or df.is_empty():
            return
        for row in df.to_dicts():
            sub_code = row.get("sub_organ_code") or ""
            if not sub_code:
                continue
            params = {
                "parent_symbol": parent_symbol,
                "sub_code": sub_code,
                "sub_name": row.get("organ_name") or sub_code,
                "ownership_percent": float(row.get("ownership_percent") or 0),
                "relation_type": row.get("type") or "",
            }
            await self._run(
                f"""
                MATCH (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent_symbol}})
                MERGE (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sub_code}})
                ON CREATE SET child.{Prop.NAME} = $sub_name
                MERGE (child)-[r:{RelType.SUBSIDIARY_OF}]->(parent)
                SET r.{Prop.OWNERSHIP_PERCENT} = $ownership_percent,
                    r.{Prop.RELATION_TYPE}     = $relation_type
                """,
                params,
            )

    # ------------------------------------------------------------------
    # Shareholders
    # ------------------------------------------------------------------

    async def upsert_shareholders(self, df: pl.DataFrame, symbol: str) -> None:
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

    # ------------------------------------------------------------------
    # Deduplication / redundancy removal
    # ------------------------------------------------------------------

    async def deduplicate_nodes(self) -> dict[str, int]:
        """Merge duplicate nodes by natural keys and preserve relationships.

        This is intended as a maintenance operation for previously ingested
        data where duplicates may already exist.
        """
        stats: dict[str, int] = {}

        stats["company"] = await self._dedupe_company_by_symbol()
        stats["stock_price"] = await self._dedupe_stock_price_by_symbol_date()
        stats["indicator"] = await self._dedupe_indicator_by_symbol_period()
        stats["financial_statement"] = await self._dedupe_fin_stmt_by_identity()
        stats["date"] = await self._dedupe_date_by_date()
        stats["quarter"] = await self._dedupe_quarter_by_year_quarter()
        stats["year"] = await self._dedupe_year_by_year()
        stats["sector"] = await self._dedupe_sector_by_name()
        stats["industry"] = await self._dedupe_industry_by_name()

        logger.info("Deduplication finished: %s", stats)
        return stats

    async def _dedupe_company_by_symbol(self) -> int:
        rows = await self._run(
            f"""
            MATCH (c:{NodeLabel.COMPANY})
            WITH c.{Prop.SYMBOL} AS symbol, collect(c) AS nodes
            WHERE symbol IS NOT NULL AND symbol <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            // Outgoing edges
            OPTIONAL MATCH (dup)-[:{RelType.HAS_STOCK_PRICE}]->(p:{NodeLabel.STOCK_PRICE})
            FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.HAS_STOCK_PRICE}]->(p)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.HAS_INDICATOR}]->(i:{NodeLabel.INDICATOR})
            FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.HAS_INDICATOR}]->(i)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs:{NodeLabel.FINANCIAL_STATEMENT})
            FOREACH (_ IN CASE WHEN fs IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.BELONGS_TO}]->(s:{NodeLabel.SECTOR})
            FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.BELONGS_TO}]->(s)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
            FOREACH (_ IN CASE WHEN ind IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.COMPETES_WITH}]->(other:{NodeLabel.COMPANY})
            FOREACH (_ IN CASE WHEN other IS NULL OR id(other) = id(keep) THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.COMPETES_WITH}]->(other)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[r_sub:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY})
            FOREACH (_ IN CASE WHEN parent IS NULL OR id(parent) = id(keep) THEN [] ELSE [1] END |
                MERGE (keep)-[r2:{RelType.SUBSIDIARY_OF}]->(parent)
                SET r2.{Prop.OWNERSHIP_PERCENT} = coalesce(r2.{Prop.OWNERSHIP_PERCENT}, r_sub.{Prop.OWNERSHIP_PERCENT}),
                    r2.{Prop.RELATION_TYPE} = coalesce(r2.{Prop.RELATION_TYPE}, r_sub.{Prop.RELATION_TYPE})
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[r_hold:{RelType.HOLDS_STAKE_IN}]->(target:{NodeLabel.COMPANY})
            FOREACH (_ IN CASE WHEN target IS NULL OR id(target) = id(keep) THEN [] ELSE [1] END |
                MERGE (keep)-[r2:{RelType.HOLDS_STAKE_IN}]->(target)
                SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r_hold.{Prop.STAKE_PERCENT})
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.LED_BY}]->(o:{NodeLabel.OFFICER})
            FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.LED_BY}]->(o)
            )
            WITH keep, dup

            // Incoming edges
            OPTIONAL MATCH (other:{NodeLabel.COMPANY})-[:{RelType.COMPETES_WITH}]->(dup)
            FOREACH (_ IN CASE WHEN other IS NULL OR id(other) = id(keep) THEN [] ELSE [1] END |
                MERGE (other)-[:{RelType.COMPETES_WITH}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (child:{NodeLabel.COMPANY})-[r_sub_in:{RelType.SUBSIDIARY_OF}]->(dup)
            FOREACH (_ IN CASE WHEN child IS NULL OR id(child) = id(keep) THEN [] ELSE [1] END |
                MERGE (child)-[r2:{RelType.SUBSIDIARY_OF}]->(keep)
                SET r2.{Prop.OWNERSHIP_PERCENT} = coalesce(r2.{Prop.OWNERSHIP_PERCENT}, r_sub_in.{Prop.OWNERSHIP_PERCENT}),
                    r2.{Prop.RELATION_TYPE} = coalesce(r2.{Prop.RELATION_TYPE}, r_sub_in.{Prop.RELATION_TYPE})
            )
            WITH keep, dup

            OPTIONAL MATCH (holder:{NodeLabel.COMPANY})-[r_hold_in:{RelType.HOLDS_STAKE_IN}]->(dup)
            FOREACH (_ IN CASE WHEN holder IS NULL OR id(holder) = id(keep) THEN [] ELSE [1] END |
                MERGE (holder)-[r2:{RelType.HOLDS_STAKE_IN}]->(keep)
                SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r_hold_in.{Prop.STAKE_PERCENT})
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_stock_price_by_symbol_date(self) -> int:
        rows = await self._run(
            f"""
            MATCH (p:{NodeLabel.STOCK_PRICE})
            WITH p.{Prop.SYMBOL} AS symbol, p.{Prop.DATE} AS dt, collect(p) AS nodes
            WHERE symbol IS NOT NULL AND symbol <> ''
              AND dt IS NOT NULL AND dt <> ''
              AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.HAS_STOCK_PRICE}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.HAS_STOCK_PRICE}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.RECORDED_ON}]->(d:{NodeLabel.DATE})
            FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.RECORDED_ON}]->(d)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_indicator_by_symbol_period(self) -> int:
        rows = await self._run(
            f"""
            MATCH (i:{NodeLabel.INDICATOR})
            WITH i.{Prop.SYMBOL} AS symbol, i.{Prop.YEAR} AS y, i.{Prop.QUARTER} AS q, collect(i) AS nodes
            WHERE symbol IS NOT NULL AND symbol <> ''
              AND y IS NOT NULL AND q IS NOT NULL
              AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.HAS_INDICATOR}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.HAS_INDICATOR}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.MEASURED_ON}]->(q:{NodeLabel.QUARTER})
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.MEASURED_ON}]->(q)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_fin_stmt_by_identity(self) -> int:
        rows = await self._run(
            f"""
            MATCH (fs:{NodeLabel.FINANCIAL_STATEMENT})
            WITH fs.{Prop.SYMBOL} AS symbol,
                 fs.{Prop.STATEMENT_TYPE} AS st,
                 fs.{Prop.PERIOD} AS p,
                 fs.{Prop.YEAR} AS y,
                 fs.{Prop.QUARTER} AS q,
                 collect(fs) AS nodes
            WHERE symbol IS NOT NULL AND symbol <> ''
              AND st IS NOT NULL AND p IS NOT NULL AND y IS NOT NULL AND q IS NOT NULL
              AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.FOR_QUARTER}]->(q:{NodeLabel.QUARTER})
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.FOR_QUARTER}]->(q)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.FOR_YEAR}]->(y:{NodeLabel.YEAR})
            FOREACH (_ IN CASE WHEN y IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.FOR_YEAR}]->(y)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_date_by_date(self) -> int:
        rows = await self._run(
            f"""
            MATCH (d:{NodeLabel.DATE})
            WITH d.{Prop.DATE} AS dt, collect(d) AS nodes
            WHERE dt IS NOT NULL AND dt <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (p:{NodeLabel.STOCK_PRICE})-[:{RelType.RECORDED_ON}]->(dup)
            FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
                MERGE (p)-[:{RelType.RECORDED_ON}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.IN_QUARTER}]->(q:{NodeLabel.QUARTER})
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.IN_QUARTER}]->(q)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_quarter_by_year_quarter(self) -> int:
        rows = await self._run(
            f"""
            MATCH (q:{NodeLabel.QUARTER})
            WITH q.{Prop.YEAR} AS y, q.{Prop.QUARTER} AS qq, collect(q) AS nodes
            WHERE y IS NOT NULL AND qq IS NOT NULL AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (d:{NodeLabel.DATE})-[:{RelType.IN_QUARTER}]->(dup)
            FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
                MERGE (d)-[:{RelType.IN_QUARTER}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (i:{NodeLabel.INDICATOR})-[:{RelType.MEASURED_ON}]->(dup)
            FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END |
                MERGE (i)-[:{RelType.MEASURED_ON}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (fs:{NodeLabel.FINANCIAL_STATEMENT})-[:{RelType.FOR_QUARTER}]->(dup)
            FOREACH (_ IN CASE WHEN fs IS NULL THEN [] ELSE [1] END |
                MERGE (fs)-[:{RelType.FOR_QUARTER}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.IN_YEAR}]->(y:{NodeLabel.YEAR})
            FOREACH (_ IN CASE WHEN y IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.IN_YEAR}]->(y)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_year_by_year(self) -> int:
        rows = await self._run(
            f"""
            MATCH (y:{NodeLabel.YEAR})
            WITH y.{Prop.YEAR} AS yy, collect(y) AS nodes
            WHERE yy IS NOT NULL AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (q:{NodeLabel.QUARTER})-[:{RelType.IN_YEAR}]->(dup)
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (q)-[:{RelType.IN_YEAR}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (fs:{NodeLabel.FINANCIAL_STATEMENT})-[:{RelType.FOR_YEAR}]->(dup)
            FOREACH (_ IN CASE WHEN fs IS NULL THEN [] ELSE [1] END |
                MERGE (fs)-[:{RelType.FOR_YEAR}]->(keep)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_sector_by_name(self) -> int:
        rows = await self._run(
            f"""
            MATCH (s:{NodeLabel.SECTOR})
            WITH s.{Prop.NAME} AS name, collect(s) AS nodes
            WHERE name IS NOT NULL AND name <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.BELONGS_TO}]->(keep)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_industry_by_name(self) -> int:
        rows = await self._run(
            f"""
            MATCH (ind:{NodeLabel.INDUSTRY})
            WITH ind.{Prop.NAME} AS name, collect(ind) AS nodes
            WHERE name IS NOT NULL AND name <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO_INDUSTRY}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.BELONGS_TO_INDUSTRY}]->(keep)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def clear_graph(self) -> dict[str, int]:
        """Delete all nodes and relationships in the current graph."""
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
        return {
            "deleted_nodes": nodes_before,
            "deleted_relationships": rels_before,
        }

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
