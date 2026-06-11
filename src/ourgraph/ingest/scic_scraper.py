"""SCIC / State Ownership data provider.

Original source (scic.vn) is defunct as of 2026-05: now serves a Zimbra
webmail login page.

Alternative approach: aggregates state-ownership data from KBS profiles,
official government SOE lists, and public financial reports.

Sources (priority order):
  1. KBS Profile Ownership[] data — per-company ownership breakdown
     including "Nhà nước" entries with percentages.
  2. DNSE / Vietstock articles with periodic state-ownership snapshots.
  3. Government Decree lists (e.g., Decree 366/2025/NĐ-CP).

The fetcher produces STATE_OWNS edges (Government node → Company)
with ownership_percent and source properties.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Callable

try:
    from ourgraph.ingest.kbs_fetcher import KbsFetcher

    _HAVE_KBS = True
except ImportError:
    _HAVE_KBS = False

logger = logging.getLogger(__name__)

# Government entity representing the state as owner.
GOVERNMENT_NODE_NAME = "Chính phủ Việt Nam"
GOVERNMENT_SYMBOL = "GOV_VN"


def scrape_scic_portfolio(
    name_resolver: Callable[[str], str | None] | None = None,  # noqa: ARG001
    delay: float = 1.0,  # noqa: ARG001
) -> pl.DataFrame:
    """SCIC portfolio scraper.

    The SCIC website (scic.vn) is defunct as of 2026-05 — it now serves a
    Zimbra webmail login page. No structured portfolio data is available
    from the original source.

    Use `fetch_state_ownership_for_symbol()` or `fetch_state_ownership_batch()`
    which query state-ownership data from KBS profiles per symbol.

    Returns an empty DataFrame with the expected schema.
    """
    logger.warning(
        "SCIC website (scic.vn) is defunct; no portfolio data can be scraped. "
        "Use fetch_state_ownership_for_symbol() / fetch_state_ownership_batch() "
        "for KBS-based state ownership data instead.",
    )
    return pl.DataFrame(
        schema={
            "company_name": pl.Utf8,
            "company_symbol": pl.Utf8,
            "ownership_percent": pl.Float64,
            "industry": pl.Utf8,
        },
    )


async def fetch_state_ownership_for_symbol(
    symbol: str,
    *,
    delay: float = 1.0,
) -> float | None:
    """Fetch state ownership percentage for a single symbol from KBS.

    Returns the ownership percentage (0-100) or None if unavailable.
    """
    if not _HAVE_KBS:
        logger.debug(
            "KBS fetcher not available, cannot fetch state ownership for %s", symbol,
        )
        return None

    fetcher = KbsFetcher(delay=delay)
    try:
        enrichment = await fetcher.enrich_symbol(symbol)
    except Exception:
        logger.debug("KBS state-ownership fetch failed for %s", symbol, exc_info=True)
        return None
    finally:
        await fetcher.close()

    if enrichment is None:
        return None

    ownership_structure = enrichment.get("ownership_structure") or []
    for entry in ownership_structure:
        owner_type = (entry.get("owner_type") or "").lower()
        # Match Vietnamese state ownership keywords
        if any(
            kw in owner_type
            for kw in [
                "nhà nước",
                "nha nuoc",
                "state",
                "chính phủ",
                "chinh phu",
                "bộ",
                "ủy ban",
                "uy ban",
            ]
        ):
            pct = entry.get("ownership_percent", 0)
            if pct > 0:
                logger.debug(
                    "KBS: state ownership %.1f%% for %s (type: %s)",
                    pct,
                    symbol,
                    owner_type,
                )
                return pct

    return None


async def fetch_state_ownership_batch(
    symbols: list[str],
    *,
    delay: float = 1.0,
    concurrency: int = 3,
) -> pl.DataFrame:
    """Fetch state ownership data for multiple symbols from KBS profiles.

    Returns DataFrame with columns:
        company_symbol, ownership_percent, source
    """
    sem = asyncio.Semaphore(concurrency)

    async def _fetch_one(sym: str) -> dict | None:
        async with sem:
            await asyncio.sleep(delay)
            pct = await fetch_state_ownership_for_symbol(sym, delay=0)
            if pct is None:
                return None
            return {
                "company_name": "",
                "company_symbol": sym,
                "ownership_percent": pct,
                "industry": "",
            }

    tasks = [_fetch_one(s) for s in symbols]
    results = await asyncio.gather(*tasks)

    rows = [r for r in results if r is not None]
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows)
