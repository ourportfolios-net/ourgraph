"""World Bank Open Data API fetcher.

Completely free, no authentication required.
Docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/898599-indicator-api-queries

Fetches Vietnamese macro indicators and returns polars DataFrames.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import polars as pl
from aiohttp import ClientTimeout

from ourgraph.constants import (
    MACRO_MAX_RETRIES,
    MACRO_RETRY_MAX_WAIT,
    MACRO_RETRY_MIN_WAIT,
)

logger = logging.getLogger(__name__)

# Vietnam country code for World Bank API
WB_COUNTRY = "VN"

# Indicator config: (code, name, unit, category, frequency)
WB_INDICATORS = {
    "NY.GDP.MKTP.CD": ("GDP (current US$)", "USD", "vn_economy", "annual"),
    "NY.GDP.MKTP.KD.ZG": ("GDP growth (annual %)", "%", "vn_economy", "annual"),
    "FP.CPI.TOTL.ZG": ("Inflation (CPI, annual %)", "%", "vn_economy", "annual"),
    "PA.NUS.FCRF": (
        "Exchange rate (LCU/USD, period avg)",
        "VND",
        "vn_monetary",
        "annual",
    ),
    "SL.UEM.TOTL.ZS": ("Unemployment (% of total labor)", "%", "vn_economy", "annual"),
    "FM.LBL.MQMY.CN": ("Money supply (M2)", "VND", "vn_monetary", "quarterly"),
    "BX.KLT.DINV.CD.WD": (
        "Foreign direct investment (net inflows)",
        "USD",
        "vn_trade",
        "annual",
    ),
    "NE.IMP.GNFS.CD": ("Imports of goods and services", "USD", "vn_trade", "annual"),
    "NE.EXP.GNFS.CD": ("Exports of goods and services", "USD", "vn_trade", "annual"),
    "NV.IND.TOTL.ZS": ("Industry, value added (% of GDP)", "%", "vn_economy", "annual"),
}


async def _fetch_json(url: str, params: dict | None = None) -> Any:
    """Fetch JSON from World Bank API with retries."""
    for attempt in range(MACRO_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params or {}, timeout=ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if attempt == MACRO_MAX_RETRIES - 1:
                raise
            wait = min(MACRO_RETRY_MIN_WAIT * (2**attempt), MACRO_RETRY_MAX_WAIT)
            logger.warning(
                "WB fetch attempt %d failed: %s. Retrying in %ds...",
                attempt + 1,
                exc,
                wait,
            )
            await asyncio.sleep(wait)
    return None


class WorldBankFetcher:
    """Fetches macro indicators from the World Bank Open Data API."""

    def __init__(
        self, start_year: int = 2010, indicator_codes: list[str] | None = None,
    ) -> None:
        self._start = str(start_year)
        self._end = "2030"
        self._indicators = indicator_codes or list(WB_INDICATORS.keys())

    async def fetch_all(self) -> pl.DataFrame:
        """Fetch all configured indicators and return a single DataFrame."""
        frames: list[pl.DataFrame] = []
        for code in self._indicators:
            try:
                df = await self.fetch_indicator(code)
                if not df.is_empty():
                    frames.append(df)
                    logger.info("WB: fetched %d rows for %s", len(df), code)
            except Exception:
                logger.exception("WB: failed to fetch indicator %s", code)

        if not frames:
            return pl.DataFrame()
        return pl.concat(frames)

    async def fetch_indicator(self, indicator_code: str) -> pl.DataFrame:
        """Fetch a single indicator from World Bank API."""
        config = WB_INDICATORS.get(indicator_code)
        if config is None:
            logger.warning("WB: unknown indicator code %s", indicator_code)
            return pl.DataFrame()

        name, unit, category, frequency = config
        url = f"https://api.worldbank.org/v2/country/{WB_COUNTRY}/indicator/{indicator_code}"
        params = {
            "format": "json",
            "date": f"{self._start}:{self._end}",
            "per_page": "1000",
        }

        data = await _fetch_json(url, params)
        if not data or len(data) < 2:
            return pl.DataFrame()

        # data[0] = metadata, data[1] = list of observations
        observations = data[1]
        if not observations:
            return pl.DataFrame()

        rows: list[dict] = []
        for obs in observations:
            value = obs.get("value")
            date_str = obs.get("date")
            if value is None or date_str is None:
                continue
            rows.append(
                {
                    "name": name,
                    "value": float(value),
                    "unit": unit,
                    "date": self._normalize_date(date_str, frequency),
                    "country": "VN",
                    "category": category,
                    "frequency": frequency,
                    "source": "worldbank",
                },
            )

        return pl.DataFrame(rows)

    @staticmethod
    def _normalize_date(date_str: str, frequency: str) -> str:
        """Convert World Bank date to ISO string."""
        if frequency == "annual":
            return f"{date_str}-01-01"
        if frequency == "quarterly":
            # WB quarterly dates are like "2024Q1"
            if "Q" in date_str:
                year, q = date_str.split("Q")
                month = (int(q) - 1) * 3 + 1
                return f"{year}-{month:02d}-01"
            return f"{date_str}-01-01"
        return f"{date_str}-01-01"
