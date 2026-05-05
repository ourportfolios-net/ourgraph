"""
SQLAlchemy ORM models for the Supabase schema.

Every table in the schema is modelled here.
The models are the single source of truth for column names and types —
no string literals scattered across query files.

Schema reference (from your Supabase SQL dump):
  tickers.*        — company, price, ratios, officers, shareholders
  market.*         — indices, vnindex, daily/weekly/monthly/quarterly/yearly changes
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ===========================================================================
# tickers schema
# ===========================================================================


class OverviewORM(Base):
    """tickers.overview_df — master company reference table."""

    __tablename__ = "overview_df"
    __table_args__ = {"schema": "tickers"}

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    exchange: Mapped[str | None] = mapped_column(String)
    industry: Mapped[str | None] = mapped_column(String)
    no_shareholders: Mapped[int | None] = mapped_column(BigInteger)
    foreign_percent: Mapped[float | None] = mapped_column(Double)
    outstanding_share: Mapped[float | None] = mapped_column(Double)
    issue_share: Mapped[float | None] = mapped_column(Double)
    established_year: Mapped[str | None] = mapped_column(String)
    no_employees: Mapped[int | None] = mapped_column(BigInteger)
    short_name: Mapped[str | None] = mapped_column(String)
    website: Mapped[str | None] = mapped_column(String)
    market_cap: Mapped[int | None] = mapped_column(BigInteger)


class PriceORM(Base):
    """tickers.price_df — latest intraday price snapshot."""

    __tablename__ = "price_df"
    __table_args__ = {"schema": "tickers"}

    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), primary_key=True
    )
    current_price: Mapped[float | None] = mapped_column(Double)
    price_change: Mapped[float | None] = mapped_column(Double)
    pct_price_change: Mapped[float | None] = mapped_column(Double)
    accumulated_volume: Mapped[int | None] = mapped_column(BigInteger)


class PriceHistoryORM(Base):
    """tickers.price_history — daily OHLCV history."""

    __tablename__ = "price_history"
    __table_args__ = {"schema": "tickers"}

    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Double)
    high: Mapped[float | None] = mapped_column(Double)
    low: Mapped[float | None] = mapped_column(Double)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)


class ProfileORM(Base):
    """tickers.profile_df — company narrative / qualitative profile."""

    __tablename__ = "profile_df"
    __table_args__ = {"schema": "tickers"}

    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), primary_key=True
    )
    company_name: Mapped[str | None] = mapped_column(Text)
    company_profile: Mapped[str | None] = mapped_column(Text)
    history_dev: Mapped[str | None] = mapped_column(Text)
    company_promise: Mapped[str | None] = mapped_column(Text)
    business_risk: Mapped[str | None] = mapped_column(Text)
    key_developments: Mapped[str | None] = mapped_column(Text)
    business_strategies: Mapped[str | None] = mapped_column(Text)


class StatsORM(Base):
    """tickers.stats_df — current financial ratios and market stats."""

    __tablename__ = "stats_df"
    __table_args__ = {"schema": "tickers"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str | None] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol")
    )
    roe: Mapped[float | None] = mapped_column(Double)
    roa: Mapped[float | None] = mapped_column(Double)
    ev_ebitda: Mapped[float | None] = mapped_column(Double)
    dividend_yield: Mapped[float | None] = mapped_column(Double)
    gross_margin: Mapped[float | None] = mapped_column(Double)
    net_margin: Mapped[float | None] = mapped_column(Double)
    doe: Mapped[float | None] = mapped_column(Double)
    alpha: Mapped[float | None] = mapped_column(Double)
    beta: Mapped[float | None] = mapped_column(Double)
    pe: Mapped[float | None] = mapped_column(Double)
    pb: Mapped[float | None] = mapped_column(Double)
    eps: Mapped[int | None] = mapped_column(BigInteger)
    ps: Mapped[float | None] = mapped_column(Double)
    ev: Mapped[float | None] = mapped_column(Double)
    rsi14: Mapped[float | None] = mapped_column(Double)


class RatioQuarterlyORM(Base):
    """tickers.ratio_quarterly — quarterly financial ratios (long format)."""

    __tablename__ = "ratio_quarterly"
    __table_args__ = {"schema": "tickers"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class RatioYearlyORM(Base):
    """tickers.ratio_yearly — annual financial ratios (long format)."""

    __tablename__ = "ratio_yearly"
    __table_args__ = {"schema": "tickers"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class ShareholdersORM(Base):
    """tickers.shareholders_df — major shareholder registry."""

    __tablename__ = "shareholders_df"
    __table_args__ = {"schema": "tickers"}

    # Composite PK synthesised from available columns (no natural PK in schema)
    share_holder: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), primary_key=True
    )
    share_own_percent: Mapped[float | None] = mapped_column(Double)


class OfficersORM(Base):
    """tickers.officers_df — board members and executives."""

    __tablename__ = "officers_df"
    __table_args__ = {"schema": "tickers"}

    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), primary_key=True
    )
    officer_name: Mapped[str] = mapped_column(String, primary_key=True)
    officer_position: Mapped[str | None] = mapped_column(String)
    officer_own_percent: Mapped[float | None] = mapped_column(Double)


class EventsORM(Base):
    """tickers.events_df — corporate events affecting price."""

    __tablename__ = "events_df"
    __table_args__ = {"schema": "tickers"}

    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), primary_key=True
    )
    event_name: Mapped[str] = mapped_column(String, primary_key=True)
    price_change_ratio: Mapped[float | None] = mapped_column(Double)
    event_desc: Mapped[str | None] = mapped_column(Text)


class NewsORM(Base):
    """tickers.news_df — news headlines with price impact."""

    __tablename__ = "news_df"
    __table_args__ = {"schema": "tickers"}

    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.overview_df.symbol"), primary_key=True
    )
    title: Mapped[str] = mapped_column(String, primary_key=True)
    publish_date: Mapped[str | None] = mapped_column(String)
    price_change_ratio: Mapped[float | None] = mapped_column(Double)


# ===========================================================================
# market schema
# ===========================================================================


class VNIndexORM(Base):
    """market.vnindex — VNINDEX OHLCV time series."""

    __tablename__ = "vnindex"
    __table_args__ = {"schema": "market"}

    time: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    open: Mapped[float | None] = mapped_column(Double)
    high: Mapped[float | None] = mapped_column(Double)
    low: Mapped[float | None] = mapped_column(Double)
    close: Mapped[float | None] = mapped_column(Double)
    volume: Mapped[int | None] = mapped_column(BigInteger)


class DailyChangesORM(Base):
    """market.daily_changes — daily performance snapshot per ticker."""

    __tablename__ = "daily_changes"
    __table_args__ = {"schema": "market"}

    symbol: Mapped[str] = mapped_column(
        String,
        ForeignKey("tickers.overview_df.symbol"),
        primary_key=True,
    )
    industry: Mapped[str | None] = mapped_column(String)
    period_end: Mapped[date | None] = mapped_column(Date)
    close: Mapped[float | None] = mapped_column(Double)
    prior_close: Mapped[float | None] = mapped_column(Double)
    pct_change: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    market_cap: Mapped[float | None] = mapped_column(Numeric)
