"""Officer, shareholder, and person node upsertion."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

from ourgraph.graph.builder._helpers import _DIACRITICS_TABLE, is_company_name, normalize_person_name, resolve_holder_symbol
from ourgraph.graph.builder.core import _GraphBuilderCore
from ourgraph.graph.schema import NodeLabel, Prop, RelType

logger = logging.getLogger(__name__)


class _PeopleMixin(_GraphBuilderCore):
    """Mixin providing officer, shareholder, and person methods."""

    async def upsert_officers(self, df: "pl.DataFrame", symbol: str) -> None:
        """Upsert officers as Person nodes with IS_OFFICER → Company edges."""
        if df is None or df.is_empty():
            return
        for row in df.to_dicts():
            name = row.get("name") or row.get("officer_name") or ""
            if not name:
                continue
            name = normalize_person_name(name)
            position = (
                row.get("position_en")
                or row.get("position")
                or row.get("officer_position")
                or ""
            )
            own_percent = float(
                row.get("officer_own_percent") or row.get("own_percent") or 0,
            )
            params = {
                "symbol": symbol,
                "person_name": name,
                "position": position,
                "own_percent": own_percent,
            }
            await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (p:{NodeLabel.PERSON} {{{Prop.PERSON_NAME}: $person_name}})
                MERGE (p)-[r:{RelType.IS_OFFICER}]->(c)
                SET r.{Prop.POSITION}    = $position,
                    r.{Prop.OWN_PERCENT} = $own_percent
                """,
                params,
            )

    async def upsert_officer_roles(self, df: "pl.DataFrame", symbol: str) -> None:
        """Create derived role relationships (IS_BOARD_MEMBER, IS_FOUNDER, IS_EXECUTIVE)."""
        if df is None or df.is_empty():
            return

        board_keywords = frozenset(
            {
                "chairman",
                "vice chairman",
                "vice chair",
                "chair",
                "board",
                "independent director",
                "non-executive",
                "member of the board",
                "board member",
                "director",
                "thanh vien hdqt",
                "thanh vien hoi dong quan tri",
                "chu tich hdqt",
                "chu tich hoi dong quan tri",
                "pho chu tich hdqt",
                "pho chu tich hoi dong quan tri",
                "chu tich",
            },
        )
        founder_keywords = frozenset(
            {
                "founder",
                "sang lap",
                "dong sang lap",
                "co-founder",
                "nguoi sang lap",
            },
        )
        executive_keywords = frozenset(
            {
                "ceo",
                "cfo",
                "coo",
                "cto",
                "cio",
                "cmo",
                "chro",
                "chief executive",
                "chief financial",
                "chief operating",
                "chief technology",
                "president",
                "general director",
                "managing director",
                "executive director",
                "tong giam doc",
                "giam doc",
                "pho tong giam doc",
                "giam doc dieu hanh",
                "giam doc tai chinh",
                "giam doc cong nghe",
                "giam doc kinh doanh",
            },
        )

        for row in df.to_dicts():
            name = row.get("name") or row.get("officer_name") or ""
            if not name:
                continue
            name = normalize_person_name(name)

            position = (
                row.get("position_en")
                or row.get("position")
                or row.get("officer_position")
                or ""
            ).lower()
            position_ascii = position.translate(_DIACRITICS_TABLE)

            role_types = [RelType.IS_OFFICER]

            if any(kw in position_ascii for kw in board_keywords):
                role_types.append(RelType.IS_BOARD_MEMBER)
            if any(kw in position_ascii for kw in founder_keywords):
                role_types.append(RelType.IS_FOUNDER)
            if any(kw in position_ascii for kw in executive_keywords):
                role_types.append(RelType.IS_EXECUTIVE)

            for role_type in role_types:
                params = {
                    "symbol": symbol,
                    "person_name": name,
                    "position": row.get("position_en")
                    or row.get("position")
                    or row.get("officer_position")
                    or "",
                }
                await self._run(
                    f"""
                    MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                    MATCH (p:{NodeLabel.PERSON} {{{Prop.PERSON_NAME}: $person_name}})
                    MERGE (p)-[r:{role_type}]->(c)
                    SET r.{Prop.POSITION} = $position
                    """,
                    params,
                )

    async def upsert_shareholders(
        self,
        df: "pl.DataFrame",
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        """Upsert shareholders as either Company or Person nodes."""
        if df is None or df.is_empty():
            return

        for row in df.to_dicts():
            await self._upsert_single_shareholder(row, symbol, name_to_symbol)

    async def _upsert_single_shareholder(
        self,
        row: dict,
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        """Process a single shareholder row."""
        holder_name = row.get("share_holder") or ""
        stake = float(row.get("share_own_percent") or 0)
        if not holder_name:
            return

        is_company = is_company_name(holder_name)
        if not is_company:
            holder_name = normalize_person_name(holder_name)

        holder_symbol = None
        if is_company:
            holder_symbol = resolve_holder_symbol(holder_name, name_to_symbol)

        if is_company and holder_symbol:
            await self._upsert_corporate_shareholder(symbol, holder_symbol, stake)
        elif is_company:
            await self._upsert_unknown_corporate_shareholder(symbol, holder_name, stake)
        else:
            await self._upsert_individual_shareholder(symbol, holder_name, stake)

    async def _upsert_corporate_shareholder(
        self,
        target_symbol: str,
        holder_symbol: str,
        stake: float,
    ) -> None:
        """Upsert a known corporate shareholder (Company→Company edge)."""
        params = {
            "target_symbol": target_symbol,
            "holder_symbol": holder_symbol,
            "stake_percent": stake,
        }
        await self._run(
            f"""
            MATCH (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $target_symbol}})
            MERGE (holder:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $holder_symbol}})
            ON CREATE SET holder.{Prop.NAME} = $holder_symbol,
                          holder.company_type = 'subsidiary'
            MERGE (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target)
            SET r.{Prop.STAKE_PERCENT} = $stake_percent
            """,
            params,
        )

    async def _upsert_unknown_corporate_shareholder(
        self,
        target_symbol: str,
        holder_name: str,
        stake: float,
    ) -> None:
        """Upsert an unknown corporate shareholder (keyed by NAME)."""
        normalized_name = " ".join(holder_name.split())
        params = {
            "target_symbol": target_symbol,
            "holder_name": normalized_name,
            "stake_percent": stake,
        }
        await self._run(
            f"""
            MATCH (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $target_symbol}})
            MERGE (holder:{NodeLabel.COMPANY} {{{Prop.NAME}: $holder_name}})
            ON CREATE SET holder.{Prop.SYMBOL} = $holder_name,
                          holder.company_type = 'subsidiary'
            MERGE (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target)
            SET r.{Prop.STAKE_PERCENT} = $stake_percent
            """,
            params,
        )

    async def _upsert_individual_shareholder(
        self,
        target_symbol: str,
        holder_name: str,
        stake: float,
    ) -> None:
        """Upsert an individual shareholder (Person node)."""
        params = {
            "target_symbol": target_symbol,
            "holder_name": holder_name,
            "stake_percent": stake,
        }
        await self._run(
            f"""
            MATCH (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $target_symbol}})
            MERGE (holder:{NodeLabel.PERSON} {{{Prop.PERSON_NAME}: $holder_name}})
            MERGE (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target)
            SET r.{Prop.STAKE_PERCENT} = $stake_percent
            """,
            params,
        )
