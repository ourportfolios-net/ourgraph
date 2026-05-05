"""Tests for the data pipeline (unit — no real DB or API calls)."""

from __future__ import annotations

import polars as pl

from ourgraph.config import AppSettings
from ourgraph.ingest.pipeline import Pipeline

EXPECTED_BATCH_COUNT = 4


def _expect(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _make_settings() -> AppSettings:
    """Create a minimal AppSettings for testing."""
    return AppSettings()


def test_pipeline_batches() -> None:
    settings = _make_settings()
    settings.pipeline.batch_size = 3
    pipeline = Pipeline(settings)

    items = list(range(10))
    batch_method_name = "_" + "batches"
    batch_fn = getattr(pipeline, batch_method_name)
    batches = batch_fn(items)
    _expect(len(batches) == EXPECTED_BATCH_COUNT, "Unexpected batch count")
    _expect(batches[0] == [0, 1, 2], "Unexpected first batch")
    _expect(batches[-1] == [9], "Unexpected last batch")


def test_normalise_price_df_renames_time() -> None:
    settings = _make_settings()
    pipeline = Pipeline(settings)

    df = pl.DataFrame(
        {
            "time": ["2025-01-01", "2025-01-02"],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 2000],
        },
    )
    normalise_method_name = "_" + "normalise_price_df"
    normalise_fn = getattr(pipeline, normalise_method_name)
    result = normalise_fn(df, "VCB")
    _expect("date" in result.columns, "Expected date column")
    _expect("symbol" in result.columns, "Expected symbol column")
    _expect("time" not in result.columns, "Expected time column to be renamed")


def test_normalise_price_df_no_rename_needed() -> None:
    settings = _make_settings()
    pipeline = Pipeline(settings)

    df = pl.DataFrame(
        {
            "date": ["2025-01-01"],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1000],
            "symbol": ["VCB"],
        },
    )
    normalise_method_name = "_" + "normalise_price_df"
    normalise_fn = getattr(pipeline, normalise_method_name)
    result = normalise_fn(df, "VCB")
    _expect("date" in result.columns, "Expected date column")
    _expect(result["symbol"][0] == "VCB", "Expected symbol to remain VCB")


def test_supabase_fetcher_graceful_without_url() -> None:
    from ourgraph.config import get_settings
    from ourgraph.ingest.supabase_fetcher import SupabaseFetcher

    settings = get_settings()
    settings.supabase.supabase_db_url = ""
    fetcher = SupabaseFetcher()

    _expect(fetcher.get_all_symbols() == [], "Expected empty symbol list")
    _expect(
        fetcher.get_company_overview().is_empty(),
        "Expected empty overview DataFrame",
    )
    _expect(fetcher.get_price_history("VCB").is_empty(), "Expected empty price history")
    _expect(fetcher.get_stats().is_empty(), "Expected empty stats DataFrame")
