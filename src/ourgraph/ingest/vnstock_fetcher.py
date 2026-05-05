"""
vnstock data fetcher.

Wraps vnstock 4.0 APIs and converts all pandas DataFrames to polars.
Source is always read from config — never hardcoded.

vnstock 4.0 uses KBS as the default source (works everywhere).
VCI provides richer company data (subsidiaries, officers) but is
best on local machines.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import polars as pl

from ourgraph.config import VnstockSettings

logger = logging.getLogger(__name__)


def _to_polars(df) -> pl.DataFrame:
    """Convert a pandas DataFrame from vnstock to a polars DataFrame."""
    if df is None:
        return pl.DataFrame()
    try:
        return pl.from_pandas(df)
    except Exception as exc:
        logger.warning("Could not convert DataFrame to polars: %s", exc)
        return pl.DataFrame()


class VnstockFetcher:
    """
    Fetches all data needed to populate the knowledge graph from vnstock.

    All methods return polars DataFrames.
    The `source` is set once at construction from config.
    """

    def __init__(self, settings: VnstockSettings) -> None:
        self._source = settings.source
        self._delay = settings.api_delay

    def _throttle(self) -> None:
        if self._delay > 0:
            time.sleep(self._delay)

    # ------------------------------------------------------------------
    # Symbol listing
    # ------------------------------------------------------------------

    def get_all_symbols(self) -> pl.DataFrame:
        """
        Return all listed symbols on HOSE + HNX.
        Columns: symbol, exchange, ...
        """
        from vnstock import Listing  # type: ignore[import]

        try:
            listing = Listing(source=self._source)
            df = listing.all_symbols()
            result = _to_polars(df)
            self._throttle()
            return result
        except Exception as exc:
            logger.exception("Failed to fetch symbol listing: %s", exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Company overview
    # ------------------------------------------------------------------

    def get_company_overview(self, symbol: str) -> pl.DataFrame:
        """
        Fetch company overview / profile.
        Uses VCI source for richer data (icb_name, issue_share, etc.)
        Falls back to KBS if VCI fails.
        """
        from vnstock import Company  # type: ignore[import]

        for src in [self._source, "VCI", "KBS"]:
            try:
                company = Company(symbol=symbol, source=src)
                df = company.overview()
                result = _to_polars(df)
                if not result.is_empty():
                    result = result.with_columns(pl.lit(symbol).alias("symbol"))
                    return result
            except Exception as exc:
                logger.debug(
                    "Company overview failed for %s via %s: %s", symbol, src, exc
                )
        return pl.DataFrame()

    def get_officers(self, symbol: str) -> pl.DataFrame:
        """Fetch current company officers / board members."""
        from vnstock import Company  # type: ignore[import]

        try:
            company = Company(symbol=symbol, source=self._source)
            df = company.officers(filter_by="working")
            result = _to_polars(df)
            self._throttle()
            return result
        except Exception as exc:
            logger.debug("Officers fetch failed for %s: %s", symbol, exc)
            return pl.DataFrame()

    def get_shareholders(self, symbol: str) -> pl.DataFrame:
        """Fetch major shareholders."""
        from vnstock import Company  # type: ignore[import]

        try:
            company = Company(symbol=symbol, source=self._source)
            df = company.shareholders()
            result = _to_polars(df)
            self._throttle()
            return result
        except Exception as exc:
            logger.debug("Shareholders fetch failed for %s: %s", symbol, exc)
            return pl.DataFrame()

    def get_subsidiaries(self, symbol: str) -> pl.DataFrame:
        """Fetch subsidiaries and associated companies."""
        from vnstock import Company  # type: ignore[import]

        try:
            company = Company(symbol=symbol, source=self._source)
            df = company.subsidiaries()
            result = _to_polars(df)
            self._throttle()
            return result
        except Exception as exc:
            logger.debug("Subsidiaries fetch failed for %s: %s", symbol, exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def get_price_history(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1D",
    ) -> pl.DataFrame:
        """
        Fetch OHLCV price history.

        Args:
            symbol: Ticker symbol.
            start: ISO date string (YYYY-MM-DD). Defaults to 2 years ago.
            end: ISO date string (YYYY-MM-DD). Defaults to today.
            interval: '1D' for daily (default).
        """
        from vnstock import Quote  # type: ignore[import]

        if end is None:
            end = date.today().isoformat()
        if start is None:
            start = (date.today() - timedelta(days=730)).isoformat()

        try:
            quote = Quote(symbol=symbol, source=self._source)
            df = quote.history(start=start, end=end, interval=interval)
            result = _to_polars(df)
            if not result.is_empty() and "symbol" not in result.columns:
                result = result.with_columns(pl.lit(symbol).alias("symbol"))
            return result
        except Exception as exc:
            logger.debug("Price history fetch failed for %s: %s", symbol, exc)
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    def get_balance_sheet(self, symbol: str, period: str = "quarter") -> pl.DataFrame:
        """Fetch balance sheet data."""
        return self._get_financial(symbol, "balance_sheet", period)

    def get_income_statement(
        self, symbol: str, period: str = "quarter"
    ) -> pl.DataFrame:
        """Fetch income statement data."""
        return self._get_financial(symbol, "income_statement", period)

    def get_cash_flow(self, symbol: str, period: str = "quarter") -> pl.DataFrame:
        """Fetch cash flow statement data."""
        return self._get_financial(symbol, "cash_flow", period)

    def get_financial_ratios(
        self, symbol: str, period: str = "quarter"
    ) -> pl.DataFrame:
        """Fetch financial ratios."""
        return self._get_financial(symbol, "ratio", period)

    def _get_financial(self, symbol: str, statement: str, period: str) -> pl.DataFrame:
        """Internal dispatcher for Finance.*() calls."""
        from vnstock import Finance  # type: ignore[import]

        try:
            finance = Finance(symbol=symbol, source=self._source)
            method = getattr(finance, statement)
            df = method(period=period)
            result = _to_polars(df)
            if not result.is_empty() and "symbol" not in result.columns:
                result = result.with_columns(pl.lit(symbol).alias("symbol"))
            return result
        except Exception as exc:
            logger.debug(
                "%s/%s fetch failed for %s: %s", statement, period, symbol, exc
            )
            return pl.DataFrame()
