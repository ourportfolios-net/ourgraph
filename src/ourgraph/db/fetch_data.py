"""
Database query functions — all return polars DataFrames.

Uses SQLAlchemy ORM selects (not raw text SQL).
Async variants are provided for pipeline use; sync variants for CLI / one-off use.

Polars is built directly from SQLAlchemy result rows — no pandas intermediate.
"""

from __future__ import annotations

import decimal
import logging
from datetime import date

import polars as pl
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from ourgraph.db.engine import get_neon_session, get_session, sync_engine
from ourgraph.db.models import (
    OfficersORM,
    OverviewORM,
    PriceHistoryORM,
    RatioQuarterlyORM,
    ShareholdersORM,
    StatsORM,
)

logger = logging.getLogger(__name__)

_STATEMENT_QUERIES = {
    "income_statement": {
        "year": text("""
            SELECT year, metric, value
            FROM financial_statements.income_statement_yearly
            WHERE symbol = :symbol
            ORDER BY year DESC
        """),
        "quarter": text("""
            SELECT year, quarter, metric, value
            FROM financial_statements.income_statement_quarterly
            WHERE symbol = :symbol
            ORDER BY year DESC, quarter DESC
        """),
    },
    "balance_sheet": {
        "year": text("""
            SELECT year, metric, value
            FROM financial_statements.balance_sheet_yearly
            WHERE symbol = :symbol
            ORDER BY year DESC
        """),
        "quarter": text("""
            SELECT year, quarter, metric, value
            FROM financial_statements.balance_sheet_quarterly
            WHERE symbol = :symbol
            ORDER BY year DESC, quarter DESC
        """),
    },
    "cash_flow": {
        "year": text("""
            SELECT year, metric, value
            FROM financial_statements.cash_flow_yearly
            WHERE symbol = :symbol
            ORDER BY year DESC
        """),
        "quarter": text("""
            SELECT year, quarter, metric, value
            FROM financial_statements.cash_flow_quarterly
            WHERE symbol = :symbol
            ORDER BY year DESC, quarter DESC
        """),
    },
}


def _clean_val(v):
    if isinstance(v, decimal.Decimal):
        return float(v) if v is not None else None
    return v


def _orm_to_polars(rows: list, model_class) -> pl.DataFrame:
    """
    Convert a list of ORM instances to a polars DataFrame.

    Extracts only mapped column names — skips SQLAlchemy internal attributes.
    """
    if not rows:
        return pl.DataFrame()

    col_names = [c.key for c in model_class.__mapper__.columns]
    data = {col: [getattr(row, col, None) for row in rows] for col in col_names}
    return pl.DataFrame(data)


# ===========================================================================
# Sync queries (for CLI / scheduler bootstrap)
# ===========================================================================


def fetch_all_symbols() -> list[str]:
    """Return all symbols from tickers.overview_df."""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(select(OverviewORM.symbol))
            return [row[0] for row in result.fetchall()]
    except SQLAlchemyError as exc:
        logger.warning("fetch_all_symbols failed: %s", exc)
        return []


def fetch_overview_all() -> pl.DataFrame:
    """Return full tickers.overview_df as a polars DataFrame."""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(select(*OverviewORM.__table__.columns))
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_overview_all failed: %s", exc)
        return pl.DataFrame()


def fetch_price_history_sync(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
) -> pl.DataFrame:
    """Return OHLCV rows from tickers.price_history for one symbol."""
    try:
        stmt = select(*PriceHistoryORM.__table__.columns).where(
            PriceHistoryORM.symbol == symbol
        )
        if start:
            stmt = stmt.where(PriceHistoryORM.date >= start)
        if end:
            stmt = stmt.where(PriceHistoryORM.date <= end)
        stmt = stmt.order_by(PriceHistoryORM.date)

        with sync_engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_price_history_sync(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


def fetch_ratio_quarterly_sync(symbol: str) -> pl.DataFrame:
    """Return tickers.ratio_quarterly rows for one symbol."""
    try:
        stmt = (
            select(*RatioQuarterlyORM.__table__.columns)
            .where(RatioQuarterlyORM.symbol == symbol)
            .order_by(RatioQuarterlyORM.year.desc(), RatioQuarterlyORM.quarter.desc())
        )
        with sync_engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_ratio_quarterly_sync(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


def fetch_officers_sync(symbol: str) -> pl.DataFrame:
    """Return tickers.officers_df rows for one symbol."""
    try:
        stmt = select(*OfficersORM.__table__.columns).where(
            OfficersORM.symbol == symbol
        )
        with sync_engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_officers_sync(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


def fetch_shareholders_sync(symbol: str) -> pl.DataFrame:
    """Return tickers.shareholders_df rows for one symbol."""
    try:
        stmt = select(*ShareholdersORM.__table__.columns).where(
            ShareholdersORM.symbol == symbol
        )
        with sync_engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_shareholders_sync(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


def fetch_stats_sync(symbol: str | None = None) -> pl.DataFrame:
    """Return tickers.stats_df, optionally filtered to one symbol."""
    try:
        stmt = select(*StatsORM.__table__.columns)
        if symbol:
            stmt = stmt.where(StatsORM.symbol == symbol)
        with sync_engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_stats_sync(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


# ===========================================================================
# Async queries (for the ETL pipeline)
# ===========================================================================


async def fetch_all_symbols_async() -> list[str]:
    """Return all symbols from tickers.overview_df (async)."""
    try:
        async with get_session() as session:
            result = await session.execute(select(OverviewORM.symbol))
            return [row[0] for row in result.fetchall()]
    except SQLAlchemyError as exc:
        logger.warning("fetch_all_symbols_async failed: %s", exc)
        return []


async def fetch_overview_async() -> pl.DataFrame:
    """Return full tickers.overview_df as a polars DataFrame (async)."""
    try:
        async with get_session() as session:
            result = await session.execute(select(*OverviewORM.__table__.columns))
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_overview_async failed: %s", exc)
        return pl.DataFrame()


async def fetch_price_history_async(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
) -> pl.DataFrame:
    """Return OHLCV rows from tickers.price_history (async)."""
    try:
        stmt = select(*PriceHistoryORM.__table__.columns).where(
            PriceHistoryORM.symbol == symbol
        )
        if start:
            stmt = stmt.where(PriceHistoryORM.date >= start)
        if end:
            stmt = stmt.where(PriceHistoryORM.date <= end)
        stmt = stmt.order_by(PriceHistoryORM.date)

        async with get_session() as session:
            result = await session.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_price_history_async(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


async def fetch_ratio_quarterly_async(symbol: str) -> pl.DataFrame:
    """Return tickers.ratio_quarterly rows (async)."""
    try:
        stmt = (
            select(*RatioQuarterlyORM.__table__.columns)
            .where(RatioQuarterlyORM.symbol == symbol)
            .order_by(RatioQuarterlyORM.year.desc(), RatioQuarterlyORM.quarter.desc())
        )
        async with get_session() as session:
            result = await session.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_ratio_quarterly_async(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


async def fetch_officers_async(symbol: str) -> pl.DataFrame:
    """Return tickers.officers_df rows (async)."""
    try:
        stmt = select(*OfficersORM.__table__.columns).where(
            OfficersORM.symbol == symbol
        )
        async with get_session() as session:
            result = await session.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_officers_async(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


async def fetch_financial_statement_async(
    statement_name: str, symbol: str, period: str
) -> pl.DataFrame:
    """Return financial statement from Neon, pivoted on year/quarter (async)."""
    query = _STATEMENT_QUERIES.get(statement_name, {}).get(period)
    if query is None:
        logger.warning(
            "fetch_financial_statement_async failed: Unknown statement %s",
            statement_name,
        )
        return pl.DataFrame()

    try:
        async with get_neon_session() as session:
            result = await session.execute(query, {"symbol": symbol})
            rows = result.fetchall()
            col_names = list(result.keys())
            if not rows:
                return pl.DataFrame()
            df = pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
            if period == "quarter":
                df = df.pivot(
                    index=["year", "quarter"], on="metric", values="value"
                ).sort(["year", "quarter"], descending=True)
            else:
                df = df.pivot(index=["year"], on="metric", values="value").sort(
                    ["year"], descending=True
                )
            return df
    except SQLAlchemyError as exc:
        logger.warning("fetch_financial_statement_async(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


async def fetch_shareholders_async(symbol: str) -> pl.DataFrame:
    """Return tickers.shareholders_df rows (async)."""
    try:
        stmt = select(*ShareholdersORM.__table__.columns).where(
            ShareholdersORM.symbol == symbol
        )
        async with get_session() as session:
            result = await session.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_shareholders_async(%s) failed: %s", symbol, exc)
        return pl.DataFrame()


async def fetch_stats_async(symbol: str | None = None) -> pl.DataFrame:
    """Return tickers.stats_df, optionally filtered (async)."""
    try:
        stmt = select(*StatsORM.__table__.columns)
        if symbol:
            stmt = stmt.where(StatsORM.symbol == symbol)
        async with get_session() as session:
            result = await session.execute(stmt)
            rows = result.fetchall()
            col_names = list(result.keys())
            return pl.DataFrame(
                {
                    col: [_clean_val(row[i]) for row in rows]
                    for i, col in enumerate(col_names)
                }
            )
    except SQLAlchemyError as exc:
        logger.warning("fetch_stats_async(%s) failed: %s", symbol, exc)
        return pl.DataFrame()
