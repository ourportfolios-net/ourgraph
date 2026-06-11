"""vnstock data fetcher.

Wraps vnstock APIs and converts all pandas DataFrames to polars.
Source is always read from config — never hardcoded downstream.

vnstock 4.0 uses KBS as the default source (works everywhere).
VCI provides richer company data (subsidiaries, officers) but is
best on local machines.

VNIndex = all stocks listed on HOSE (Ho Chi Minh Stock Exchange).
The exchange filter is applied here so the pipeline only processes
relevant tickers.

Valid sources per vnstock class:
  Listing:  KBS, VCI, MSN
  Company:  KBS, VCI
  Finance:  KBS, VCI
  Quote:    kbs, vci, msn, dnse, binance, fmp, fmarket

TCBS is deprecated and must not be used.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    import pandas as pd

    from ourgraph.config import VnstockSettings

logger = logging.getLogger(__name__)


def _suppress_vnstock_noise() -> None:
    """Suppress vnstock's promo/telemetry logging and banner output."""
    for name in ("vnai", "vnai.scope", "vnai.scope.promo"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        from vnstock import vnai  # type: ignore[import]

        vnai.configure_privacy(level="minimal")
    except Exception:  # noqa: BLE001
        logger.debug("Could not configure vnai privacy", exc_info=True)


def _register(api_key: str | None) -> None:
    """Register the user with vnstock for higher API rate limits."""
    if not api_key:
        logger.info("No VNSTOCK_API_KEY set — running with free tier (20 req/min)")
        return
    try:
        from vnstock import register_user  # type: ignore[import]

        register_user(api_key=api_key)
        logger.info("Registered vnstock user with API key (60 req/min)")
    except Exception:  # noqa: BLE001
        logger.warning("Failed to register vnstock API key — falling back to free tier")


def _to_polars(df: pd.DataFrame | None) -> pl.DataFrame:
    if df is None:
        return pl.DataFrame()
    try:
        return pl.from_pandas(df)
    except (TypeError, ValueError, AttributeError) as exc:
        logger.warning("Could not convert DataFrame to polars: %s", exc)
        return pl.DataFrame()


def _normalize_company_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize company overview column names to what the builder expects.

    vnstock returns different column names depending on the source (KBS vs VCI)
    and version. This function maps them to a consistent set.
    """
    rename: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower()
        # Company name
        if lower in ("short_name", "company_name", "name_vi", "ten_cong_ty"):
            rename[col] = "short_name"
        # Industry — critical for sector/industry node creation
        elif lower in (
            "industry",
            "industryname",
            "industry_name",
            "nganh_nghe",
            "nganh",
        ):
            rename[col] = "industry"
        # Sector (sometimes provided separately)
        elif lower in ("sector", "sectorname", "sector_name", "khoi_nganh"):
            rename[col] = "sector"
        # Exchange
        elif lower in ("exchange", "san_giao_dich", "listing_exchange"):
            rename[col] = "exchange"
        # Market cap
        elif lower in ("market_cap", "marketcap", "market_capitalization", "von_hoa"):
            rename[col] = "market_cap"
        # Employees
        elif lower in ("no_employees", "num_employees", "employees", "so_luong_nv"):
            rename[col] = "no_employees"
        # Established year
        elif lower in ("established_year", "founded_year", "founded", "nam_thanh_lap"):
            rename[col] = "established_year"
        # Website
        elif lower in ("website", "web", "url", "trang_web"):
            rename[col] = "website"
        # Outstanding shares
        elif lower in (
            "outstanding_share",
            "outstanding_shares",
            "listed_share",
            "cp_niem_yet",
        ):
            rename[col] = "outstanding_share"
        # Foreign ownership percent
        elif lower in (
            "foreign_percent",
            "foreign_ownership",
            "foreign_own",
            "ty_le_nn",
        ):
            rename[col] = "foreign_percent"
        # Auditor from KBS profile
        elif lower in ("auditor", "auditor_name", "kiem_toan", "kt"):
            rename[col] = "auditor"

    if rename:
        df = df.rename(rename)

    # Ensure the 'industry' column exists — derive from sector if needed
    if "industry" not in df.columns and "sector" in df.columns:
        df = df.rename({"sector": "industry"})

    return df


def _normalize_officer_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize officer/board member column names to a consistent set."""
    rename: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower()
        # Officer name
        if lower in ("officer_name", "name", "ho_ten", "nguoi_dai_dien"):
            rename[col] = "name"
        # Position
        elif lower in (
            "position",
            "position_en",
            "position_vi",
            "chuc_danh",
            "chuc_vu",
        ):
            rename[col] = "position"
        elif lower in ("officer_position", "officer_position_en"):
            rename[col] = "officer_position"
        # Ownership percent
        elif lower in (
            "own_percent",
            "officer_own_percent",
            "ownership_percent",
            "ty_le_so_huu",
            "share_own_percent",
        ):
            rename[col] = "officer_own_percent"

    if rename:
        df = df.rename(rename)

    return df


def _normalize_shareholder_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize shareholder column names to a consistent set."""
    rename: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower()
        if lower in (
            "share_holder",
            "shareholder",
            "ten_co_dong",
            "co_dong",
            "name",
            "holder_name",
        ):
            rename[col] = "share_holder"
        elif lower in (
            "share_own_percent",
            "stake_percent",
            "ownership_percent",
            "ownership_percentage",
            "ty_le_so_huu",
            "holding_percent",
            "shares_owned",
        ):
            rename[col] = "share_own_percent"

    if rename:
        df = df.rename(rename)

    return df


def _normalize_subsidiary_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize subsidiary column names to a consistent set."""
    rename: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ("sub_name", "name", "company_name", "ten_cong_ty"):
            rename[col] = "name"
        elif lower in ("sub_organ_code", "organ_code", "ticker", "symbol", "ma_cp"):
            rename[col] = "sub_organ_code"
        elif lower in ("ownership_percent", "ownership_perce", "ty_le_so_huu", "pct"):
            rename[col] = "ownership_percent"
        elif lower in ("relation_type", "type", "loai_quan_he"):
            rename[col] = "type"

    if rename:
        df = df.rename(rename)

    # If no type/relation_type column from the API, infer it from ownership_percent
    if "type" not in df.columns and "ownership_percent" in df.columns:
        df = df.with_columns(
            pl.when(pl.col("ownership_percent") > 50)
            .then(pl.lit("công ty con"))
            .otherwise(pl.lit("công ty liên kết"))
            .alias("type"),
        )

    return df


def _normalize_financial_ratio_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize financial ratio column names to a consistent set."""
    rename: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower()
        # Price-to-book
        if lower in ("pb", "pbr", "price_to_book", "price_to_book_ratio"):
            rename[col] = "pb"
        # Price-to-earnings
        elif lower in ("pe", "per", "price_to_earning", "price_to_earning_ratio"):
            rename[col] = "pe"
        # Earnings per share
        elif lower in ("eps", "earning_per_share", "eps_vnd"):
            rename[col] = "eps"
        # Return on equity
        elif lower in ("roe", "return_on_equity", "roe_percent"):
            rename[col] = "roe"
        # Return on assets
        elif lower in ("roa", "return_on_assets", "roa_percent"):
            rename[col] = "roa"
        # Debt-to-equity
        elif lower in ("de", "debt_to_equity", "debt_equity_ratio", "d_e"):
            rename[col] = "debt_to_equity"
        # Current ratio
        elif lower in ("current_ratio", "cr", "current"):
            rename[col] = "current_ratio"
        # Quick ratio
        elif lower in ("quick_ratio", "qr", "quick"):
            rename[col] = "quick_ratio"
        # Gross margin
        elif lower in ("gross_margin", "gross_profit_margin", "gm"):
            rename[col] = "gross_margin"
        # Net margin
        elif lower in ("net_margin", "net_profit_margin", "npm", "profit_margin"):
            rename[col] = "net_margin"
        # Revenue growth
        elif lower in (
            "revenue_growth",
            "revenue_growth_rate",
            "rev_growth",
            "yoy_revenue",
        ):
            rename[col] = "revenue_growth"
        # Dividend yield
        elif lower in ("dividend_yield", "div_yield", "dy"):
            rename[col] = "dividend_yield"
        # Year/quarter identifiers
        elif lower == "year":
            rename[col] = "year"
        elif lower == "quarter":
            rename[col] = "quarter"

    if rename:
        df = df.rename(rename)

    return df


def _unpivot_financial_data(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """Unpivot financial data from VCI/KBS pivoted format to flat rows.

    VCI/KBS returns financial data pivoted:
        item | item_en | item_id | 2026-Q1 | 2025-Q4 | ...

    We need it unpivoted:
        symbol | year | quarter | current_assets | cash | ...
    """
    import re

    if df.is_empty():
        return df

    # Identify quarter columns like "2026-Q1", "2025-Q4", etc.
    q_cols: list[str] = []
    for c in df.columns:
        if re.match(r"^\d{4}-Q[1-4]$", c):
            q_cols.append(c)
        elif re.match(r"^\d{4}-Q[1-4]_", c):
            # KBS sometimes adds suffixes like 2025-Q4_1
            q_cols.append(c)

    if not q_cols:
        logger.debug("No quarter columns found — returning raw data")
        if "symbol" not in df.columns:
            df = df.with_columns(pl.lit(symbol).alias("symbol"))
        return df

    # Identify ID columns (everything that is not a quarter column)
    id_cols = [c for c in df.columns if c not in q_cols]
    if not id_cols:
        return pl.DataFrame()

    # Melt: convert quarter columns into rows
    melted = df.melt(
        id_vars=id_cols, value_vars=q_cols, variable_name="period", value_name="value",
    )

    # Parse year and quarter from period column name
    melted = melted.with_columns(
        pl.col("period").str.replace(r"_.*$", "").alias("period_clean"),
    )
    melted = melted.with_columns(
        [
            pl.col("period_clean")
            .str.split("-Q")
            .list.get(0)
            .cast(pl.Int32)
            .alias("year"),
            pl.col("period_clean")
            .str.split("-Q")
            .list.get(1)
            .cast(pl.Int32)
            .alias("quarter"),
        ],
    )

    # Use item_en if available for readable column names, else item_id, else item
    name_col = (
        "item_en"
        if "item_en" in melted.columns
        else ("item_id" if "item_id" in melted.columns else "item")
    )

    # Pivot: each item becomes a column, each (year, quarter) becomes a row
    pivoted = melted.pivot(
        index=["year", "quarter"],
        columns=name_col,
        values="value",
        aggregate_function="first",
    )

    # Add symbol column
    pivoted = pivoted.with_columns(pl.lit(symbol).alias("symbol"))

    logger.debug(
        "Unpivoted financial data: %d quarters \u00d7 %d metrics for %s",
        len(pivoted),
        len(pivoted.columns) - 3,
        symbol,
    )
    return pivoted


class VnstockFetcher:
    """Fetches all data needed to populate the knowledge graph from vnstock.

    All methods return polars DataFrames.

    Each data method independently tries its configured source, then falls
    back to alternate sources. Failures for one symbol don't affect others.
    No global circuit breaker — if a method can't get data it returns empty.
    """

    def __init__(self, settings: VnstockSettings) -> None:
        self._source = settings.source
        self._delay = settings.effective_delay
        self._last_call: float = 0.0
        _suppress_vnstock_noise()
        _register(settings.api_key)
        logger.info(
            "VnstockFetcher delay=%.1fs (api_key=%s)",
            self._delay,
            bool(settings.api_key),
        )

    def _throttle(self) -> None:
        """Enforce minimum delay between API calls to stay within rate limits."""
        if self._delay <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._delay:
            sleep_for = self._delay - elapsed
            logger.debug("Throttling %.1fs", sleep_for)
            time.sleep(sleep_for)
        self._last_call = time.monotonic()

    # ------------------------------------------------------------------
    # Symbol listing
    # ------------------------------------------------------------------

    def get_vnindex_symbols(self) -> list[str]:  # noqa: C901
        """Return HOSE + HNX ticker symbols (~800 total).

        Uses symbols_by_exchange() which returns all exchanges, then
        filters to HOSE and HNX. Tries KBS first (most reliable),
        then VCI, then MSN.
        """
        from vnstock import Listing  # type: ignore[import]

        for src in ["KBS", "VCI", "MSN"]:
            try:
                listing = Listing(source=src)
                symbols: list[str] = []

                # vnstock 4.x: symbols_by_exchange() returns ticker + exchange
                if hasattr(listing, "symbols_by_exchange"):
                    df = listing.symbols_by_exchange()
                    result = _to_polars(df)
                    if not result.is_empty():
                        exchange_col = next(
                            (c for c in result.columns if "exchange" in c.lower()),
                            None,
                        )
                        ticker_col = next(
                            (
                                c
                                for c in result.columns
                                if c.lower() in ("ticker", "symbol")
                            ),
                            None,
                        )
                        if exchange_col and ticker_col:
                            # Filter HOSE symbols
                            hose = result.filter(
                                pl.col(exchange_col).str.to_uppercase() == "HOSE",
                            )
                            if not hose.is_empty():
                                symbols.extend(hose[ticker_col].to_list())

                            # Filter HNX symbols
                            hnx = result.filter(
                                pl.col(exchange_col).str.to_uppercase() == "HNX",
                            )
                            if not hnx.is_empty():
                                symbols.extend(hnx[ticker_col].to_list())

                            if symbols:
                                logger.info(
                                    "Resolved %d symbols (HOSE+HNX) via %s symbols_by_exchange",
                                    len(symbols),
                                    src,
                                )
                                return symbols

                # vnstock 3.x / fallback: all_symbols() with exchange filter
                df = listing.all_symbols()
                result = _to_polars(df)
                if not result.is_empty():
                    exchange_col = next(
                        (c for c in result.columns if "exchange" in c.lower()),
                        None,
                    )
                    ticker_col = next(
                        (
                            c
                            for c in result.columns
                            if c.lower() in ("ticker", "symbol")
                        ),
                        None,
                    )
                    if exchange_col and ticker_col:
                        # Filter HOSE and HNX
                        filtered = result.filter(
                            (pl.col(exchange_col).str.to_uppercase() == "HOSE")
                            | (pl.col(exchange_col).str.to_uppercase() == "HNX"),
                        )
                        if not filtered.is_empty():
                            symbols = filtered[ticker_col].to_list()
                            logger.info(
                                "Resolved %d symbols (HOSE+HNX) via %s all_symbols",
                                len(symbols),
                                src,
                            )
                            return symbols

                    # No exchange column — return all symbols
                    if ticker_col:
                        symbols = result[ticker_col].to_list()
                        logger.warning(
                            "No exchange column found — returning all %d symbols from %s",
                            len(symbols),
                            src,
                        )
                        return symbols

            except (
                TypeError,
                ValueError,
                AttributeError,
                RuntimeError,
                Exception,  # noqa: BLE001
            ) as exc:
                logger.debug("Symbol listing failed via %s: %s", src, exc)
                continue

        logger.error("All symbol listing attempts failed")
        return []

    def get_all_symbols(self) -> pl.DataFrame:
        """Return all listed symbols as a DataFrame (kept for compat)."""
        self._throttle()
        from vnstock import Listing  # type: ignore[import]

        try:
            listing = Listing(source=self._source)
            df = listing.all_symbols()
            result = _to_polars(df)
        except Exception:
            logger.exception("Failed to fetch symbol listing")
            return pl.DataFrame()
        else:
            return result

    # ------------------------------------------------------------------
    # Company overview
    # ------------------------------------------------------------------

    def get_company_overview(self, symbol: str) -> pl.DataFrame:
        """Fetch company overview / profile."""
        self._throttle()
        from vnstock import Company  # type: ignore[import]

        sources = [self._source]
        if self._source != "VCI":
            sources.append("VCI")
        if self._source != "KBS":
            sources.append("KBS")
        for src in sources:
            try:
                company = Company(symbol=symbol, source=src)
                df = company.overview()
                result = _to_polars(df)
                if not result.is_empty():
                    result = result.with_columns(pl.lit(symbol).alias("symbol"))
                    return _normalize_company_columns(result)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Company overview failed for %s via %s",
                    symbol,
                    src,
                    exc_info=True,
                )
        return pl.DataFrame()

    def get_officers(self, symbol: str) -> pl.DataFrame:
        """Fetch current company officers / board members.

        KBS source returns all officers (no filter_by support).
        VCI source supports filter_by='working'|'resigned'|'all'.
        """
        self._throttle()
        from vnstock import Company  # type: ignore[import]

        sources = [self._source]
        if self._source != "VCI":
            sources.append("VCI")
        if self._source != "KBS":
            sources.append("KBS")

        for src in sources:
            try:
                company = Company(symbol=symbol, source=src)
                if src.upper() == "VCI":
                    df = company.officers(filter_by="working")
                else:
                    df = company.officers()
                result = _to_polars(df)
                if not result.is_empty():
                    return _normalize_officer_columns(result)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Officers fetch failed for %s via %s",
                    symbol,
                    src,
                    exc_info=True,
                )
                continue

        return pl.DataFrame()

    def get_shareholders(self, symbol: str) -> pl.DataFrame:
        """Fetch major shareholders. VCI provides more entries than KBS."""
        self._throttle()
        from vnstock import Company  # type: ignore[import]

        sources = [self._source]
        if self._source != "VCI":
            sources.append("VCI")
        if self._source != "KBS":
            sources.append("KBS")

        for src in sources:
            try:
                company = Company(symbol=symbol, source=src)
                df = company.shareholders()
                result = _to_polars(df)
                if not result.is_empty():
                    normalized = _normalize_shareholder_columns(result)
                    # KBS sometimes returns rows with null shareholder names;
                    # drop those and fall through to next source if all empty.
                    if "share_holder" in normalized.columns:
                        non_null = normalized.filter(
                            pl.col("share_holder").is_not_null()
                            & (pl.col("share_holder").cast(pl.Utf8) != ""),
                        )
                        if not non_null.is_empty():
                            return non_null
                    else:
                        return normalized
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Shareholders fetch failed for %s via %s",
                    symbol,
                    src,
                    exc_info=True,
                )
                continue

        return pl.DataFrame()

    def get_subsidiaries(self, symbol: str) -> pl.DataFrame:
        """Fetch subsidiaries and associated companies. VCI provides more entries."""
        self._throttle()
        from vnstock import Company  # type: ignore[import]

        sources = [self._source]
        if self._source != "VCI":
            sources.append("VCI")
        if self._source != "KBS":
            sources.append("KBS")

        for src in sources:
            try:
                company = Company(symbol=symbol, source=src)
                df = company.subsidiaries()
                result = _to_polars(df)
                if not result.is_empty():
                    return _normalize_subsidiary_columns(result)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Subsidiaries fetch failed for %s via %s",
                    symbol,
                    src,
                    exc_info=True,
                )
                continue

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
        """Fetch OHLCV price history."""
        self._throttle()
        from vnstock import Quote  # type: ignore[import]

        current_date = datetime.now(UTC).date()
        if end is None:
            end = current_date.isoformat()
        if start is None:
            start = (current_date - timedelta(days=730)).isoformat()

        sources = [self._source]
        if self._source != "VCI":
            sources.append("VCI")
        if self._source != "KBS":
            sources.append("KBS")

        for src in sources:
            try:
                quote = Quote(symbol=symbol, source=src)
                df = quote.history(start=start, end=end, interval=interval)
                result = _to_polars(df)
                if not result.is_empty():
                    if "symbol" not in result.columns:
                        result = result.with_columns(pl.lit(symbol).alias("symbol"))
                    return result
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Price history fetch failed for %s via %s",
                    symbol,
                    src,
                    exc_info=True,
                )
                continue

        return pl.DataFrame()

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    def get_balance_sheet(self, symbol: str, period: str = "quarter") -> pl.DataFrame:
        self._throttle()
        return self._get_financial(symbol, "balance_sheet", period)

    def get_income_statement(
        self,
        symbol: str,
        period: str = "quarter",
    ) -> pl.DataFrame:
        self._throttle()
        return self._get_financial(symbol, "income_statement", period)

    def get_cash_flow(self, symbol: str, period: str = "quarter") -> pl.DataFrame:
        self._throttle()
        return self._get_financial(symbol, "cash_flow", period)

    def get_financial_ratios(
        self,
        symbol: str,
        period: str = "quarter",
    ) -> pl.DataFrame:
        self._throttle()
        df = self._get_financial(symbol, "ratio", period)
        if not df.is_empty():
            return _normalize_financial_ratio_columns(df)
        return df

    # ------------------------------------------------------------------
    # VCI Events (Phase 1b)
    # ------------------------------------------------------------------

    def get_events(self, symbol: str) -> pl.DataFrame:
        """Fetch corporate action events (dividends, issuances, meetings, M&A).

        Uses VCI source which provides event types:
        - DIV (dividend) — ex-right and payment dates
        - ISS (issuance) — new share issuances
        - AGME (meeting) — shareholder meetings
        - MA (M&A) — mergers and acquisitions

        Returns polars DataFrame with columns: event_code, event_name,
        public_date, record_date, exright_date.
        """
        self._throttle()
        from vnstock import Company  # type: ignore[import]

        # VCI is the only source that reliably provides events
        try:
            company = Company(symbol=symbol, source="VCI")
            df = company.events()
            result = _to_polars(df)
            if not result.is_empty():
                result = result.with_columns(pl.lit(symbol).alias("symbol"))
            return result
        except Exception:  # noqa: BLE001
            logger.debug(
                "Events fetch failed for %s via VCI",
                symbol,
                exc_info=True,
            )
        return pl.DataFrame()

    def _get_financial(self, symbol: str, statement: str, period: str) -> pl.DataFrame:
        from vnstock import Finance  # type: ignore[import]

        sources = [self._source]
        if self._source != "VCI":
            sources.append("VCI")
        if self._source != "KBS":
            sources.append("KBS")

        for src in sources:
            try:
                finance = Finance(symbol=symbol, source=src)
                method = getattr(finance, statement)
                df = method(period=period)
                result = _to_polars(df)
                if not result.is_empty():
                    # Unpivot the pivoted VCI/KBS format into flat rows
                    result = _unpivot_financial_data(result, symbol)
                    if not result.is_empty() and "symbol" not in result.columns:
                        result = result.with_columns(pl.lit(symbol).alias("symbol"))
                    return result
            except Exception:  # noqa: BLE001
                logger.debug(
                    "%s/%s fetch failed for %s via %s",
                    statement,
                    period,
                    symbol,
                    src,
                    exc_info=True,
                )
                continue

        return pl.DataFrame()
