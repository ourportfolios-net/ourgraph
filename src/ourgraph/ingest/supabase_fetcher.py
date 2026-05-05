"""
Supabase data fetcher for the pipeline.

Uses the SQLAlchemy ORM-based fetch_data functions from db.fetch_data.
All methods return polars DataFrames and degrade gracefully when
SUPABASE_DB_URL is not set (returns empty DataFrames, no crash).

This module is the boundary between the database layer and the pipeline:
  db.fetch_data  →  SupabaseFetcher  →  Pipeline
"""

from __future__ import annotations

import logging

import polars as pl

from ourgraph.db.fetch_data import (
    fetch_all_symbols,
    fetch_all_symbols_async,
    fetch_financial_statement_async,
    fetch_officers_async,
    fetch_officers_sync,
    fetch_overview_all,
    fetch_overview_async,
    fetch_price_history_async,
    fetch_price_history_sync,
    fetch_ratio_quarterly_async,
    fetch_ratio_quarterly_sync,
    fetch_shareholders_async,
    fetch_shareholders_sync,
    fetch_stats_async,
    fetch_stats_sync,
)

logger = logging.getLogger(__name__)


class SupabaseFetcher:
    """
    Reads your existing Supabase data via SQLAlchemy ORM.

    Safe to instantiate even when Supabase is not configured —
    all methods return empty DataFrames without raising.

    Async methods are preferred inside the pipeline.
    Sync methods are available for CLI / bootstrap use.
    """

    def __init__(self) -> None:
        from ourgraph.config import get_settings

        self._available = bool(get_settings().supabase.supabase_db_url)
        if not self._available:
            logger.info(
                "SUPABASE_DB_URL not set — SupabaseFetcher disabled. "
                "All data will come from vnstock directly."
            )

    # ------------------------------------------------------------------
    # Symbol list
    # ------------------------------------------------------------------

    async def get_all_symbols_async(self) -> list[str]:
        if not self._available:
            return []
        try:
            return await fetch_all_symbols_async()
        except Exception as exc:
            logger.warning("get_all_symbols_async failed: %s", exc)
            return []

    def get_all_symbols(self) -> list[str]:
        if not self._available:
            return []
        try:
            return fetch_all_symbols()
        except Exception as exc:
            logger.warning("get_all_symbols failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Company overview
    # ------------------------------------------------------------------

    async def get_company_overview_async(self) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return await fetch_overview_async()
        except Exception as exc:
            logger.warning("get_company_overview_async failed: %s", exc)
            return pl.DataFrame()

    def get_company_overview(self) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return fetch_overview_all()
        except Exception as exc:
            logger.warning("get_company_overview failed: %s", exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    async def get_price_history_async(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return await fetch_price_history_async(symbol)
        except Exception as exc:
            logger.warning("get_price_history_async(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    def get_price_history(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return fetch_price_history_sync(symbol)
        except Exception as exc:
            logger.warning("get_price_history(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Financial ratios
    # ------------------------------------------------------------------

    async def get_ratio_quarterly_async(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return await fetch_ratio_quarterly_async(symbol)
        except Exception as exc:
            logger.warning("get_ratio_quarterly_async(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    def get_ratio_quarterly(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return fetch_ratio_quarterly_sync(symbol)
        except Exception as exc:
            logger.warning("get_ratio_quarterly(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    async def get_stats_async(self, symbol: str | None = None) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return await fetch_stats_async(symbol)
        except Exception as exc:
            logger.warning("get_stats_async(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    async def get_financial_statement_async(
        self, statement_name: str, symbol: str, period: str
    ) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return await fetch_financial_statement_async(statement_name, symbol, period)
        except Exception as exc:
            logger.warning("get_financial_statement_async(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    def get_stats(self, symbol: str | None = None) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return fetch_stats_sync(symbol)
        except Exception as exc:
            logger.warning("get_stats failed: %s", exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Officers
    # ------------------------------------------------------------------

    async def get_officers_async(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return await fetch_officers_async(symbol)
        except Exception as exc:
            logger.warning("get_officers_async(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    def get_officers(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return fetch_officers_sync(symbol)
        except Exception as exc:
            logger.warning("get_officers(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Shareholders
    # ------------------------------------------------------------------

    async def get_shareholders_async(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return await fetch_shareholders_async(symbol)
        except Exception as exc:
            logger.warning("get_shareholders_async(%s) failed: %s", symbol, exc)
            return pl.DataFrame()

    def get_shareholders(self, symbol: str) -> pl.DataFrame:
        if not self._available:
            return pl.DataFrame()
        try:
            return fetch_shareholders_sync(symbol)
        except Exception as exc:
            logger.warning("get_shareholders(%s) failed: %s", symbol, exc)
            return pl.DataFrame()
