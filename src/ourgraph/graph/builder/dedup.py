"""Node deduplication — merges duplicate nodes by identity key."""

from __future__ import annotations

import logging

from ourgraph.graph.builder.core import _GraphBuilderCore
from ourgraph.graph.schema import NodeLabel, Prop, RelType

logger = logging.getLogger(__name__)


class _DedupMixin(_GraphBuilderCore):
    """Mixin providing node deduplication methods."""

    async def deduplicate_nodes(self) -> dict[str, int]:
        """Run all deduplication steps and return stats per node type."""
        stats: dict[str, int] = {}
        stats["company"] = await self._dedupe_company_by_symbol()
        stats["person"] = await self._dedupe_person_by_name()
        stats["indicator"] = await self._dedupe_indicator_by_symbol_period()
        stats["financial_statement"] = await self._dedupe_fin_stmt_by_identity()
        stats["date"] = await self._dedupe_date_by_date()
        stats["quarter"] = await self._dedupe_quarter_by_year_quarter()
        stats["year"] = await self._dedupe_year_by_year()
        stats["sector"] = await self._dedupe_sector_by_name()
        stats["industry"] = await self._dedupe_industry_by_name()
        logger.info("Deduplication finished: %s", stats)
        return stats

    async def _dedupe_person_by_name(self) -> int:
        """Deduplicate Person nodes by person_name."""
        rows = await self._run(
            f"""
            MATCH (p:{NodeLabel.PERSON})
            WITH p.{Prop.PERSON_NAME} AS name, collect(p) AS nodes
            WHERE name IS NOT NULL AND name <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (dup)-[r_off:{RelType.IS_OFFICER}]->(c:{NodeLabel.COMPANY})
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[r2:{RelType.IS_OFFICER}]->(c)
                SET r2.{Prop.POSITION} = coalesce(r2.{Prop.POSITION}, r_off.{Prop.POSITION}),
                    r2.{Prop.OWN_PERCENT} = coalesce(r2.{Prop.OWN_PERCENT}, r_off.{Prop.OWN_PERCENT})
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[r_hold:{RelType.HOLDS_STAKE_IN}]->(target:{NodeLabel.COMPANY})
            FOREACH (_ IN CASE WHEN target IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[r2:{RelType.HOLDS_STAKE_IN}]->(target)
                SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r_hold.{Prop.STAKE_PERCENT})
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_company_by_symbol(self) -> int:
        """Deduplicate Company nodes by symbol."""
        total_removed = 0

        while True:
            rows = await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY})
                WITH c.{Prop.SYMBOL} AS sym, collect(c) AS nodes
                WHERE sym IS NOT NULL AND sym <> '' AND size(nodes) > 1
                UNWIND nodes[1..] AS dup
                RETURN sym, nodes[0] AS keep, dup
                LIMIT 10
                """,
            )
            if not rows:
                break

            for row_data in rows:
                sym = row_data[0]

                for rel_type, target_label in [
                    (RelType.HAS_INDICATOR, NodeLabel.INDICATOR),
                    (RelType.HAS_FINANCIAL_STATEMENTS, NodeLabel.FINANCIAL_STATEMENT),
                    (RelType.BELONGS_TO, NodeLabel.SECTOR),
                    (RelType.BELONGS_TO_INDUSTRY, NodeLabel.INDUSTRY),
                ]:
                    await self._run(
                        f"""
                        MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[:{rel_type}]->(t:{target_label})
                        WITH t
                        LIMIT 100
                        MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                        WITH t, keep
                        LIMIT 100
                        MERGE (keep)-[:{rel_type}]->(t)
                        """,
                        {"sym": sym},
                    )

                await self._run(
                    f"""
                    MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[:{RelType.COMPETES_WITH}]->(other:{NodeLabel.COMPANY})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(other) <> id(keep)
                    MERGE (keep)-[:{RelType.COMPETES_WITH}]->(other)
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(parent) <> id(keep)
                    MERGE (keep)-[r2:{RelType.SUBSIDIARY_OF}]->(parent)
                    SET r2.{Prop.OWNERSHIP_PERCENT} = coalesce(r2.{Prop.OWNERSHIP_PERCENT}, r.{Prop.OWNERSHIP_PERCENT}),
                        r2.{Prop.RELATION_TYPE} = coalesce(r2.{Prop.RELATION_TYPE}, r.{Prop.RELATION_TYPE})
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[r:{RelType.HOLDS_STAKE_IN}]->(target:{NodeLabel.COMPANY})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(target) <> id(keep)
                    MERGE (keep)-[r2:{RelType.HOLDS_STAKE_IN}]->(target)
                    SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r.{Prop.STAKE_PERCENT})
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (other:{NodeLabel.COMPANY})-[:{RelType.COMPETES_WITH}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(other) <> id(keep)
                    MERGE (other)-[:{RelType.COMPETES_WITH}]->(keep)
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(child) <> id(keep)
                    MERGE (child)-[r2:{RelType.SUBSIDIARY_OF}]->(keep)
                    SET r2.{Prop.OWNERSHIP_PERCENT} = coalesce(r2.{Prop.OWNERSHIP_PERCENT}, r.{Prop.OWNERSHIP_PERCENT}),
                        r2.{Prop.RELATION_TYPE} = coalesce(r2.{Prop.RELATION_TYPE}, r.{Prop.RELATION_TYPE})
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (holder:{NodeLabel.COMPANY})-[r:{RelType.HOLDS_STAKE_IN}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(holder) <> id(keep)
                    MERGE (holder)-[r2:{RelType.HOLDS_STAKE_IN}]->(keep)
                    SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r.{Prop.STAKE_PERCENT})
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (person:{NodeLabel.PERSON})-[r:{RelType.IS_OFFICER}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MERGE (person)-[r2:{RelType.IS_OFFICER}]->(keep)
                    SET r2.{Prop.POSITION} = coalesce(r2.{Prop.POSITION}, r.{Prop.POSITION}),
                        r2.{Prop.OWN_PERCENT} = coalesce(r2.{Prop.OWN_PERCENT}, r.{Prop.OWN_PERCENT})
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (person:{NodeLabel.PERSON})-[r:{RelType.HOLDS_STAKE_IN}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MERGE (person)-[r2:{RelType.HOLDS_STAKE_IN}]->(keep)
                    SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r.{Prop.STAKE_PERCENT})
                    """,
                    {"sym": sym},
                )

                await self._run(
                    f"""
                    MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WITH c
                    ORDER BY size(keys(c)) DESC
                    WITH collect(c) AS nodes
                    WITH nodes[0] AS keep, nodes[1..] AS dups
                    UNWIND dups AS dup
                    SET keep += properties(dup)
                    WITH dup
                    DETACH DELETE dup
                    RETURN COUNT(*)
                    """,
                    {"sym": sym},
                )
                total_removed += 1

        return total_removed

    async def _dedupe_indicator_by_symbol_period(self) -> int:
        """Deduplicate Indicator nodes by (symbol, year, quarter)."""
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
        """Deduplicate FinancialStatement nodes."""
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
        """Deduplicate Date nodes by date value."""
        rows = await self._run(
            f"""
            MATCH (d:{NodeLabel.DATE})
            WITH d.{Prop.DATE} AS dt, collect(d) AS nodes
            WHERE dt IS NOT NULL AND dt <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

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
        """Deduplicate Quarter nodes by (year, quarter)."""
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
        """Deduplicate Year nodes by year value."""
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
        """Deduplicate Sector nodes by name."""
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
        """Deduplicate Industry nodes by name."""
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
