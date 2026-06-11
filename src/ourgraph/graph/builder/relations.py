"""Macro indicators, country, bonds, auditor, company events, and scraper relationships."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

from ourgraph.graph.builder._helpers import first_nonempty, serialize_for_json
from ourgraph.graph.builder.core import _GraphBuilderCore
from ourgraph.graph.schema import NodeLabel, Prop, RelType

logger = logging.getLogger(__name__)


class _RelationsMixin(_GraphBuilderCore):
    """Mixin providing country, macro, auditor, events, bonds, and scraper relationships."""

    async def upsert_country(self, code: str, name: str) -> None:
        """Upsert a Country reference node."""
        await self._run(
            f"""
            MERGE (c:{NodeLabel.COUNTRY} {{{Prop.CODE}: $code}})
            SET c.{Prop.NAME} = $name
            """,
            {"code": code, "name": name},
        )

    async def upsert_macro_indicator(self, df: "pl.DataFrame") -> None:
        """Upsert macro indicators from a DataFrame."""
        for row in df.to_dicts():
            name = row.get(Prop.NAME, "")
            date_val = row.get(Prop.DATE, "")
            country = row.get(Prop.COUNTRY, "")
            source = row.get(Prop.SOURCE, "")
            value = row.get(Prop.VALUE)
            unit = row.get(Prop.UNIT, "")
            category = row.get(Prop.CATEGORY, "")
            frequency = row.get(Prop.FREQUENCY, "annual")

            if not name or not date_val or not country:
                continue

            try:
                d = date.fromisoformat(str(date_val)[:10])
                year = d.year
                month = d.month
                day = d.day
                quarter = (month - 1) // 3 + 1
            except (ValueError, TypeError):
                logger.debug("Skipping invalid date: %s", date_val)
                continue

            await self._run(
                f"""
                MERGE (m:{NodeLabel.MACRO_INDICATOR} {{
                    {Prop.NAME}: $name,
                    {Prop.DATE}: $date_val,
                    {Prop.COUNTRY}: $country,
                    {Prop.SOURCE}: $source
                }})
                SET m.{Prop.VALUE}    = $value,
                    m.{Prop.UNIT}     = $unit,
                    m.{Prop.CATEGORY} = $category,
                    m.{Prop.FREQUENCY} = $frequency

                WITH m
                MERGE (c:{NodeLabel.COUNTRY} {{{Prop.CODE}: $country}})
                ON CREATE SET c.{Prop.NAME} = $country_name
                MERGE (c)-[:{RelType.HAS_MACRO_INDICATOR}]->(m)

                WITH m
                MERGE (d:{NodeLabel.DATE} {{{Prop.DATE}: $date_val}})
                SET d.{Prop.YEAR}  = $year,
                    d.{Prop.MONTH} = $month,
                    d.{Prop.DAY}   = $day
                MERGE (q:{NodeLabel.QUARTER} {{
                    {Prop.YEAR}: $year, {Prop.QUARTER}: $quarter
                }})
                MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: $year}})
                MERGE (d)-[:{RelType.IN_QUARTER}]->(q)
                MERGE (q)-[:{RelType.IN_YEAR}]->(y)
                MERGE (m)-[:{RelType.MEASURED_ON}]->(d)
                """,
                {
                    "name": name,
                    "date_val": str(date_val)[:10],
                    "country": country,
                    "country_name": row.get("country_name", country),
                    "source": source,
                    "value": float(value) if value is not None else None,
                    "unit": unit,
                    "category": category,
                    "frequency": frequency,
                    "year": year,
                    "month": month,
                    "day": day,
                    "quarter": quarter,
                },
            )

    async def upsert_macro_sector_link(
        self,
        macro_name: str,
        sector_name: str,
        reason: str = "",
    ) -> None:
        """Link a macro indicator to a sector it affects."""
        await self._run(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR} {{{Prop.NAME}: $macro_name}})
            MATCH (s:{NodeLabel.SECTOR} {{{Prop.NAME}: $sector_name}})
            MERGE (m)-[r:{RelType.AFFECTS_SECTOR}]->(s)
            SET r.{Prop.REASON} = $reason
            """,
            {"macro_name": macro_name, "sector_name": sector_name, "reason": reason},
        )

    async def upsert_macro_industry_link(
        self,
        macro_name: str,
        industry_name: str,
        reason: str = "",
    ) -> None:
        """Link a macro indicator to an industry it affects."""
        await self._run(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR} {{{Prop.NAME}: $macro_name}})
            MATCH (i:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry_name}})
            MERGE (m)-[r:{RelType.AFFECTS_INDUSTRY}]->(i)
            SET r.{Prop.REASON} = $reason
            """,
            {
                "macro_name": macro_name,
                "industry_name": industry_name,
                "reason": reason,
            },
        )

    async def upsert_auditor(self, symbol: str, auditor_name: str) -> None:
        """Create AUDITED_BY edge from company to its audit firm."""
        if not auditor_name:
            return

        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", auditor_name.lower()).strip("_")
        safe_name = re.sub(r"_+", "_", safe_name)[:50]
        if not safe_name:
            return
        auditor_id = f"AUD_{safe_name}"

        await self._run(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $symbol }})
            MERGE (a:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $auditor_id }})
            ON CREATE SET a.{Prop.NAME} = $auditor_name,
                          a.company_type = 'audit_firm'
            MERGE (c)-[r:{RelType.AUDITED_BY}]->(a)
            SET r.{Prop.AUDITOR_NAME} = $auditor_name
            """,
            {
                "symbol": symbol,
                "auditor_id": auditor_id,
                "auditor_name": auditor_name,
            },
        )

    async def upsert_company_events(self, symbol: str, events_df: "pl.DataFrame") -> None:
        """Store latest corporate action dates as properties on the Company node."""
        if events_df.is_empty():
            return

        df = events_df
        rename: dict[str, str] = {}
        for col in df.columns:
            lower = col.lower()
            if lower == "event_code":
                rename[col] = "event_code"
            elif lower == "exright_date":
                rename[col] = "exright_date"
            elif lower == "public_date":
                rename[col] = "public_date"
            elif lower == "record_date":
                rename[col] = "record_date"
        if rename:
            df = df.rename(rename)

        if "event_code" not in df.columns:
            return

        date_col = None
        for col in ("exright_date", "public_date", "record_date"):
            if col in df.columns:
                date_col = col
                break

        if date_col is None:
            return

        latest: dict[str, str | None] = {
            "DIV": None,
            "ISS": None,
            "AGME": None,
        }
        for row in df.to_dicts():
            code = str(row.get("event_code", "")).strip().upper()
            if code not in latest:
                continue
            raw_date = row.get(date_col)
            if raw_date is None:
                continue
            raw_str = str(raw_date)[:10]
            current = latest[code]
            if current is None or raw_str > current:
                latest[code] = raw_str

        sets: list[str] = []
        params: dict[str, str] = {"symbol": symbol}
        for event_type, prop_name in [
            ("DIV", Prop.LAST_DIVIDEND_DATE),
            ("ISS", Prop.LAST_ISSUANCE_DATE),
            ("AGME", Prop.LAST_MEETING_DATE),
        ]:
            date_val = latest.get(event_type)
            if date_val:
                param_key = f"{event_type.lower()}_date"
                sets.append(f"SET c.{prop_name} = ${param_key}")
                params[param_key] = date_val

        if not sets:
            return

        sets_str = "\n".join(sets)
        await self._run(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $symbol }})
            {sets_str}
            """,
            params,
        )

    async def upsert_company_relationship(
        self,
        source_symbol: str,
        target_symbol: str,
        target_name: str,
        rel_type: str,
        *,
        stake_percent: float | None = None,
        amount: float | None = None,
        interest_rate: float | None = None,
        maturity_date: str | None = None,
        issue_date: str | None = None,
        issue_amount: float | None = None,
        transaction_date: str | None = None,
        description: str | None = None,
    ) -> None:
        """Create a generic Company → Company relationship (used by scrapers)."""
        if not source_symbol or not target_symbol:
            return

        params: dict[str, object] = {
            "source_symbol": source_symbol,
            "target_symbol": target_symbol,
            "target_name": target_name,
        }

        optional_props: dict[str, object] = {}
        if stake_percent is not None:
            optional_props[Prop.STAKE_PERCENT] = stake_percent
        if amount is not None:
            optional_props["amount"] = amount
        if interest_rate is not None:
            optional_props["interest_rate"] = interest_rate
        if maturity_date is not None:
            optional_props["maturity_date"] = maturity_date
        if issue_date is not None:
            optional_props["issue_date"] = issue_date
        if issue_amount is not None:
            optional_props["issue_amount"] = issue_amount
        if transaction_date is not None:
            optional_props["transaction_date"] = transaction_date
        if description is not None:
            optional_props["description"] = description

        if optional_props:
            set_clauses = ", ".join(f"r.{k} = ${k}" for k in optional_props)
            params.update(optional_props)
            set_str = f"SET {set_clauses}"
        else:
            set_str = ""

        await self._run(
            f"""
            MATCH (source:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $source_symbol }})
            MERGE (target:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $target_symbol }})
            ON CREATE SET target.{Prop.NAME} = $target_name
            MERGE (source)-[r:{rel_type}]->(target)
            {set_str}
            """,
            params,
        )

    async def upsert_bonds(self, df: "pl.DataFrame") -> int:
        """Upsert bond issuance data as Bond nodes linked to issuing companies."""
        if df is None or df.is_empty():
            return 0

        rows: list[dict] = []
        for row in df.to_dicts():
            issuer_symbol = row.get("issuer_symbol", "")
            bond_code = row.get("bond_code", "")
            if not issuer_symbol or not bond_code:
                continue

            bond_id = f"{issuer_symbol}_{bond_code}"
            rows.append(
                {
                    "bond_id": bond_id,
                    "issuer_symbol": issuer_symbol,
                    "bond_code": bond_code,
                    "issuer_name": row.get("issuer_name", ""),
                    "interest_rate": row.get("interest_rate"),
                    "maturity_date": row.get("maturity_date", ""),
                    "issue_date": row.get("issue_date", ""),
                    "issue_amount": row.get("issue_amount"),
                    "currency": row.get("currency", ""),
                    "status": row.get("status", ""),
                },
            )

        if not rows:
            return 0

        try:
            await self._run(
                f"""
                UNWIND $rows AS r
                MATCH (c:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: r.issuer_symbol }})
                MERGE (b:{NodeLabel.BOND} {{ id: r.bond_id }})
                SET b.bond_code    = r.bond_code,
                    b.issuer_symbol = r.issuer_symbol,
                    b.issuer_name   = r.issuer_name,
                    b.interest_rate  = r.interest_rate,
                    b.maturity_date  = r.maturity_date,
                    b.issue_date    = r.issue_date,
                    b.issue_amount  = r.issue_amount,
                    b.currency      = r.currency,
                    b.status       = r.status
                MERGE (c)-[:{RelType.HAS_BOND}]->(b)
                """,
                {"rows": rows},
            )
        except Exception:
            logger.exception("Failed to upsert bonds — skipping batch")
            return 0

        return len(rows)
