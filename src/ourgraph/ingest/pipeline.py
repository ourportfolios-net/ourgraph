"""
Main ETL pipeline.

Orchestrates the full flow:
  1. Discover symbols (from Supabase ORM or vnstock)
  2. For each symbol (in batches):
     a. Fetch company overview → upsert Company + Sector/Industry nodes
     b. Fetch price history → upsert StockPrice nodes
     c. Fetch financial statements → upsert FinancialStatement nodes
     d. Fetch ratios → upsert FinancialIndicator nodes
     e. Fetch officers → upsert Officer nodes
     f. Fetch subsidiaries → upsert SUBSIDIARY_OF edges
     g. Fetch shareholders → upsert HOLDS_STAKE_IN edges

Design:
  - Fully async: FalkorDB writes are awaited concurrently where safe.
  - Batch + delay: avoids vnstock rate limits.
  - Idempotent: all writes use MERGE — safe to re-run.
  - Supabase is queried via SQLAlchemy ORM (not raw SQL / connectorx).
  - Supabase data is preferred for cached data; vnstock supplements / updates.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import polars as pl

from ourgraph.config import AppSettings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.ingest.supabase_fetcher import SupabaseFetcher
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher

logger = logging.getLogger(__name__)


class Pipeline:
    """Full ETL pipeline from data sources to FalkorDB knowledge graph."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._vnstock = VnstockFetcher(settings.vnstock)
        self._supabase = SupabaseFetcher()

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def run_full(self, symbols: list[str] | None = None) -> None:
        """
        Run the full pipeline for all symbols (or a provided subset).

        Args:
            symbols: Optional list of tickers to process.
                     Defaults to all symbols resolved from Supabase or vnstock.
        """
        if symbols is None:
            symbols = await self._resolve_symbols()

        logger.info("Pipeline starting — %d symbols", len(symbols))

        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            await builder.ensure_indices()
            await self._ingest_companies(builder, symbols)
            await self._ingest_per_symbol(builder, symbols)

        logger.info("Pipeline complete")

    async def run_daily_update(self) -> None:
        """
        Lightweight daily update — refreshes only prices and indicators.
        Does not re-fetch static company data (subsidiaries, officers, etc.)
        """
        symbols = await self._resolve_symbols()
        today = date.today().isoformat()

        logger.info("Daily update for %d symbols on %s", len(symbols), today)

        async with GraphBuilder.from_settings(self._settings.falkordb) as builder:
            for batch in self._batches(symbols):
                # Sequential price processing to respect API limits
                for sym in batch:
                    try:
                        await self._update_symbol_price(builder, sym, today)
                    except Exception as exc:
                        logger.error("Symbol %s daily update failed: %s", sym, exc)
                    await asyncio.sleep(self._settings.pipeline.batch_delay)

        logger.info("Daily update complete")

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------

    async def _resolve_symbols(self) -> list[str]:
        """
        Resolve the list of symbols to process.

        Priority:
          1. Supabase tickers.overview_df (your existing, curated list)
          2. vnstock Listing.all_symbols()
        """
        symbols = await self._supabase.get_all_symbols_async()
        if symbols:
            logger.info("Resolved %d symbols from Supabase", len(symbols))
            return symbols

        df = self._vnstock.get_all_symbols()
        if not df.is_empty() and "symbol" in df.columns:
            symbols = df["symbol"].to_list()
            logger.info("Resolved %d symbols from vnstock", len(symbols))
            return symbols

        logger.warning("Could not resolve any symbols — check your data sources")
        return []

    def _batches(self, items: list) -> list[list]:
        size = self._settings.pipeline.batch_size
        return [items[i : i + size] for i in range(0, len(items), size)]

    # ------------------------------------------------------------------
    # Company node ingestion
    # ------------------------------------------------------------------

    async def _ingest_companies(
        self, builder: GraphBuilder, symbols: list[str]
    ) -> None:
        """Upsert all Company and Industry nodes from Supabase overview."""
        df_overview = await self._supabase.get_company_overview_async()

        if df_overview.is_empty():
            logger.info("No Supabase overview — fetching from vnstock per symbol")
            for batch in self._batches(symbols):
                for sym in batch:
                    df = self._vnstock.get_company_overview(sym)
                    if not df.is_empty():
                        await builder.upsert_companies(df)
                        await builder.upsert_sector_industry(df)
                await asyncio.sleep(self._settings.pipeline.batch_delay)
        else:
            if symbols:
                df_overview = df_overview.filter(pl.col("symbol").is_in(symbols))
            logger.info("Upserting %d companies to Graph...", len(df_overview))
            await builder.upsert_companies(df_overview)
            await builder.upsert_sector_industry(df_overview)
            logger.info("Upserted %d companies from Supabase", len(df_overview))

    # ------------------------------------------------------------------
    # Per-symbol ingestion
    # ------------------------------------------------------------------

    async def _ingest_per_symbol(
        self, builder: GraphBuilder, symbols: list[str]
    ) -> None:
        total_batches = (
            len(symbols) + self._settings.pipeline.batch_size - 1
        ) // self._settings.pipeline.batch_size

        for i, batch in enumerate(self._batches(symbols)):
            logger.info("Batch %d/%d — %s", i + 1, total_batches, batch)
            # Process sequentially instead of parallel gather
            # This respects API limits much better than concurrent requests
            for sym in batch:
                try:
                    await self._ingest_symbol(builder, sym)
                except Exception as exc:
                    logger.error("Symbol %s failed: %s", sym, exc)
                # Global rate-limit delay per symbol
                await asyncio.sleep(self._settings.pipeline.batch_delay)

    async def _ingest_symbol(self, builder: GraphBuilder, symbol: str) -> None:
        """Ingest all data for a single symbol."""
        logger.info("Ingesting symbol: %s...", symbol)
        prices_count = 0
        statements_count = 0
        indicators_count = 0
        officers_count = 0
        subsidiaries_count = 0
        shareholders_count = 0

        # --- Price history (Supabase cache preferred) ---
        df_prices = await self._supabase.get_price_history_async(symbol)
        if df_prices.is_empty():
            df_prices = self._vnstock.get_price_history(symbol)
        if not df_prices.is_empty():
            df_prices = self._normalise_price_df(df_prices, symbol)
            await builder.upsert_stock_prices(df_prices)
            prices_count = len(df_prices)

        # --- Financial statements (Neon DB preferred) ---
        for stmt in ("balance_sheet", "income_statement", "cash_flow"):
            df = await self._supabase.get_financial_statement_async(
                stmt, symbol, "quarter"
            )
            if df.is_empty():
                df = self._vnstock._get_financial(symbol, stmt, "quarter")
            if not df.is_empty():
                await builder.upsert_financial_statement(df, symbol, stmt, "quarter")
                statements_count += len(df)

        # --- Financial ratios (Supabase preferred) ---
        df_ratios = await self._supabase.get_ratio_quarterly_async(symbol)
        if not df_ratios.is_empty():
            await builder.upsert_financial_indicators(df_ratios, symbol)
            indicators_count = len(df_ratios)
        else:
            df_ratios = self._vnstock.get_financial_ratios(symbol, "quarter")
            if not df_ratios.is_empty():
                await builder.upsert_financial_indicators(df_ratios, symbol)
                indicators_count = len(df_ratios)

        # --- Officers (Supabase preferred) ---
        df_officers = await self._supabase.get_officers_async(symbol)
        if df_officers.is_empty():
            df_officers = self._vnstock.get_officers(symbol)
        if not df_officers.is_empty():
            await builder.upsert_officers(df_officers, symbol)
            officers_count = len(df_officers)

        # --- Subsidiaries (vnstock only — always fresh) ---
        df_subs = self._vnstock.get_subsidiaries(symbol)
        if not df_subs.is_empty():
            await builder.upsert_subsidiaries(df_subs, symbol)
            subsidiaries_count = len(df_subs)

        # --- Shareholders (Supabase preferred) ---
        df_holders = await self._supabase.get_shareholders_async(symbol)
        if df_holders.is_empty():
            df_holders = self._vnstock.get_shareholders(symbol)
        if not df_holders.is_empty():
            await builder.upsert_shareholders(df_holders, symbol)
            shareholders_count = len(df_holders)

        logger.info(
            "Finished %s: prices=%d, statements=%d, ratios=%d, officers=%d, subsidiaries=%d, shareholders=%d",
            symbol,
            prices_count,
            statements_count,
            indicators_count,
            officers_count,
            subsidiaries_count,
            shareholders_count,
        )

    async def _update_symbol_price(
        self, builder: GraphBuilder, symbol: str, as_of: str
    ) -> None:
        """Fetch and upsert only the latest price for a symbol."""
        df = self._vnstock.get_price_history(symbol, start=as_of, end=as_of)
        if df.is_empty():
            return
        df = self._normalise_price_df(df, symbol)
        await builder.upsert_stock_prices(df)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_price_df(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
        """
        Normalise price DataFrame column names to the canonical schema.
        vnstock may return 'time', 'tradingDate', or 'date'.
        We always need: symbol, date, open, high, low, close, volume
        """
        rename_map: dict[str, str] = {}
        for col in df.columns:
            if col.lower() in ("time", "tradingdate", "trading_date"):
                rename_map[col] = "date"
            elif col.lower() == "ticker":
                rename_map[col] = "symbol"

        if rename_map:
            df = df.rename(rename_map)

        if "symbol" not in df.columns:
            df = df.with_columns(pl.lit(symbol).alias("symbol"))

        return df
