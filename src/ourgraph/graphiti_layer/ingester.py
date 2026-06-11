"""Graphiti episode ingester.

Converts the structured FalkorDB knowledge graph into natural-language text
episodes and feeds them to Graphiti for LLM-queryable temporal memory.

Why text episodes (not JSON):
  - phi3.5 and other small local models handle structured-output extraction
    from JSON poorly and inconsistently.
  - Text episodes let us craft precise relationship sentences that encode
    the cross-ticker relationships we care about (ownership chains,
    sector groupings, conglomerate linkages).

Episode design:
  One episode per company — compact, relationship-dense, <400 words.
  Additional cross-company episodes for:
    - Sector peer groups (all steel companies, all banks, etc.)
    - Conglomerate maps (parent → all subsidiaries in one episode)
    - Shared insider maps (person who sits on multiple boards)

After this ingester runs, `ourgraph query "What are HPG's subsidiaries?"`
will return actual results.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from graphiti_core.nodes import EpisodeType

from ourgraph.constants import EPISODE_MAX_WORDS
from ourgraph.graph.schema import NodeLabel, Prop, RelType
from ourgraph.graphiti_layer.client import build_graphiti_client

if TYPE_CHECKING:
    from falkordb.asyncio import FalkorDB
    from graphiti_core import Graphiti

    from ourgraph.config import AppSettings

logger = logging.getLogger(__name__)


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "unknown"
    return f"{v:.1f}%"


class GraphitiIngester:
    """Reads the raw FalkorDB graph and feeds episodes to Graphiti.

    Usage::

        ingester = await GraphitiIngester.create(settings)
        await ingester.ingest_all()
        await ingester.close()
    """

    def __init__(
        self,
        graphiti: Graphiti,
        raw_client: FalkorDB,
        raw_graph_name: str,
        group_id: str,
    ) -> None:
        self._graphiti = graphiti
        self._raw_client = raw_client
        self._raw_graph_name = raw_graph_name
        self._group_id = group_id

    @classmethod
    async def create(cls, settings: AppSettings) -> GraphitiIngester:
        from ourgraph.db.falkordb import build_falkordb_client
        from ourgraph.graphiti_layer.client import GRAPHITI_GRAPH_SUFFIX

        graphiti = build_graphiti_client(settings)
        await graphiti.build_indices_and_constraints()

        raw_client = build_falkordb_client(settings.falkordb)
        group_id = settings.falkordb.graph_name + GRAPHITI_GRAPH_SUFFIX

        return cls(
            graphiti=graphiti,
            raw_client=raw_client,
            raw_graph_name=settings.falkordb.graph_name,
            group_id=group_id,
        )

    async def _raw_query(self, cypher: str, params: dict | None = None) -> list:
        g = self._raw_client.select_graph(self._raw_graph_name)
        result = await g.ro_query(cypher, params or {})
        return result.result_set

    # ------------------------------------------------------------------
    # Top-level entry points
    # ------------------------------------------------------------------

    async def ingest_all(self, symbols: list[str] | None = None) -> None:
        """Ingest all companies and cross-company relationship episodes."""
        # Check Ollama connectivity and model availability before starting
        try:
            from ourgraph.config import get_settings

            settings = get_settings()
            ollama_base = settings.ollama.base_url.rstrip("/")
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{ollama_base}/api/tags", timeout=5)
                resp.raise_for_status()
                data = resp.json()
                model_names = [m.get("name", "") for m in data.get("models", [])]
                llm_model = settings.ollama.llm_model
                embed_model = settings.ollama.embedding_model
                if llm_model not in model_names:
                    logger.error(
                        "Ollama model '%s' not found. Pull it with: ollama pull %s",
                        llm_model,
                        llm_model,
                    )
                    return
                if embed_model not in model_names:
                    logger.error(
                        "Ollama embedding model '%s' not found. "
                        "Pull it with: ollama pull %s",
                        embed_model,
                        embed_model,
                    )
                    return
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Cannot connect to Ollama at %s. "
                "Please start Ollama first: `ollama serve` or `docker start ollama`. "
                "Error: %s",
                settings.ollama.base_url if "settings" in locals() else "(unknown)",
                exc,
            )
            return

        logger.info("Graphiti ingestion starting...")

        all_symbols = await self._get_all_company_symbols()
        if symbols:
            all_symbols = [s for s in all_symbols if s in symbols]

        logger.info("Ingesting %d company episodes...", len(all_symbols))
        for symbol in all_symbols:
            try:
                await self._ingest_company_episode(symbol)
            except Exception:
                logger.exception("Failed to ingest episode for %s", symbol)

        logger.info("Ingesting sector group episodes...")
        await self._ingest_sector_group_episodes()

        logger.info("Ingesting conglomerate episodes...")
        await self._ingest_conglomerate_episodes()

        logger.info("Ingesting shared insider episodes...")
        await self._ingest_shared_insider_episodes()

        logger.info("Ingesting macro indicator episodes...")
        await self._ingest_macro_episodes()

        logger.info("Graphiti ingestion complete.")

    # ------------------------------------------------------------------
    # Company-level episode
    # ------------------------------------------------------------------

    async def _ingest_company_episode(self, symbol: str) -> None:
        """Build one episode per company encoding all its key relationships."""
        company = await self._get_company(symbol)
        if not company:
            return

        name = company.get("name") or symbol
        exchange = company.get("exchange") or "HOSE"
        industry = await self._get_company_industry(symbol)
        sector = await self._get_company_sector(symbol)
        market_cap = company.get("market_cap")
        employees = company.get("no_employees")

        parts: list[str] = []

        # Identity
        mc_str = f" with a market cap of {market_cap:,} VND" if market_cap else ""
        emp_str = f" and approximately {employees:,} employees" if employees else ""
        parts.append(
            f"{symbol} ({name}) is a Vietnamese company listed on {exchange}{mc_str}{emp_str}.",
        )

        if industry:
            parts.append(f"It operates in the {industry} industry.")
        if sector and sector != industry:
            parts.append(f"Its broader sector is {sector}.")

        # Sector peers
        peers = await self._get_sector_peers(symbol)
        if peers:
            peer_list = ", ".join(peers[:10])
            parts.append(
                f"{symbol} competes directly with: {peer_list}.",
            )
            parts.append(
                f"A significant change in {symbol}'s stock price may influence "
                f"investor sentiment toward its sector peers: {peer_list}.",
            )

        # Subsidiaries
        subs = await self._get_subsidiaries(symbol)
        if subs:
            sub_parts = [
                f"{s['sub_symbol']} ({s['sub_name']}, {_fmt_pct(s['ownership_pct'])} owned)"
                for s in subs[:8]
            ]
            parts.append(
                f"{symbol} directly controls the following subsidiaries: {', '.join(sub_parts)}. "
                f"Financial performance of {symbol} directly impacts these entities.",
            )

        # Parent companies (who owns this company?)
        parents = await self._get_parent_companies(symbol)
        if parents:
            parent_parts = [
                f"{p['parent_symbol']} ({_fmt_pct(p['ownership_pct'])})"
                for p in parents[:5]
            ]
            parts.append(
                f"{symbol} is a subsidiary of: {', '.join(parent_parts)}. "
                f"Its performance affects the consolidated financials of these parent companies.",
            )

        # Corporate shareholders (institutional)
        corp_holders = await self._get_corporate_shareholders(symbol)
        if corp_holders:
            holder_parts = [
                f"{h['holder_name']} ({_fmt_pct(h['stake_pct'])})"
                for h in corp_holders[:6]
            ]
            parts.append(
                f"Major institutional shareholders of {symbol}: {', '.join(holder_parts)}.",
            )

        # Individual insider shareholders
        person_holders = await self._get_person_shareholders(symbol)
        if person_holders:
            person_parts = [
                f"{p['person_name']} ({_fmt_pct(p['stake_pct'])})"
                for p in person_holders[:5]
            ]
            parts.append(
                f"Individual insider shareholders of {symbol}: {', '.join(person_parts)}.",
            )

        # Officers
        officers = await self._get_officers(symbol)
        if officers:
            off_parts = [
                f"{o['person_name']} ({o['position']})"
                for o in officers[:6]
                if o.get("position")
            ]
            if off_parts:
                parts.append(f"Key executives of {symbol}: {', '.join(off_parts)}.")

        # Financial indicators (latest quarter)
        indicators = await self._get_latest_indicators(symbol)
        if indicators:
            parts_list = []
            per = indicators.get("per")
            if per:
                parts_list.append(f"P/E of {per:.1f}")
            roe = indicators.get("roe")
            if roe is not None:
                parts_list.append(f"ROE of {roe:.1f}%")
            roa = indicators.get("roa")
            if roa is not None:
                parts_list.append(f"ROA of {roa:.1f}%")
            de = indicators.get("debt_to_equity")
            if de is not None:
                parts_list.append(f"debt-to-equity of {de:.2f}")
            cr = indicators.get("current_ratio")
            if cr is not None:
                parts_list.append(f"current ratio of {cr:.2f}")
            gm = indicators.get("gross_margin")
            if gm is not None:
                parts_list.append(f"gross margin of {gm:.1f}%")
            nm = indicators.get("net_margin")
            if nm is not None:
                parts_list.append(f"net margin of {nm:.1f}%")
            rg = indicators.get("revenue_growth")
            if rg is not None:
                sign = "+" if rg > 0 else ""
                parts_list.append(f"revenue growth of {sign}{rg:.1f}%")
            dy = indicators.get("dividend_yield")
            if dy is not None:
                parts_list.append(f"dividend yield of {dy:.2f}%")

            if parts_list:
                period = f"Q{indicators.get('quarter', '')} {indicators.get('year', '')}".strip()
                period_str = f" ({period})" if period else ""
                parts.append(
                    f"{symbol}'s key financial indicators{period_str}: "
                    f"{', '.join(parts_list)}.",
                )

        # Price summary
        price_parts = []
        if company.get("price_current"):
            price_parts.append(f"currently at {company.get('price_current'):,.0f} VND")
        if company.get("price_52w_high"):
            price_parts.append(f"52-week high of {company.get('price_52w_high'):,.0f}")
        if company.get("price_52w_low"):
            price_parts.append(f"52-week low of {company.get('price_52w_low'):,.0f}")
        if company.get("price_min"):
            price_parts.append(f"all-time low of {company.get('price_min'):,.0f}")
        if company.get("price_max"):
            price_parts.append(f"all-time high of {company.get('price_max'):,.0f}")
        if company.get("price_avg") is not None:
            price_parts.append(f"average price of {company.get('price_avg'):,.0f}")
        if company.get("price_median") is not None:
            price_parts.append(f"median price of {company.get('price_median'):,.0f}")
        if company.get("volatility_90d") is not None:
            price_parts.append(
                f"90-day volatility of {float(company['volatility_90d']) * 100:.1f}%",
            )
        ret_1m = company.get("return_1m")
        if ret_1m is not None:
            sign = "+" if ret_1m > 0 else ""
            price_parts.append(f"1-month return of {sign}{ret_1m:.1f}%")
        ret_1y = company.get("return_1y")
        if ret_1y is not None:
            sign = "+" if ret_1y > 0 else ""
            price_parts.append(f"1-year return of {sign}{ret_1y:.1f}%")
        if price_parts:
            parts.append(f"Stock price summary: {', '.join(price_parts)}.")

        # Cross-shareholding hint
        cross = await self._get_cross_shareholding(symbol)
        if cross:
            cross_parts = [f"{c['other_symbol']} (mutual stake)" for c in cross[:5]]
            parts.append(
                f"{symbol} has cross-shareholding relationships with: {', '.join(cross_parts)}. "
                f"These companies have mutual financial interests and their stock prices tend to correlate.",
            )

        episode_body = " ".join(parts)

        # Guard against oversized episodes
        words = episode_body.split()
        if len(words) > EPISODE_MAX_WORDS:
            episode_body = " ".join(words[:EPISODE_MAX_WORDS]) + "..."

        await self._graphiti.add_episode(
            name=f"company_{symbol}",
            episode_body=episode_body,
            source=EpisodeType.text,
            source_description="VNIndex knowledge graph — company profile",
            reference_time=datetime.now(UTC),
            group_id=self._group_id,
        )
        logger.debug(
            "Ingested episode for %s (%d words)",
            symbol,
            min(len(words), EPISODE_MAX_WORDS),
        )

    # ------------------------------------------------------------------
    # Sector group episodes
    # ------------------------------------------------------------------

    async def _ingest_sector_group_episodes(self) -> None:
        """One episode per sector listing all member companies.

        This is the key episode for cross-ticker correlation reasoning:
        an LLM seeing "HPG, NKG, TIS, POM all operate in Steel Manufacturing"
        can infer that a shock to one may propagate to others.
        """
        rows = await self._raw_query(
            f"""
            MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
            RETURN ind.{Prop.NAME} AS industry, collect(c.{Prop.SYMBOL}) AS symbols
            ORDER BY size(symbols) DESC
            """,
        )
        # Fetch macro-to-industry links for context
        macro_links = await self._raw_query(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR})-[r:{RelType.AFFECTS_INDUSTRY}]->(i:{NodeLabel.INDUSTRY})
            WHERE m.{Prop.VALUE} IS NOT NULL
            RETURN i.{Prop.NAME} AS industry, m.{Prop.NAME} AS indicator,
                   m.{Prop.VALUE} AS value, m.{Prop.UNIT} AS unit,
                   m.{Prop.DATE} AS date
            ORDER BY m.{Prop.DATE} DESC
            """,
        )
        # Group macro links by industry
        from collections import defaultdict

        macro_by_industry: dict[str, list[dict]] = defaultdict(list)
        for row in macro_links:
            if row[0] and row[1] and row[2] is not None:
                macro_by_industry[row[0]].append(
                    {
                        "indicator": row[1],
                        "value": row[2],
                        "unit": row[3] or "",
                    },
                )

        for row in rows:
            industry = row[0]
            symbols: list[str] = row[1] or []
            if not industry or len(symbols) < 2:
                continue

            symbol_list = ", ".join(symbols[:30])
            body_parts = [
                f"The following Vietnamese companies all operate in the {industry} industry "
                f"and are listed on VNIndex: {symbol_list}. "
                f"Because they share the same industry, macroeconomic events, regulatory changes, "
                f"or demand shocks affecting one company typically impact all companies in this group. "
                f"A significant stock price movement in one of these companies is often a leading "
                f"indicator for the others.",
            ]

            # Add relevant macro indicators for this industry
            if industry in macro_by_industry:
                macro_parts = []
                for m in macro_by_industry[industry][:5]:
                    unit_str = f" {m['unit']}" if m["unit"] else ""
                    macro_parts.append(
                        f"{m['indicator']} is {m['value']:.2f}{unit_str}",
                    )
                if macro_parts:
                    body_parts.append(
                        f"Key macro indicators affecting {industry}: {', '.join(macro_parts)}.",
                    )

            body = " ".join(body_parts)

            words = body.split()
            if len(words) > EPISODE_MAX_WORDS:
                body = " ".join(words[:EPISODE_MAX_WORDS]) + "..."

            await self._graphiti.add_episode(
                name=f"sector_{industry.replace(' ', '_').lower()[:60]}",
                episode_body=body,
                source=EpisodeType.text,
                source_description="VNIndex knowledge graph — sector grouping",
                reference_time=datetime.now(UTC),
                group_id=self._group_id,
            )
            logger.debug(
                "Ingested sector episode: %s (%d companies)",
                industry,
                len(symbols),
            )

    # ------------------------------------------------------------------
    # Conglomerate episodes
    # ------------------------------------------------------------------

    async def _ingest_conglomerate_episodes(self) -> None:
        """One episode per parent company that owns 3+ subsidiaries.

        Encodes the conglomerate structure so the LLM understands that
        performance of the parent drives performance of the children and vice versa.
        """
        rows = await self._raw_query(
            f"""
            MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY})
            WITH parent, collect({{
                symbol: child.{Prop.SYMBOL},
                name: child.{Prop.NAME},
                pct: r.{Prop.OWNERSHIP_PERCENT}
            }}) AS subs
            WHERE size(subs) >= 3
            RETURN parent.{Prop.SYMBOL}, parent.{Prop.NAME}, subs
            ORDER BY size(subs) DESC
            """,
        )
        for row in rows:
            parent_symbol = row[0]
            parent_name = row[1] or parent_symbol
            subs = row[2] or []

            sub_parts = [
                f"{s.get('symbol', '?')} ({s.get('name', '?')}, {_fmt_pct(s.get('pct'))} owned)"
                for s in subs[:12]
            ]
            body = (
                f"{parent_symbol} ({parent_name}) is a conglomerate that controls "
                f"the following subsidiaries: {', '.join(sub_parts)}. "
                f"The financial health of {parent_symbol} directly affects all these subsidiaries. "
                f"Conversely, poor performance in any major subsidiary will negatively impact "
                f"{parent_symbol}'s consolidated earnings and stock price."
            )

            words = body.split()
            if len(words) > EPISODE_MAX_WORDS:
                body = " ".join(words[:EPISODE_MAX_WORDS]) + "..."

            await self._graphiti.add_episode(
                name=f"conglomerate_{parent_symbol}",
                episode_body=body,
                source=EpisodeType.text,
                source_description="VNIndex knowledge graph — conglomerate structure",
                reference_time=datetime.now(UTC),
                group_id=self._group_id,
            )

    # ------------------------------------------------------------------
    # Shared insider episodes
    # ------------------------------------------------------------------

    async def _ingest_shared_insider_episodes(self) -> None:
        """Episodes for people who sit on boards or hold stakes across multiple companies.

        This is the hidden influence network. A person chairing two competing
        companies' boards creates an implicit link between those companies.
        """
        rows = await self._raw_query(
            f"""
            MATCH (p:{NodeLabel.PERSON})-[r:{RelType.IS_OFFICER}|{RelType.HOLDS_STAKE_IN}]->(c:{NodeLabel.COMPANY})
            WITH p.{Prop.PERSON_NAME} AS person, collect(DISTINCT c.{Prop.SYMBOL}) AS companies
            WHERE size(companies) > 1
            RETURN person, companies
            ORDER BY size(companies) DESC
            LIMIT 100
            """,
        )
        for row in rows:
            person = row[0]
            companies: list[str] = row[1] or []
            if not person or len(companies) < 2:
                continue

            company_list = ", ".join(companies[:10])
            body = (
                f"{person} has insider roles (as officer or significant shareholder) "
                f"at multiple VNIndex companies: {company_list}. "
                f"This creates an implicit link between these companies — "
                f"decisions by {person} or events affecting their holdings may "
                f"simultaneously affect the stock prices of all these companies."
            )

            safe_name = person.replace(" ", "_").lower()[:50]
            await self._graphiti.add_episode(
                name=f"insider_{safe_name}",
                episode_body=body,
                source=EpisodeType.text,
                source_description="VNIndex knowledge graph — shared insider network",
                reference_time=datetime.now(UTC),
                group_id=self._group_id,
            )

    # ------------------------------------------------------------------
    # Macro indicator episodes
    # ------------------------------------------------------------------

    async def _ingest_macro_episodes(self) -> None:
        """Create text episodes from macro indicators for LLM queries.

        Episodes are grouped by category or country so that each episode
        contains a coherent set of related macro indicators.
        """
        # Get all macro indicators grouped by category
        rows = await self._raw_query(
            f"""
            MATCH (m:{NodeLabel.MACRO_INDICATOR})
            RETURN m.{Prop.CATEGORY} AS category,
                   m.{Prop.COUNTRY}   AS country,
                   m.{Prop.NAME}       AS name,
                   m.{Prop.VALUE}      AS value,
                   m.{Prop.UNIT}       AS unit,
                   m.{Prop.DATE}       AS date,
                   m.{Prop.FREQUENCY}  AS frequency
            ORDER BY m.{Prop.CATEGORY}, m.{Prop.DATE} DESC
            """,
        )
        if not rows:
            logger.info("No macro indicators found for episodes.")
            return

        # Group by category
        from collections import defaultdict

        by_category: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            cat = row[0] or "unknown"
            by_category[cat].append(
                {
                    "country": row[1],
                    "name": row[2],
                    "value": row[3],
                    "unit": row[4],
                    "date": str(row[5])[:10] if row[5] else "",
                    "frequency": row[6] or "annual",
                },
            )

        for category, indicators in by_category.items():
            parts: list[str] = [
                f"The following macro economic indicators are available for {category}:",
            ]
            # Take latest 20 indicators per category
            for ind in indicators[:20]:
                if ind["value"] is None:
                    continue
                date_str = ind["date"] or "unknown date"
                parts.append(
                    f"On {date_str}, {ind['name']} was {ind['value']:.2f} {ind['unit']} "
                    f"(frequency: {ind['frequency']}, country: {ind['country']}).",
                )

            body = " ".join(parts)
            words = body.split()
            if len(words) > EPISODE_MAX_WORDS:
                body = " ".join(words[:EPISODE_MAX_WORDS]) + "..."

            safe_cat = category.replace(" ", "_").lower()[:60]
            await self._graphiti.add_episode(
                name=f"macro_{safe_cat}",
                episode_body=body,
                source=EpisodeType.text,
                source_description="Macro economic indicators — {category}",
                reference_time=datetime.now(UTC),
                group_id=self._group_id,
            )
            logger.debug(
                "Ingested macro episode for category: %s (%d indicators)",
                category,
                min(len(indicators), 20),
            )

    # ------------------------------------------------------------------
    # Raw graph query helpers
    # ------------------------------------------------------------------

    async def _get_all_company_symbols(self) -> list[str]:
        rows = await self._raw_query(
            f"MATCH (c:{NodeLabel.COMPANY}) WHERE c.{Prop.SYMBOL} IS NOT NULL RETURN c.{Prop.SYMBOL}",
        )
        return [r[0] for r in rows if r[0]]

    async def _get_company(self, symbol: str) -> dict | None:
        rows = await self._raw_query(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN c.{Prop.NAME}, c.{Prop.EXCHANGE}, c.{Prop.MARKET_CAP}, c.{Prop.NO_EMPLOYEES},
                   c.{Prop.PRICE_CURRENT}, c.{Prop.PRICE_52W_HIGH}, c.{Prop.PRICE_52W_LOW},
                   c.{Prop.VOLATILITY_90D}, c.{Prop.AVG_VOLUME_30D},
                   c.{Prop.RETURN_1M}, c.{Prop.RETURN_3M}, c.{Prop.RETURN_1Y},
                   c.{Prop.PRICE_MIN}, c.{Prop.PRICE_MAX}, c.{Prop.PRICE_AVG}, c.{Prop.PRICE_MEDIAN}
            """,
            {"symbol": symbol},
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "name": r[0],
            "exchange": r[1],
            "market_cap": r[2],
            "no_employees": r[3],
            "price_current": r[4],
            "price_52w_high": r[5],
            "price_52w_low": r[6],
            "volatility_90d": r[7],
            "avg_volume_30d": r[8],
            "return_1m": r[9],
            "return_3m": r[10],
            "return_1y": r[11],
            "price_min": r[12],
            "price_max": r[13],
            "price_avg": r[14],
            "price_median": r[15],
        }

    async def _get_latest_indicators(self, symbol: str) -> dict[str, float | None]:
        """Return most recent indicator values for a company."""
        rows = await self._raw_query(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.HAS_INDICATOR}]->(i:{NodeLabel.INDICATOR})
            WHERE i.{Prop.PER} IS NOT NULL
            RETURN i.{Prop.PER}, i.{Prop.ROE}, i.{Prop.ROA},
                   i.{Prop.DEBT_TO_EQUITY}, i.{Prop.CURRENT_RATIO},
                   i.{Prop.GROSS_MARGIN}, i.{Prop.NET_MARGIN},
                   i.{Prop.REVENUE_GROWTH}, i.{Prop.DIVIDEND_YIELD},
                   i.{Prop.YEAR}, i.{Prop.QUARTER}
            ORDER BY i.{Prop.YEAR} DESC, i.{Prop.QUARTER} DESC
            LIMIT 1
            """,
            {"symbol": symbol},
        )
        if not rows:
            return {}
        r = rows[0]
        return {
            "per": r[0],
            "roe": r[1],
            "roa": r[2],
            "debt_to_equity": r[3],
            "current_ratio": r[4],
            "gross_margin": r[5],
            "net_margin": r[6],
            "revenue_growth": r[7],
            "dividend_yield": r[8],
            "year": r[9],
            "quarter": r[10],
        }

    async def _get_company_industry(self, symbol: str) -> str | None:
        rows = await self._raw_query(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
            RETURN ind.{Prop.NAME} LIMIT 1
            """,
            {"symbol": symbol},
        )
        return rows[0][0] if rows else None

    async def _get_company_sector(self, symbol: str) -> str | None:
        rows = await self._raw_query(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.BELONGS_TO}]->(s:{NodeLabel.SECTOR})
            RETURN s.{Prop.NAME} LIMIT 1
            """,
            {"symbol": symbol},
        )
        return rows[0][0] if rows else None

    async def _get_sector_peers(self, symbol: str) -> list[str]:
        rows = await self._raw_query(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.COMPETES_WITH}]-(peer:{NodeLabel.COMPANY})
            WHERE peer.{Prop.SYMBOL} <> $symbol
            RETURN peer.{Prop.SYMBOL}
            LIMIT 15
            """,
            {"symbol": symbol},
        )
        return [r[0] for r in rows if r[0]]

    async def _get_subsidiaries(self, symbol: str) -> list[dict]:
        rows = await self._raw_query(
            f"""
            MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->
                  (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN child.{Prop.SYMBOL}, child.{Prop.NAME}, r.{Prop.OWNERSHIP_PERCENT}
            ORDER BY r.{Prop.OWNERSHIP_PERCENT} DESC
            LIMIT 10
            """,
            {"symbol": symbol},
        )
        return [
            {"sub_symbol": r[0], "sub_name": r[1], "ownership_pct": r[2]} for r in rows
        ]

    async def _get_parent_companies(self, symbol: str) -> list[dict]:
        rows = await self._raw_query(
            f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY})
            RETURN parent.{Prop.SYMBOL}, r.{Prop.OWNERSHIP_PERCENT}
            ORDER BY r.{Prop.OWNERSHIP_PERCENT} DESC
            LIMIT 5
            """,
            {"symbol": symbol},
        )
        return [{"parent_symbol": r[0], "ownership_pct": r[1]} for r in rows]

    async def _get_corporate_shareholders(self, symbol: str) -> list[dict]:
        rows = await self._raw_query(
            f"""
            MATCH (holder:{NodeLabel.COMPANY})-[r:{RelType.HOLDS_STAKE_IN}]->
                  (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN holder.{Prop.NAME}, holder.{Prop.SYMBOL}, r.{Prop.STAKE_PERCENT}
            ORDER BY r.{Prop.STAKE_PERCENT} DESC
            LIMIT 8
            """,
            {"symbol": symbol},
        )
        return [
            {"holder_name": r[0] or r[1], "holder_symbol": r[1], "stake_pct": r[2]}
            for r in rows
        ]

    async def _get_person_shareholders(self, symbol: str) -> list[dict]:
        rows = await self._raw_query(
            f"""
            MATCH (p:{NodeLabel.PERSON})-[r:{RelType.HOLDS_STAKE_IN}]->
                  (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN p.{Prop.PERSON_NAME}, r.{Prop.STAKE_PERCENT}
            ORDER BY r.{Prop.STAKE_PERCENT} DESC
            LIMIT 6
            """,
            {"symbol": symbol},
        )
        return [{"person_name": r[0], "stake_pct": r[1]} for r in rows]

    async def _get_officers(self, symbol: str) -> list[dict]:
        rows = await self._raw_query(
            f"""
            MATCH (p:{NodeLabel.PERSON})-[r:{RelType.IS_OFFICER}]->
                  (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN p.{Prop.PERSON_NAME}, r.{Prop.POSITION}
            LIMIT 8
            """,
            {"symbol": symbol},
        )
        return [{"person_name": r[0], "position": r[1]} for r in rows]

    async def _get_cross_shareholding(self, symbol: str) -> list[dict]:
        rows = await self._raw_query(
            f"""
            MATCH (a:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.HOLDS_STAKE_IN}]->(b:{NodeLabel.COMPANY})
                  -[:{RelType.HOLDS_STAKE_IN}]->(a)
            RETURN b.{Prop.SYMBOL}
            LIMIT 5
            """,
            {"symbol": symbol},
        )
        return [{"other_symbol": r[0]} for r in rows]

    async def close(self) -> None:
        import contextlib
        import inspect

        with contextlib.suppress(Exception):
            await self._graphiti.close()

        with contextlib.suppress(Exception):
            close = getattr(self._raw_client, "close", None)
            if callable(close):
                maybe_awaitable = close()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
