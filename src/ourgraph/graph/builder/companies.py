"""Company, Sector, Industry upsertion and competition edge generation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

from ourgraph.graph.builder._helpers import first_nonempty, resolve_subsidiary_symbol
from ourgraph.graph.builder.core import _GraphBuilderCore
from ourgraph.graph.schema import NodeLabel, Prop, RelType

logger = logging.getLogger(__name__)


class _CompanyMixin(_GraphBuilderCore):
    """Mixin providing company, sector, industry, and subsidiary methods."""

    async def upsert_companies(self, df: "pl.DataFrame") -> None:
        """Upsert Company nodes from a DataFrame."""
        for row in df.to_dicts():
            params = {
                "symbol": row.get(Prop.SYMBOL, ""),
                "name": first_nonempty(
                    row, "short_name", "company_name", "name", Prop.SYMBOL,
                )
                or row.get(Prop.SYMBOL, ""),
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
                    c.{Prop.FOREIGN_PERCENT}  = $foreign_percent,
                    c.company_type            = 'listed'
                """,
                params,
            )

    async def upsert_sector_industry(self, df: "pl.DataFrame") -> None:
        """Upsert Sector/Industry nodes with BELONGS_TO / BELONGS_TO_INDUSTRY edges."""
        for row in df.to_dicts():
            symbol = row.get(Prop.SYMBOL, "")
            industry = first_nonempty(
                row, "industry", "industryName", "industry_name", "sector", "nganh",
            )
            if not industry:
                logger.debug(
                    "No industry for %s — columns: %s", symbol, list(row.keys()),
                )
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

        for row in df.to_dicts():
            symbol = row.get(Prop.SYMBOL, "")
            industry = first_nonempty(
                row, "industry", "industryName", "industry_name", "sector", "nganh",
            )
            if not industry:
                continue
            sector = first_nonempty(row, "sector", "sectorName", "sector_name") or (
                industry.split(" - ")[0] if " - " in industry else industry
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
        """Create single COMPETES_WITH edge per pair (symmetric relationship)."""
        await self._run(f"MATCH ()-[r:{RelType.COMPETES_WITH}]->() DELETE r")
        await self._run(
            f"""
            MATCH (a:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
                  <-[:{RelType.BELONGS_TO_INDUSTRY}]-(b:{NodeLabel.COMPANY})
            WHERE a.{Prop.SYMBOL} < b.{Prop.SYMBOL}
            MERGE (a)-[:{RelType.COMPETES_WITH}]->(b)
            """,
        )

    async def upsert_subsidiaries(
        self,
        df: "pl.DataFrame",
        parent_symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        """Upsert subsidiary Company nodes with SUBSIDIARY_OF / HOLDS_STAKE_IN edges."""
        if df is None or df.is_empty():
            return

        parent_exists = await self._run(
            f"MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent}}) RETURN COUNT(c)",
            {"parent": parent_symbol},
        )
        if not parent_exists or int(parent_exists[0][0]) == 0:
            logger.warning(
                "Parent company %s not found in graph, skipping subsidiaries",
                parent_symbol,
            )
            return

        for row in df.to_dicts():
            sub_name = row.get("name") or row.get("organ_name") or ""
            if not sub_name:
                continue

            sub_code = resolve_subsidiary_symbol(
                sub_name,
                row.get("sub_organ_code"),
                name_to_symbol,
            )

            if sub_code.upper() == parent_symbol.upper():
                logger.debug("Skipping self-reference subsidiary: %s", sub_name)
                continue

            ownership_pct = float(
                row.get("ownership_percent") or row.get("ownership_perce") or 0,
            )

            params = {
                "parent_symbol": parent_symbol,
                "sub_code": sub_code,
                "sub_name": sub_name,
                "ownership_percent": ownership_pct,
                "relation_type": row.get("type") or row.get("relation_type") or "",
            }

            if ownership_pct >= 50:
                await self._run(
                    f"""
                    MATCH (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent_symbol}})
                    MERGE (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sub_code}})
                    ON CREATE SET child.{Prop.NAME} = $sub_name,
                                  child.company_type = 'subsidiary'
                    MERGE (child)-[r:{RelType.SUBSIDIARY_OF}]->(parent)
                    SET r.{Prop.OWNERSHIP_PERCENT} = $ownership_percent,
                        r.{Prop.RELATION_TYPE}     = $relation_type
                    """,
                    params,
                )
            else:
                await self._run(
                    f"""
                    MATCH (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent_symbol}})
                    MERGE (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sub_code}})
                    ON CREATE SET child.{Prop.NAME} = $sub_name,
                                  child.company_type = 'subsidiary'
                    MERGE (parent)-[r:{RelType.HOLDS_STAKE_IN}]->(child)
                    SET r.{Prop.STAKE_PERCENT} = $ownership_percent,
                        r.{Prop.RELATION_TYPE} = $relation_type
                    """,
                    params,
                )
