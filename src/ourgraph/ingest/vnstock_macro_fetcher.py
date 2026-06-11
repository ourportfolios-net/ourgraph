"""vnstock Macro module fetcher for Vietnamese macro economic data.

Uses the vnstock library's Macro module for Vietnamese macro indicators.
May require sponsor tier for some data — individual methods are wrapped in try/except.

Docs: https://vnstocks.com/docs
"""

from __future__ import annotations

import logging
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

# Macro data config: (method_path, name, unit, category, frequency)
VNSTOCK_MACRO_CONFIG = [
    # Economy
    ("economy", "gdp", "GDP (current US$)", "USD", "vn_economy", "annual"),
    ("economy", "cpi", "CPI (inflation, annual %)", "%", "vn_economy", "annual"),
    ("economy", "fdi", "Foreign Direct Investment", "USD", "vn_trade", "annual"),
    ("economy", "import_export", "Import/Export", "USD", "vn_trade", "annual"),
    (
        "economy",
        "industry_prod",
        "Industrial Production",
        "index",
        "vn_economy",
        "monthly",
    ),
    ("economy", "money_supply", "Money Supply (M2)", "VND", "vn_monetary", "monthly"),
    (
        "economy",
        "population_labor",
        "Population & Labor",
        "index",
        "vn_economy",
        "annual",
    ),
    ("economy", "retail", "Retail Sales", "VND", "vn_economy", "monthly"),
    # Currency & Interest
    ("currency", "exchange_rate", "Exchange Rate", "VND", "vn_monetary", "daily"),
    ("currency", "interest_rate", "Interest Rate", "%", "vn_monetary", "daily"),
    # Commodities
    ("commodity", "gold", "Gold Price", "VND", "global_commodity", "daily"),
    ("commodity", "oil_crude", "Crude Oil Price", "USD", "global_commodity", "daily"),
    ("commodity", "gas", "Gas Price", "VND", "global_commodity", "daily"),
]


def _check_available() -> bool:
    """Check if vnstock Macro module is available in current tier."""
    try:
        from vnstock import Macro

        return True
    except (ImportError, AttributeError):
        return False


class VnstockMacroFetcher:
    """Fetches Vietnamese macro data via vnstock Macro module."""

    def __init__(self, start_year: int = 2010) -> None:
        self._start_year = start_year
        self._available = _check_available()
        if not self._available:
            logger.warning(
                "vnstock Macro module not available in current tier. Skipping.",
            )

    @property
    def is_available(self) -> bool:
        return self._available

    async def fetch_all(self) -> pl.DataFrame:
        """Fetch all available macro indicators and return a single DataFrame."""
        if not self._available:
            return pl.DataFrame()

        frames: list[pl.DataFrame] = []
        for (
            module_name,
            method_name,
            name,
            unit,
            category,
            frequency,
        ) in VNSTOCK_MACRO_CONFIG:
            try:
                df = await self._fetch_one(
                    module_name, method_name, name, unit, category, frequency,
                )
                if not df.is_empty():
                    frames.append(df)
                    logger.info("vnstock: fetched %d rows for %s", len(df), name)
            except Exception:
                logger.exception(
                    "vnstock: failed to fetch %s.%s", module_name, method_name,
                )

        if not frames:
            return pl.DataFrame()
        return pl.concat(frames)

    async def _fetch_one(
        self,
        module_name: str,
        method_name: str,
        name: str,
        unit: str,
        category: str,
        frequency: str,
    ) -> pl.DataFrame:
        """Fetch data from a single vnstock Macro method."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._fetch_sync,
            module_name,
            method_name,
            name,
            unit,
            category,
            frequency,
        )

    def _fetch_sync(
        self,
        module_name: str,
        method_name: str,
        name: str,
        unit: str,
        category: str,
        frequency: str,
    ) -> pl.DataFrame:
        """Synchronous fetch using vnstock Macro."""
        try:
            from vnstock import Macro

            macro = Macro()
            module = getattr(macro, module_name, None)
            if module is None:
                return pl.DataFrame()

            method = getattr(module(), method_name, None)
            if method is None:
                return pl.DataFrame()

            result = method()
            if result is None:
                return pl.DataFrame()

            # Convert to polars if it's a pandas DataFrame
            if hasattr(result, "to_dict"):
                pdf = result
                if hasattr(pdf, "reset_index"):
                    pdf = pdf.reset_index()
                return self._normalize_data(pdf, name, unit, category, frequency)

            return pl.DataFrame()

        except (AttributeError, RuntimeError, ValueError, TypeError) as exc:
            logger.debug(
                "vnstock: %s.%s not available: %s", module_name, method_name, exc,
            )
            return pl.DataFrame()

    def _normalize_data(
        self,
        df: Any,
        name: str,
        unit: str,
        category: str,
        frequency: str,
    ) -> pl.DataFrame:
        """Normalize vnstock data to standard DataFrame format."""
        # Handle different return formats from vnstock
        if not hasattr(df, "iterrows"):
            return pl.DataFrame()

        rows: list[dict] = []
        for _, row in df.iterrows():
            # Try to extract date and value from various column formats
            date_val = None
            value = None

            # Look for date-like columns
            for col in ("date", "time", "year", "quarter"):
                if col in df.columns:
                    date_val = row.get(col)
                    break

            # Look for value-like columns
            for col in ("value", "close", "price", "rate", "index"):
                if col in df.columns:
                    val = row.get(col)
                    if val is not None:
                        try:
                            value = float(val)
                            break
                        except (ValueError, TypeError):
                            continue

            if date_val is None or value is None:
                continue

            date_str = str(date_val)[:10] if date_val else ""

            rows.append(
                {
                    "name": name,
                    "value": value,
                    "unit": unit,
                    "date": date_str,
                    "country": "VN",
                    "category": category,
                    "frequency": frequency,
                    "source": "vnstock",
                },
            )

        return pl.DataFrame(rows)
