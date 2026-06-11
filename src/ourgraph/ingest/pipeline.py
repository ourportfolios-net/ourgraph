"""Main ETL pipeline.

Orchestrates the full flow:
  1. Discover symbols — VNIndex (HOSE + HNX) via vnstock
  2. For each symbol (in batches):
     a. Fetch company overview → upsert Company + Sector/Industry nodes
     b. Fetch price history → upsert StockPrice nodes
     c. Fetch financial statements → upsert FinancialStatement nodes
     d. Fetch ratios → upsert FinancialIndicator nodes
     e. Fetch officers → upsert Person + IS_OFFICER edges
     f. Fetch subsidiaries → upsert SUBSIDIARY_OF edges
     g. Fetch shareholders → upsert Person/Company + HOLDS_STAKE_IN edges
  3. Feed Graphiti with natural-language episodes from the raw graph
     so that LLM queries return actual results.

Design:
  - Fully async: FalkorDB writes are awaited sequentially to respect API limits.
  - Batch + delay: avoids vnstock rate limits.
  - Idempotent: all writes use MERGE — safe to re-run.
  - Graphiti ingestion is a separate step run after the raw graph is complete.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import polars as pl

from ourgraph.graph.builder import GraphBuilder
from ourgraph.graph.schema import NodeLabel, Prop, RelType
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher

if TYPE_CHECKING:
    from collections.abc import Callable

    from ourgraph.config import AppSettings

# Import macro fetchers conditionally to avoid hard dependencies
try:
    from ourgraph.ingest.worldbank_fetcher import WorldBankFetcher

    _HAVE_WB = True
except ImportError:
    _HAVE_WB = False

try:
    from ourgraph.ingest.imf_fetcher import IMFFetcher

    _HAVE_IMF = True
except ImportError:
    _HAVE_IMF = False

try:
    from ourgraph.ingest.yfinance_fetcher import YFinanceFetcher

    _HAVE_YF = True
except ImportError:
    _HAVE_YF = False

try:
    from ourgraph.ingest.vnstock_macro_fetcher import VnstockMacroFetcher

    _HAVE_VN_MACRO = True
except ImportError:
    _HAVE_VN_MACRO = False

try:
    from ourgraph.ingest.kbs_fetcher import KbsFetcher

    _HAVE_KBS = True
except ImportError:
    _HAVE_KBS = False

if TYPE_CHECKING:
    from ourgraph.config import AppSettings

logger = logging.getLogger(__name__)


class Pipeline:
    """Full ETL pipeline from vnstock to FalkorDB + Graphiti knowledge graph."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        on_symbol_done: Callable[[str, str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._vnstock = VnstockFetcher(settings.vnstock)
        self._macro_settings = settings.macro
        self._on_symbol_done = on_symbol_done

        # Initialize macro fetchers based on availability
        self._wb_fetcher = None
        self._imf_fetcher = None
        self._yf_fetcher = None
        self._vn_macro_fetcher = None

        if _HAVE_WB and "worldbank" in settings.macro.sources:
            self._wb_fetcher = WorldBankFetcher(
                start_year=settings.macro.start_year,
                indicator_codes=settings.macro.worldbank_vn_indicators.split(","),
            )
        if _HAVE_IMF and "imf" in settings.macro.sources:
            self._imf_fetcher = IMFFetcher(
                start_year=settings.macro.start_year,
                indicator_codes=settings.macro.imf_vn_indicators.split(","),
            )
        if _HAVE_YF and "yfinance" in settings.macro.sources:
            self._yf_fetcher = YFinanceFetcher(
                tickers=settings.macro.yfinance_commodities.split(",")
                + settings.macro.yfinance_indices.split(","),
                start_year=settings.macro.start_year,
            )
        if _HAVE_VN_MACRO and "vnstock" in settings.macro.sources:
            self._vn_macro_fetcher = VnstockMacroFetcher(
                start_year=settings.macro.start_year,
            )

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def run_full(
        self,
        symbols: list[str] | None = None,
        *,
        resume: bool = False,
        industries: list[str] | None = None,
    ) -> None:
        """Run the full pipeline: raw graph + Graphiti ingestion.

        If resume=True, skip symbols that already have a Company node in the
        graph and only ingest the remaining ones.

        If industries is provided (e.g. ["Banking", "Steel"]), only ingest
        companies belonging to those industries. The pipeline first fetches
        all company overviews, then filters to the specified industries
        for per-symbol data (officers, shareholders, etc.).
        """
        if symbols is None:
            symbols = await self._resolve_symbols()

        if resume:
            symbols = await self._filter_uningested(symbols)
            if not symbols:
                logger.info("All symbols already ingested — nothing to resume")
                return
            logger.info(
                "Resuming pipeline — %d symbols remaining (%d already in graph)",
                len(symbols),
                len(symbols),
            )

        logger.info("Pipeline starting — %d symbols", len(symbols))

        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            await builder.ensure_indices()
            # Always fetch company overviews to build the industry graph
            await self._ingest_companies(builder, symbols)
            name_to_symbol = await self._build_name_to_symbol_map(builder)

            # Filter to target industries if specified
            if industries:
                symbols = await self._filter_by_industries(builder, industries)
                if not symbols:
                    logger.warning(
                        "No symbols found matching industries: %s — "
                        "falling back to all symbols",
                        industries,
                    )
                    symbols = await self._resolve_symbols()

            await self._ingest_per_symbol(builder, symbols, name_to_symbol)
            # Deduplicate nodes before generating COMPETES_WITH edges
            dedupe_stats = await builder.deduplicate_nodes()  # type: ignore[attr-defined]
            logger.info("Pre-competition deduplication: %s", dedupe_stats)
            # Generate COMPETES_WITH edges after all company data is ingested
            await builder.upsert_competes_with()

            # Ingest macro indicators and link them to sectors/industries
            macro_results = await self.run_macro_ingestion()
            logger.info("Macro ingestion results: %s", macro_results)

            # Run hidden relationship discovery
            try:
                from ourgraph.graph.discovery import GraphDiscovery
                from ourgraph.graph.queries import GraphQueries

                async with GraphQueries.from_settings(
                    self._settings.falkordb,
                ) as queries:
                    discovery = GraphDiscovery(queries)
                    discovered = await discovery.discover_all()
                    total_discovered = sum(
                        len(v) if isinstance(v, list) else 0
                        for v in discovered.values()
                    )
                    logger.info(
                        "Discovered %d hidden relationships across %d categories",
                        total_discovered,
                        len(discovered),
                    )
            except Exception:
                logger.exception("Discovery phase failed — continuing")

        logger.info("Raw graph complete — starting Graphiti ingestion...")
        await self._run_graphiti_ingestion(symbols)

        logger.info("Pipeline complete")

    async def run_graphiti_only(self, symbols: list[str] | None = None) -> None:
        """Re-run only the Graphiti episode ingestion from the existing raw graph."""
        if symbols is None:
            # Fetch symbols from local graph instead of vnstock API
            async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
                rows = await builder.query_raw(
                    f"MATCH (c:{NodeLabel.COMPANY}) WHERE c.{Prop.SYMBOL} IS NOT NULL RETURN c.{Prop.SYMBOL}",
                )
                symbols = [r[0] for r in rows if r[0]]
        await self._run_graphiti_ingestion(symbols)

    async def run_daily_update(self) -> None:
        """Daily update is no longer needed after removing price data."""
        logger.info("Daily update skipped — price data removed from graph")

    # ------------------------------------------------------------------
    # Macro data ingestion
    # ------------------------------------------------------------------

    async def run_macro_ingestion(
        self, sources: list[str] | None = None,
    ) -> dict[str, int]:
        """Ingest macro data from all configured sources.

        sources: list like ["worldbank", "imf", "yfinance", "vnstock"]
                If None, ingest from all enabled sources.
        Returns dict with counts per source.
        """
        if sources is None:
            sources = [s.strip() for s in self._macro_settings.sources.split(",")]

        results: dict[str, int] = {}
        for source in sources:
            try:
                count = await getattr(self, f"_ingest_{source}_macro")()
                results[source] = count
                logger.info("Macro ingestion from %s: %d indicators", source, count)
            except Exception:
                logger.exception("Failed to ingest from %s", source)
                results[source] = 0

        logger.info("Macro ingestion complete: %s", results)

        # Now that we have macro indicators, link them to sectors/industries
        link_count = await self._link_macro_to_sectors_and_industries()
        logger.info("Macro → sector/industry links created: %d", link_count)

        return results

    async def _link_macro_to_sectors_and_industries(self) -> int:
        """Create AFFECTS_SECTOR and AFFECTS_INDUSTRY edges from MACRO_SECTOR_LINKS."""
        from ourgraph.constants import MACRO_SECTOR_LINKS

        if not MACRO_SECTOR_LINKS:
            return 0

        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            total_links = 0
            for macro_name, sector_names in MACRO_SECTOR_LINKS.items():
                for sector_name in sector_names:
                    try:
                        await builder.upsert_macro_sector_link(macro_name, sector_name)
                        total_links += 1
                    except Exception:
                        logger.exception(
                            "Failed to link macro '%s' → sector '%s'",
                            macro_name,
                            sector_name,
                        )
            return total_links

    async def _ingest_worldbank_macro(self) -> int:
        """Fetch and upsert World Bank data."""
        if self._wb_fetcher is None:
            logger.warning("WorldBankFetcher not available, skipping.")
            return 0
        df = await self._wb_fetcher.fetch_all()
        if df.is_empty():
            return 0
        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            await builder.upsert_macro_indicator(df)
        return len(df)

    async def _ingest_imf_macro(self) -> int:
        """Fetch and upsert IMF data."""
        if self._imf_fetcher is None:
            logger.warning("IMFFetcher not available, skipping.")
            return 0
        df = await self._imf_fetcher.fetch_all()
        if df.is_empty():
            return 0
        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            await builder.upsert_macro_indicator(df)
        return len(df)

    async def _ingest_yfinance_macro(self) -> int:
        """Fetch and upsert yfinance commodities/indices data."""
        if self._yf_fetcher is None:
            logger.warning("YFinanceFetcher not available, skipping.")
            return 0
        df = await self._yf_fetcher.fetch_all()
        if df.is_empty():
            return 0
        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            await builder.upsert_macro_indicator(df)
        return len(df)

    async def _ingest_vnstock_macro(self) -> int:
        """Fetch and upsert vnstock macro data (if available)."""
        if self._vn_macro_fetcher is None:
            logger.warning("VnstockMacroFetcher not available, skipping.")
            return 0
        if not self._vn_macro_fetcher.is_available:
            logger.warning("Vnstock Macro module not available in current tier.")
            return 0
        df = await self._vn_macro_fetcher.fetch_all()
        if df.is_empty():
            return 0
        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            await builder.upsert_macro_indicator(df)
        return len(df)

    # ------------------------------------------------------------------
    # Symbol resolution — VNIndex first
    # ------------------------------------------------------------------

    async def resolve_symbols_for_progress(self) -> list[str]:
        """Resolve symbols without running the full pipeline (for progress bar)."""
        return await self._resolve_symbols()

    async def _resolve_symbols(self) -> list[str]:
        """Resolve the list of symbols to process (HOSE + HNX)."""
        symbols = self._vnstock.get_vnindex_symbols()
        if symbols:
            logger.info("Resolved %d symbols (HOSE + HNX) from vnstock", len(symbols))
            return symbols

        logger.warning(
            "Could not resolve any symbols from vnstock, falling back to graph",
        )
        # Fallback: get symbols from existing graph
        try:
            async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
                rows = await builder.query_raw(
                    f"MATCH (c:{NodeLabel.COMPANY}) WHERE c.{Prop.SYMBOL} IS NOT NULL RETURN c.{Prop.SYMBOL}",
                )
                symbols = [r[0] for r in rows if r[0]]
                if symbols:
                    logger.info("Using %d symbols from existing graph", len(symbols))
                    return symbols
        except Exception:
            logger.exception("Failed to fallback to graph symbols")

        return []

    async def _get_ingested_symbols(self) -> set[str]:
        """Return the set of symbols that already have a Company node in the graph."""
        try:
            async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
                rows = await builder.query_raw(
                    f"MATCH (c:{NodeLabel.COMPANY}) "
                    f"WHERE c.{Prop.SYMBOL} IS NOT NULL "
                    f"RETURN c.{Prop.SYMBOL}",
                )
                return {r[0].upper() for r in rows if r[0]}
        except Exception:
            logger.exception("Failed to query ingested symbols — assuming none")
            return set()

    async def _filter_uningested(self, symbols: list[str]) -> list[str]:
        """Return only symbols not yet present in the graph, preserving order."""
        ingested = await self._get_ingested_symbols()
        if not ingested:
            return symbols
        remaining = [s for s in symbols if s.upper() not in ingested]
        skipped = len(symbols) - len(remaining)
        if skipped:
            logger.info(
                "Skipping %d already-ingested symbols (%d remaining)",
                skipped,
                len(remaining),
            )
        return remaining

    async def _filter_by_industries(
        self,
        builder: GraphBuilder,
        industries: list[str],
    ) -> list[str]:
        """Filter symbols to only those belonging to the given industries.

        Queries the graph for Company nodes connected to Industry nodes
        whose name matches any of the provided industry names.
        """
        all_filtered: list[str] = []
        for industry in industries:
            rows = await builder.query_raw(
                f"""
                MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
                WHERE toLower(ind.{Prop.NAME}) CONTAINS toLower($industry)
                RETURN c.{Prop.SYMBOL}
                """,
                {"industry": industry},
            )
            all_filtered.extend(r[0] for r in rows if r[0])

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for sym in all_filtered:
            if sym.upper() not in seen:
                seen.add(sym.upper())
                unique.append(sym)

        if unique:
            logger.info(
                "Filtered to %d symbols matching industries %s: %s",
                len(unique),
                industries,
                unique,
            )
        return unique

    def _batches(self, items: list) -> list[list]:
        size = self._settings.pipeline.batch_size
        return [items[i : i + size] for i in range(0, len(items), size)]

    async def _build_name_to_symbol_map(
        self,
        builder: GraphBuilder,
    ) -> dict[str, str]:
        """Build a mapping from company names (and symbols) to symbols.

        This is used to resolve corporate shareholder names to their
        ticker symbols for proper graph linkage.
        """
        name_to_symbol: dict[str, str] = {}
        try:
            rows = await builder.query_raw(
                f"MATCH (c:{NodeLabel.COMPANY}) RETURN c.{Prop.SYMBOL}, c.{Prop.NAME}",
            )
            for row in rows:
                sym, name = row[0], row[1]
                if sym:
                    name_to_symbol[sym.lower()] = sym
                    if name:
                        name_to_symbol[(name or "").lower()] = sym
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return name_to_symbol

    # ------------------------------------------------------------------
    # Company node ingestion
    # ------------------------------------------------------------------

    async def _ingest_companies(
        self,
        builder: GraphBuilder,
        symbols: list[str],
    ) -> None:
        logger.info("Ingesting %d companies...", len(symbols))
        for i, sym in enumerate(symbols):
            try:
                df = self._vnstock.get_company_overview(sym)
                self._log_fetch_result(f"{sym}/overview", df)
                if not df.is_empty():
                    await builder.upsert_companies(df)
                    await builder.upsert_sector_industry(df)
                    # Extract auditor from overview data (VCI source lacks this column)
                    if "auditor" in df.columns:
                        auditor = df.select(
                            pl.col("auditor").cast(pl.Utf8).drop_nulls().first(),
                        ).item()
                        if auditor:
                            await builder.upsert_auditor(sym, str(auditor))
            except Exception:
                logger.exception("Company ingestion failed for %s", sym)
            if self._on_symbol_done:
                self._on_symbol_done(sym, "Company")
            if i > 0 and i % 10 == 0:
                logger.info("Companies: %d/%d done", i, len(symbols))
        logger.info("Company ingestion complete")

    # ------------------------------------------------------------------
    # Per-symbol ingestion
    # ------------------------------------------------------------------

    async def _ingest_per_symbol(
        self,
        builder: GraphBuilder,
        symbols: list[str],
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        total = len(symbols)
        for i, sym in enumerate(symbols):
            try:
                await self._ingest_symbol(builder, sym, name_to_symbol)
            except Exception:
                logger.exception("Symbol %s failed", sym)
            if self._on_symbol_done:
                self._on_symbol_done(sym, "Details")
            if i > 0 and i % 5 == 0:
                progress_pct = 100.0 * (i + 1) / total
                logger.info(
                    "Progress: %d/%d symbols (%.0f%%)", i + 1, total, progress_pct,
                )

        logger.info("Per-symbol ingestion complete: %d symbols", total)

    async def _ingest_symbol(
        self,
        builder: GraphBuilder,
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        logger.info("Ingesting symbol: %s...", symbol)
        statements_count = await self._ingest_symbol_statements(builder, symbol)
        indicators_count = await self._ingest_symbol_indicators(builder, symbol)
        officers_count = await self._ingest_symbol_officers(builder, symbol)
        subsidiaries_count = await self._ingest_symbol_subsidiaries(
            builder,
            symbol,
            name_to_symbol,
        )
        shareholders_count = await self._ingest_symbol_shareholders(
            builder, symbol, name_to_symbol,
        )
        events_count = await self._ingest_symbol_events(builder, symbol)
        kbs_count = await self._ingest_symbol_kbs_enrichment(
            builder, symbol, name_to_symbol,
        )

        logger.info(
            "Finished %s: statements=%d, ratios=%d, "
            "officers=%d, subsidiaries=%d, shareholders=%d, events=%d, kbs=%d",
            symbol,
            statements_count,
            indicators_count,
            officers_count,
            subsidiaries_count,
            shareholders_count,
            events_count,
            kbs_count,
        )

    @staticmethod
    def _log_fetch_result(label: str, df: pl.DataFrame) -> None:
        """Log the shape and columns of a fetched DataFrame for debugging."""
        if df.is_empty():
            logger.warning("  %s: EMPTY (no data)", label)
        else:
            logger.debug(
                "  %s: %d rows × %d cols — %s",
                label,
                len(df),
                len(df.columns),
                ", ".join(df.columns),
            )

    async def _ingest_symbol_statements(
        self,
        builder: GraphBuilder,
        symbol: str,
    ) -> int:
        statements_count = 0
        statement_fetchers = {
            "balance_sheet": self._vnstock.get_balance_sheet,
            "income_statement": self._vnstock.get_income_statement,
            "cash_flow": self._vnstock.get_cash_flow,
        }
        for stmt in ("balance_sheet", "income_statement", "cash_flow"):
            df = statement_fetchers[stmt](symbol, "quarter")
            self._log_fetch_result(f"{symbol}/{stmt}", df)
            if df.is_empty():
                continue
            await builder.upsert_financial_statement(df, symbol, stmt, "quarter")
            statements_count += len(df)
        return statements_count

    async def _ingest_symbol_indicators(
        self,
        builder: GraphBuilder,
        symbol: str,
    ) -> int:
        df_ratios = self._vnstock.get_financial_ratios(symbol, "quarter")
        self._log_fetch_result(f"{symbol}/ratios", df_ratios)
        if df_ratios.is_empty():
            return 0
        await builder.upsert_financial_indicators(df_ratios, symbol)
        return len(df_ratios)

    async def _ingest_symbol_officers(self, builder: GraphBuilder, symbol: str) -> int:
        df_officers = self._vnstock.get_officers(symbol)
        self._log_fetch_result(f"{symbol}/officers", df_officers)
        if df_officers.is_empty():
            return 0
        await builder.upsert_officers(df_officers, symbol)
        # Create derived role relationships (IS_BOARD_MEMBER, IS_FOUNDER, IS_EXECUTIVE)
        await builder.upsert_officer_roles(df_officers, symbol)
        return len(df_officers)

    async def _ingest_symbol_subsidiaries(
        self,
        builder: GraphBuilder,
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> int:
        df_subs = self._vnstock.get_subsidiaries(symbol)
        self._log_fetch_result(f"{symbol}/subsidiaries", df_subs)
        if df_subs.is_empty():
            return 0
        await builder.upsert_subsidiaries(df_subs, symbol, name_to_symbol)
        return len(df_subs)

    async def _ingest_symbol_shareholders(
        self,
        builder: GraphBuilder,
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> int:
        df_holders = self._vnstock.get_shareholders(symbol)
        self._log_fetch_result(f"{symbol}/shareholders", df_holders)
        if df_holders.is_empty():
            return 0
        await builder.upsert_shareholders(df_holders, symbol, name_to_symbol)
        return len(df_holders)

    async def _ingest_symbol_events(self, builder: GraphBuilder, symbol: str) -> int:
        """Fetch and store corporate action events as Company node properties."""
        df_events = self._vnstock.get_events(symbol)
        self._log_fetch_result(f"{symbol}/events", df_events)
        if df_events.is_empty():
            return 0
        await builder.upsert_company_events(symbol, df_events)
        return len(df_events)

    # ------------------------------------------------------------------
    # KBS enrichment (Phase 1a — richer profile data)
    # ------------------------------------------------------------------

    async def _ingest_symbol_kbs_enrichment(
        self,
        builder: GraphBuilder,
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> int:
        """Enrich the graph with richer KBS profile data.

        KBS provides more entries and richer fields for subsidiaries,
        officers, shareholders, and auditor compared to vnstock's standard
        wrappers. This runs after the vnstock pipeline as an additive step.

        Returns total number of enriched data points written.
        """
        if not _HAVE_KBS:
            return 0

        fetcher = KbsFetcher()
        try:
            enrichment = await fetcher.enrich_symbol(symbol)
        except Exception:
            logger.debug("KBS enrichment failed for %s", symbol, exc_info=True)
            return 0
        finally:
            await fetcher.close()

        if enrichment is None:
            return 0

        count = 0

        # 1. Enriched subsidiaries (KBS has up to 96 vs vnstock's ~20)
        df_subs = enrichment.get("subsidiaries")
        if df_subs is not None and not df_subs.is_empty():
            try:
                await builder.upsert_subsidiaries(df_subs, symbol, name_to_symbol)
                count += len(df_subs)
                logger.debug(
                    "KBS: %d subsidiaries enriched for %s", len(df_subs), symbol,
                )
            except Exception:
                logger.debug(
                    "KBS subsidiary enrichment failed for %s", symbol, exc_info=True,
                )

        # 2. Enriched leaders (KBS provides English position for better classification)
        df_leaders = enrichment.get("leaders")
        if df_leaders is not None and not df_leaders.is_empty():
            try:
                await builder.upsert_officers(df_leaders, symbol)
                await builder.upsert_officer_roles(df_leaders, symbol)
                count += len(df_leaders)
                logger.debug("KBS: %d leaders enriched for %s", len(df_leaders), symbol)
            except Exception:
                logger.debug(
                    "KBS leader enrichment failed for %s", symbol, exc_info=True,
                )

        # 3. Enriched shareholders (KBS provides share count + ownership %)
        df_holders = enrichment.get("shareholders")
        if df_holders is not None and not df_holders.is_empty():
            try:
                await builder.upsert_shareholders(df_holders, symbol, name_to_symbol)
                count += len(df_holders)
                logger.debug(
                    "KBS: %d shareholders enriched for %s", len(df_holders), symbol,
                )
            except Exception:
                logger.debug(
                    "KBS shareholder enrichment failed for %s", symbol, exc_info=True,
                )

        # 4. Auditor from KT field (only if not already set by vnstock)
        auditor = enrichment.get("auditor")
        if auditor:
            try:
                # Only set if not already present
                existing = await builder.query_raw(
                    f"MATCH (c:{NodeLabel.COMPANY} {{symbol: $sym}})-[:AUDITED_BY]->() RETURN COUNT(*)",
                    {"sym": symbol},
                )
                has_auditor = (
                    existing and int(existing[0][0]) > 0 if existing else False
                )
                if not has_auditor:
                    await builder.upsert_auditor(symbol, auditor)
                    count += 1
                    logger.debug("KBS: auditor '%s' set for %s", auditor, symbol)
            except Exception:
                logger.debug(
                    "KBS auditor enrichment failed for %s", symbol, exc_info=True,
                )

        if count:
            logger.info("KBS enriched %d data points for %s", count, symbol)
        return count

    async def run_scrapers(
        self,
        symbols: list[str] | None = None,
        *,
        cafef: bool = False,
        hnx_bonds: bool = False,
        scic: bool = False,
        max_cafef_symbols: int = 20,
    ) -> dict[str, int]:
        """Run the configured scrapers and upsert results into the graph.

        Args:
            symbols: Symbols for per-symbol scrapers (CafeF)
            cafef: Run CafeF disclosure scraper
            hnx_bonds: Run HNX bond scraper
            scic: Run SCIC portfolio scraper
            max_cafef_symbols: Max symbols to process for CafeF scraper

        Returns:
            Dict of scraper name -> count of relationships created

        """
        results: dict[str, int] = {}

        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            name_to_symbol = await self._build_name_to_symbol_map(builder)

            def _name_resolver(name: str) -> str | None:
                """Resolve company name to symbol using the map."""
                lookup = name.lower().strip()
                # Direct match (symbol or full company name)
                direct = name_to_symbol.get(lookup)
                if direct:
                    return direct
                # Word-boundary match only — avoid matching "VCB"
                # inside "VCBNeo" or "VCBL".
                for name_key, sym in name_to_symbol.items():
                    if len(name_key) < 3:
                        continue
                    # Match only if the key appears as a whole word
                    # or the lookup is a complete substring at word boundaries.
                    import re as _re

                    if _re.search(rf"\b{_re.escape(name_key)}\b", lookup):
                        return sym
                return None

            if cafef:
                count = await self._run_cafef_scraper(
                    builder, symbols, _name_resolver, max_cafef_symbols,
                )
                results["cafef"] = count

            if hnx_bonds:
                count = await self._run_hnx_bond_scraper(builder, _name_resolver)
                results["hnx_bonds"] = count

            if scic:
                count = await self._run_scic_scraper(builder, _name_resolver)
                results["scic"] = count

        return results

    async def _run_cafef_scraper(
        self,
        builder: GraphBuilder,
        symbols: list[str] | None,
        name_resolver: Callable[[str], str | None],
        max_symbols: int = 20,
    ) -> int:
        """Run CafeF disclosure scraper and upsert relationships."""
        try:
            from ourgraph.ingest.cafef_scraper import batch_scrape
        except ImportError:
            logger.warning("CafeF scraper not available (missing dependencies)")
            return 0

        if symbols is None:
            symbols = await self._resolve_symbols()

        df = await asyncio.to_thread(
            batch_scrape,
            symbols,
            name_resolver=name_resolver,
            max_symbols=max_symbols,
        )
        if df.is_empty():
            return 0

        return await self._upsert_scraper_results(builder, df)

    async def _run_hnx_bond_scraper(
        self,
        builder: GraphBuilder,
        name_resolver: Callable[[str], str | None],
    ) -> int:
        """Run HNX bond scraper and upsert relationships."""
        try:
            from ourgraph.ingest.hnx_bond_scraper import scrape_bonds
        except ImportError:
            logger.warning("HNX bond scraper not available (missing dependencies)")
            return 0

        df = await asyncio.to_thread(scrape_bonds, name_resolver=name_resolver)
        if df.is_empty():
            return 0

        # 1. Upsert all bonds as Bond nodes linked to their issuing companies.
        #    This is the primary path — it saves every bond record that has a
        #    resolved issuer symbol (the scraper extracts tickers from issuer
        #    names like "TCB - Ngan hang...").
        bond_count = await builder.upsert_bonds(df)

        # 2. For records that also have an underwriter, create additional
        #    UNDERWRITTEN_BY and LENDS_TO edges between the issuer and the
        #    underwriter.  cbonds.hnx.vn does not expose underwriter data, so
        #    this path is exercised only by future scrapers that do.
        edge_count = 0
        for row in df.to_dicts():
            issuer_symbol = row.get("issuer_symbol", "")
            issuer_name = row.get("issuer_name", "")

            if not issuer_symbol:
                logger.warning(
                    "HNX bond: could not resolve issuer symbol for '%s' — skipping",
                    issuer_name,
                )
                continue

            underwriter_symbol = row.get("underwriter_symbol") or ""
            underwriter_name = row.get("underwriter_name") or ""

            if underwriter_symbol and underwriter_name:
                await builder.upsert_company_relationship(
                    source_symbol=issuer_symbol,
                    target_symbol=underwriter_symbol,
                    target_name=underwriter_name,
                    rel_type=RelType.UNDERWRITTEN_BY,
                    interest_rate=row.get("interest_rate"),
                    maturity_date=row.get("maturity_date", ""),
                    issue_date=row.get("issue_date", ""),
                    issue_amount=row.get("issue_amount"),
                    description=f"Bond issuance by {issuer_name}",
                )
                edge_count += 1

                await builder.upsert_company_relationship(
                    source_symbol=issuer_symbol,
                    target_symbol=underwriter_symbol,
                    target_name=underwriter_name,
                    rel_type=RelType.LENDS_TO,
                    amount=row.get("issue_amount"),
                    interest_rate=row.get("interest_rate"),
                    maturity_date=row.get("maturity_date", ""),
                    transaction_date=row.get("issue_date", ""),
                    description=f"Loan from bond issuance underwritten by {underwriter_name}",
                )
                edge_count += 1
            else:
                logger.debug(
                    "HNX bond: %s issued %s (%s) at %.1f%% maturing %s "
                    "(no underwriter data — saved as Bond node)",
                    issuer_symbol,
                    row.get("bond_code", ""),
                    row.get("currency", ""),
                    row.get("interest_rate") or 0,
                    row.get("maturity_date", ""),
                )

        logger.info(
            "HNX bond scraper: %d Bond nodes upserted, %d underwriter edges created",
            bond_count,
            edge_count,
        )

        return bond_count + edge_count

    async def _run_scic_scraper(
        self,
        builder: GraphBuilder,
        name_resolver: Callable[[str], str | None],
    ) -> int:
        """Fetch state ownership data and upsert STATE_OWNS edges.

        Primary source: KBS Profile Ownership[] data for each company.
        Fallback: hardcoded state-ownership percentages from public reports.

        The source node is 'Chính phủ Việt Nam' (GOV_VN) rather than SCIC
        since the original SCIC website is defunct and state ownership
        encompasses more than just SCIC-managed enterprises.
        """
        try:
            from ourgraph.ingest.scic_scraper import (
                GOVERNMENT_NODE_NAME,
                GOVERNMENT_SYMBOL,
                fetch_state_ownership_batch,
            )
        except ImportError:
            logger.warning("SCIC scraper not available (missing dependencies)")
            return 0

        symbols = await self._resolve_symbols()
        if not symbols:
            return 0

        df = await fetch_state_ownership_batch(symbols, concurrency=3)
        if df.is_empty():
            logger.warning("No state ownership data found for any symbol")
            return 0

        # Ensure the government node exists (no self-edge)
        await builder.query_raw(
            "MERGE (g:Company {symbol: $sym}) SET g.name = $name",
            {"sym": GOVERNMENT_SYMBOL, "name": GOVERNMENT_NODE_NAME},
        )

        count = 0
        for row in df.to_dicts():
            company_symbol = row.get("company_symbol", "")
            company_name = row.get("company_name", "")
            ownership = row.get("ownership_percent")

            if not company_symbol or not ownership or ownership <= 0:
                continue

            await builder.upsert_company_relationship(
                source_symbol=GOVERNMENT_SYMBOL,
                target_symbol=company_symbol,
                target_name=company_name,
                rel_type=RelType.STATE_OWNS,
                stake_percent=ownership,
                description=f"State ownership in {company_name or company_symbol}: {ownership:.1f}%",
            )
            count += 1

        logger.info("SCIC/State ownership: %d STATE_OWNS edges created", count)
        return count

    @staticmethod
    async def _upsert_scraper_results(
        builder: GraphBuilder,
        df: pl.DataFrame,
    ) -> int:
        """Upsert scraper results as relationships in the graph."""
        count = 0
        for row in df.to_dicts():
            source = row.get("source_symbol", "")
            target_sym = row.get("target_symbol", "")
            target_name = row.get("target_name", "")
            rel_type = row.get("rel_type", "")

            if not source or not target_sym or not rel_type:
                continue

            await builder.upsert_company_relationship(
                source_symbol=source,
                target_symbol=target_sym,
                target_name=target_name,
                rel_type=rel_type,
                amount=row.get("amount"),
                transaction_date=row.get("transaction_date"),
                description=row.get("description"),
            )
            count += 1

        return count

    # ------------------------------------------------------------------
    # Graphiti ingestion
    # ------------------------------------------------------------------

    async def _run_graphiti_ingestion(self, symbols: list[str] | None = None) -> None:
        """Feed the raw FalkorDB graph into Graphiti as text episodes."""
        from ourgraph.graphiti_layer.ingester import GraphitiIngester

        ingester = await GraphitiIngester.create(self._settings)
        try:
            await ingester.ingest_all(symbols=symbols)
        finally:
            await ingester.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
