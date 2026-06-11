"""IMF SDMX API fetcher.

Completely free, no authentication required.
Docs: https://data.imf.org/en/Resource-Pages/IMF-API

Uses SDMX 2.0 CompactData endpoint for IFS (International Financial Statistics).
"""

from __future__ import annotations

import asyncio
import logging
from xml.etree import ElementTree as ET

import aiohttp
import polars as pl
from aiohttp import ClientTimeout

from ourgraph.constants import (
    MACRO_MAX_RETRIES,
    MACRO_RETRY_MAX_WAIT,
    MACRO_RETRY_MIN_WAIT,
)

logger = logging.getLogger(__name__)

# Vietnam country code in IMF SDMX
IMF_COUNTRY = "VN"

# Indicator config: (code, name, unit, category, frequency)
# SDMX 2.0 endpoint: CompactData/IFS/{freq}.{country}.{indicator}
IMF_INDICATORS = {
    "PCPI_IX": ("CPI (consumer price index)", "index", "vn_economy", "monthly"),
    "ENDE_XDC_USD_RATE": (
        "Exchange rate (LCU/USD, end period)",
        "VND",
        "vn_monetary",
        "monthly",
    ),
    "FM_LBL_MQMY_CN": ("Money supply (M2)", "VND", "vn_monetary", "monthly"),
    "FR_INR_LR": ("Interest rate (central bank policy)", "%", "vn_monetary", "monthly"),
}


async def _fetch_xml(url: str) -> str:
    """Fetch XML from IMF API with retries."""
    for attempt in range(MACRO_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(
                timeout=ClientTimeout(total=30),
            ) as session:
                async with session.get(url, timeout=ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    return await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if attempt == MACRO_MAX_RETRIES - 1:
                raise
            wait = min(MACRO_RETRY_MIN_WAIT * (2**attempt), MACRO_RETRY_MAX_WAIT)
            logger.warning(
                "IMF fetch attempt %d failed: %s. Retrying in %ds...",
                attempt + 1,
                exc,
                wait,
            )
            await asyncio.sleep(wait)
    return ""


class IMFFetcher:
    """Fetches macro indicators from the IMF SDMX API."""

    def __init__(
        self, start_year: int = 2010, indicator_codes: list[str] | None = None,
    ) -> None:
        self._start = f"{start_year}-01-01"
        self._end = "2030-12-31"
        self._indicators = indicator_codes or list(IMF_INDICATORS.keys())

    async def fetch_all(self) -> pl.DataFrame:
        """Fetch all configured indicators and return a single DataFrame."""
        frames: list[pl.DataFrame] = []
        for code in self._indicators:
            try:
                df = await self.fetch_indicator(code)
                if not df.is_empty():
                    frames.append(df)
                    logger.info("IMF: fetched %d rows for %s", len(df), code)
            except Exception:
                logger.exception("IMF: failed to fetch indicator %s", code)

        if not frames:
            return pl.DataFrame()
        return pl.concat(frames)

    async def fetch_indicator(self, indicator_code: str) -> pl.DataFrame:
        """Fetch a single indicator from IMF SDMX API."""
        config = IMF_INDICATORS.get(indicator_code)
        if config is None:
            logger.warning("IMF: unknown indicator code %s", indicator_code)
            return pl.DataFrame()

        name, unit, category, frequency = config

        # Map frequency to SDMX freq code
        freq_map = {"monthly": "M", "quarterly": "Q", "annual": "A"}
        freq_code = freq_map.get(frequency, "M")

        # Try HTTPS first, fall back to HTTP on DNS/connection errors
        base_urls = [
            ("https://dataservices.imf.org/REST/SDMX_XML.svc/", "HTTPS"),
            ("http://dataservices.imf.org/REST/SDMX_XML.svc/", "HTTP"),
        ]
        xml_text = ""
        last_error = None
        for base_url, protocol in base_urls:
            url = (
                f"{base_url}"
                f"CompactData/IFS/{freq_code}.{IMF_COUNTRY}.{indicator_code}"
                f"?startPeriod={self._start}&endPeriod={self._end}"
            )
            try:
                xml_text = await _fetch_xml(url)
                if xml_text:
                    logger.info(
                        "IMF: connected via %s for %s", protocol, indicator_code,
                    )
                    break
            except aiohttp.ClientError as exc:
                err_str = str(exc).lower()
                is_connection_error = any(
                    keyword in err_str
                    for keyword in (
                        "name or service not known",
                        "nodename nor servname",
                        "getaddrinfo",
                        "connection refused",
                        "cannot connect",
                        "dns",
                    )
                )
                if is_connection_error and protocol == "HTTPS":
                    logger.warning(
                        "IMF: %s connection failed (%s), falling back to HTTP",
                        protocol,
                        exc,
                    )
                    continue
                last_error = exc
                logger.exception(
                    "IMF: %s fetch failed for %s", protocol, indicator_code,
                )
            except asyncio.TimeoutError as exc:
                last_error = exc
                if protocol == "HTTPS":
                    logger.warning("IMF: %s timed out, falling back to HTTP", protocol)
                    continue
                logger.exception("IMF: HTTP fetch timed out for %s", indicator_code)

        if not xml_text:
            if last_error:
                logger.warning(
                    "IMF: all endpoints failed for %s (last error: %s)",
                    indicator_code,
                    last_error,
                )
            return pl.DataFrame()

        return self._parse_xml(xml_text, name, unit, category, frequency)

    def _parse_xml(
        self, xml_text: str, name: str, unit: str, category: str, frequency: str,
    ) -> pl.DataFrame:
        """Parse IMF SDMX XML response into a DataFrame."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.exception("IMF: failed to parse XML")
            return pl.DataFrame()

        rows: list[dict] = []
        # Find all Series elements
        for series in root.findall(".//Series"):
            # Obs elements contain the data points
            for obs in series.findall(".//Obs"):
                obs_value = obs.find("ObsValue")
                time_period = obs.find("TimePeriod")
                if obs_value is None or time_period is None:
                    continue

                value_str = obs_value.get("value")
                date_str = time_period.get("value")
                if value_str is None or date_str is None:
                    continue

                try:
                    value = float(value_str)
                except (ValueError, TypeError):
                    continue

                rows.append(
                    {
                        "name": name,
                        "value": value,
                        "unit": unit,
                        "date": self._normalize_date(date_str, frequency),
                        "country": "VN",
                        "category": category,
                        "frequency": frequency,
                        "source": "imf",
                    },
                )

        return pl.DataFrame(rows)

    @staticmethod
    def _normalize_date(date_str: str, frequency: str) -> str:
        """Convert IMF date format to ISO string."""
        if frequency == "monthly":
            # Format: "2024-01" or "2024-01-01"
            if len(date_str) == 7:  # YYYY-MM
                return f"{date_str}-01"
            return date_str
        if frequency == "quarterly":
            # Format: "2024-Q1"
            if "-Q" in date_str:
                year, q = date_str.split("-Q")
                month = (int(q)) * 3 - 2
                return f"{year}-{month:02d}-01"
            return date_str
        if frequency == "annual":
            return f"{date_str}-01-01"
        return date_str
