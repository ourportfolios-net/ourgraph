"""yfinance (Yahoo Finance) fetcher for commodities, indices, and macro data.

Free, no API key required. Uses the yfinance library.
Docs: https://ranaroussi.github.io/yfinance/

Note: Yahoo Finance ToS is for personal use only.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

# Ticker → (name, unit, country, category)
YFINANCE_TICKERS = {
    # Commodities
    "GC=F": ("Gold Price (Futures)", "USD", "GLOBAL", "global_commodity"),
    "CL=F": ("Crude Oil (WTI)", "USD", "GLOBAL", "global_commodity"),
    "BZ=F": ("Crude Oil (Brent)", "USD", "GLOBAL", "global_commodity"),
    "SI=F": ("Silver Price (Futures)", "USD", "GLOBAL", "global_commodity"),
    "HG=F": ("Copper Price (Futures)", "USD", "GLOBAL", "global_commodity"),
    "ZC=F": ("Corn Futures", "USD", "GLOBAL", "global_commodity"),
    "ZS=F": ("Soybean Futures", "USD", "GLOBAL", "global_commodity"),
    "KC=F": ("Coffee Futures", "USD", "GLOBAL", "global_commodity"),
    # Indices
    "^VIX": ("VIX (Volatility Index)", "index", "US", "global_index"),
    "^GSPC": ("S&P 500", "index", "US", "global_index"),
    "^HSI": ("Hang Seng Index", "index", "HK", "global_index"),
    "000001.SS": ("Shanghai Composite", "index", "CN", "global_index"),
    "^SETI": ("SET Index (Thailand)", "index", "TH", "global_index"),
    "DX-Y.NYB": ("USD Index (DXY)", "index", "US", "global_index"),
}


class YFinanceFetcher:
    """Fetches commodities, indices, and macro data from Yahoo Finance via yfinance."""

    def __init__(
        self,
        tickers: list[str] | None = None,
        start_year: int = 2010,
    ) -> None:
        self._tickers = tickers or list(YFINANCE_TICKERS.keys())
        self._start = f"{start_year}-01-01"

    async def fetch_all(self) -> pl.DataFrame:
        """Fetch all configured tickers and return a single DataFrame."""
        frames: list[pl.DataFrame] = []
        for ticker in self._tickers:
            try:
                df = await self.fetch_ticker(ticker)
                if not df.is_empty():
                    frames.append(df)
                    logger.info("yfinance: fetched %d rows for %s", len(df), ticker)
            except Exception:
                logger.exception("yfinance: failed to fetch ticker %s", ticker)

        if not frames:
            return pl.DataFrame()
        return pl.concat(frames)

    async def fetch_ticker(self, ticker: str) -> pl.DataFrame:
        """Fetch historical data for a single ticker."""
        config = YFINANCE_TICKERS.get(ticker)
        if config is None:
            logger.warning("yfinance: unknown ticker %s", ticker)
            return pl.DataFrame()

        name, unit, country, category = config

        # yfinance is synchronous, run in a thread to avoid blocking
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(
            None,
            self._fetch_sync,
            ticker,
            self._start,
        )

        if df is None or df.empty:
            return pl.DataFrame()

        # Convert pandas DataFrame to polars
        pdf = df.reset_index()
        pdf.columns = [c.lower() for c in pdf.columns]

        if "date" not in pdf.columns and "index" in pdf.columns:
            pdf = pdf.rename(columns={"index": "date"})

        # Use close price as the value
        if "close" not in pdf.columns:
            logger.warning("yfinance: no 'close' column for %s", ticker)
            return pl.DataFrame()

        rows: list[dict] = []
        for _, row in pdf.iterrows():
            date_val = row.get("date")
            close_val = row.get("close")
            if date_val is None or close_val is None:
                continue
            date_str = str(date_val)[:10]  # Extract YYYY-MM-DD

            # Filter NaN and Inf which FalkorDB cannot serialize
            float_val = float(close_val)
            if math.isnan(float_val) or math.isinf(float_val):
                continue

            rows.append(
                {
                    "name": name,
                    "value": float_val,
                    "unit": unit,
                    "date": date_str,
                    "country": country,
                    "category": category,
                    "frequency": "daily",
                    "source": "yfinance",
                },
            )

        return pl.DataFrame(rows)

    @staticmethod
    def _fetch_sync(ticker: str, start: str) -> Any:
        """Synchronous fetch using yfinance."""
        try:
            import yfinance as yf

            return yf.Ticker(ticker).history(
                start=start,
                interval="1d",
            )
        except Exception:
            logger.exception("yfinance: sync fetch failed for %s", ticker)
            return None
