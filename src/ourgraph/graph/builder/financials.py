"""Financial statement and indicator upsertion."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

from ourgraph.graph.builder._helpers import serialize_for_json
from ourgraph.graph.builder.core import _GraphBuilderCore
from ourgraph.graph.schema import NodeLabel, Prop, RelType

logger = logging.getLogger(__name__)


class _FinancialMixin(_GraphBuilderCore):
    """Mixin providing financial statement and indicator methods."""

    async def upsert_financial_statement(
        self,
        df: "pl.DataFrame",
        symbol: str,
        statement_type: str,
        period: str,
    ) -> None:
        """Upsert financial statement nodes using batch UNWIND."""
        if df is None or df.is_empty():
            return

        is_quarter = period == "quarter"
        rows: list[dict] = []
        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0))
            quarter = int(row.get(Prop.QUARTER, 0)) if is_quarter else 0

            payload_dict = {
                k: v
                for k, v in row.items()
                if k not in (Prop.YEAR, Prop.QUARTER, Prop.SYMBOL) and v is not None
            }

            rows.append(
                {
                    "symbol": symbol,
                    "statement_type": statement_type,
                    "period": period,
                    "year": year,
                    "quarter": quarter,
                    "payload": json.dumps(
                        serialize_for_json(payload_dict), ensure_ascii=False,
                    ),
                },
            )

        if not rows:
            return

        if is_quarter and rows[0]["quarter"] > 0:
            await self._run(
                f"""
                UNWIND $rows AS r
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: r.symbol}})
                MERGE (fs:{NodeLabel.FINANCIAL_STATEMENT} {{
                    {Prop.SYMBOL}: r.symbol,
                    {Prop.STATEMENT_TYPE}: r.statement_type,
                    {Prop.PERIOD}: r.period,
                    {Prop.YEAR}: r.year,
                    {Prop.QUARTER}: r.quarter
                }})
                SET fs.{Prop.PAYLOAD} = r.payload
                MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs)
                MERGE (q:{NodeLabel.QUARTER} {{{Prop.YEAR}: r.year, {Prop.QUARTER}: r.quarter}})
                MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: r.year}})
                MERGE (q)-[:{RelType.IN_YEAR}]->(y)
                MERGE (fs)-[:{RelType.FOR_QUARTER}]->(q)
                MERGE (fs)-[:{RelType.FOR_YEAR}]->(y)
                """,
                {"rows": rows},
            )
        else:
            await self._run(
                f"""
                UNWIND $rows AS r
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: r.symbol}})
                MERGE (fs:{NodeLabel.FINANCIAL_STATEMENT} {{
                    {Prop.SYMBOL}: r.symbol,
                    {Prop.STATEMENT_TYPE}: r.statement_type,
                    {Prop.PERIOD}: r.period,
                    {Prop.YEAR}: r.year,
                    {Prop.QUARTER}: r.quarter
                }})
                SET fs.{Prop.PAYLOAD} = r.payload
                MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs)
                MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: r.year}})
                MERGE (fs)-[:{RelType.FOR_YEAR}]->(y)
                """,
                {"rows": rows},
            )

    async def upsert_financial_indicators(self, df: "pl.DataFrame", symbol: str) -> None:
        """Upsert financial indicator nodes using batch UNWIND."""
        if df is None or df.is_empty():
            return

        metric_map: dict[str, str] = {
            "pb": Prop.PBR,
            "pbr": Prop.PBR,
            "pe": Prop.PER,
            "per": Prop.PER,
            "eps": Prop.EPS,
            "roe": Prop.ROE,
            "roa": Prop.ROA,
            "debt_to_equity": Prop.DEBT_TO_EQUITY,
            "current_ratio": Prop.CURRENT_RATIO,
            "quick_ratio": Prop.QUICK_RATIO,
            "gross_margin": Prop.GROSS_MARGIN,
            "net_margin": Prop.NET_MARGIN,
            "revenue_growth": Prop.REVENUE_GROWTH,
            "dividend_yield": Prop.DIVIDEND_YIELD,
        }

        indicator_cols = set(metric_map.keys()) | {
            Prop.YEAR,
            Prop.QUARTER,
            Prop.SYMBOL,
            "year",
            "quarter",
            "symbol",
        }

        rows: list[dict] = []
        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0) or row.get("year", 0))
            quarter = int(row.get(Prop.QUARTER, 0) or row.get("quarter", 0))

            metrics: dict[str, float | None] = {}
            for col_key, prop_name in metric_map.items():
                val = row.get(col_key)
                if val is not None:
                    try:
                        metrics[prop_name] = float(val)
                    except (ValueError, TypeError):
                        metrics[prop_name] = None

            payload_dict = {
                k: (v.isoformat() if isinstance(v, date) else v)
                for k, v in row.items()
                if k not in indicator_cols and v is not None
            }

            rows.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "quarter": quarter,
                    "pbr": metrics.get(Prop.PBR),
                    "per": metrics.get(Prop.PER),
                    "eps": metrics.get(Prop.EPS),
                    "roe": metrics.get(Prop.ROE),
                    "roa": metrics.get(Prop.ROA),
                    "debt_to_equity": metrics.get(Prop.DEBT_TO_EQUITY),
                    "current_ratio": metrics.get(Prop.CURRENT_RATIO),
                    "quick_ratio": metrics.get(Prop.QUICK_RATIO),
                    "gross_margin": metrics.get(Prop.GROSS_MARGIN),
                    "net_margin": metrics.get(Prop.NET_MARGIN),
                    "revenue_growth": metrics.get(Prop.REVENUE_GROWTH),
                    "dividend_yield": metrics.get(Prop.DIVIDEND_YIELD),
                    "payload": json.dumps(
                        serialize_for_json(payload_dict), ensure_ascii=False,
                    )
                    if payload_dict
                    else "",
                },
            )

        if not rows:
            return

        await self._run(
            f"""
            UNWIND $rows AS r
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: r.symbol}})
            MERGE (i:{NodeLabel.INDICATOR} {{
                {Prop.SYMBOL}: r.symbol,
                {Prop.YEAR}: r.year,
                {Prop.QUARTER}: r.quarter
            }})
            SET i.{Prop.PBR}              = r.pbr,
                i.{Prop.PER}              = r.per,
                i.{Prop.EPS}              = r.eps,
                i.{Prop.ROE}              = r.roe,
                i.{Prop.ROA}              = r.roa,
                i.{Prop.DEBT_TO_EQUITY}   = r.debt_to_equity,
                i.{Prop.CURRENT_RATIO}    = r.current_ratio,
                i.{Prop.QUICK_RATIO}      = r.quick_ratio,
                i.{Prop.GROSS_MARGIN}     = r.gross_margin,
                i.{Prop.NET_MARGIN}       = r.net_margin,
                i.{Prop.REVENUE_GROWTH}   = r.revenue_growth,
                i.{Prop.DIVIDEND_YIELD}   = r.dividend_yield,
                i.{Prop.PAYLOAD}          = r.payload
            MERGE (c)-[:{RelType.HAS_INDICATOR}]->(i)
            MERGE (q:{NodeLabel.QUARTER} {{{Prop.YEAR}: r.year, {Prop.QUARTER}: r.quarter}})
            MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: r.year}})
            MERGE (q)-[:{RelType.IN_YEAR}]->(y)
            MERGE (i)-[:{RelType.MEASURED_ON}]->(q)
            """,
            {"rows": rows},
        )
