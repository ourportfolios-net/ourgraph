"""Tests for the data pipeline (unit — no real DB or API calls)."""

from __future__ import annotations

import polars as pl

from ourgraph.ingest.pipeline import Pipeline


def _make_settings(tmp_path=None):
    """Create a minimal AppSettings for testing."""
    from ourgraph.config import AppSettings

    return AppSettings()


def test_pipeline_batches():
    settings = _make_settings()
    pipeline = Pipeline(settings)
    pipeline._settings.pipeline.batch_size = 3

    items = list(range(10))
    batches = pipeline._batches(items)
    assert len(batches) == 4
    assert batches[0] == [0, 1, 2]
    assert batches[-1] == [9]


def test_normalise_price_df_renames_time():
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
        }
    )
    result = pipeline._normalise_price_df(df, "VCB")
    assert "date" in result.columns
    assert "symbol" in result.columns
    assert "time" not in result.columns


def test_normalise_price_df_no_rename_needed():
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
        }
    )
    result = pipeline._normalise_price_df(df, "VCB")
    assert "date" in result.columns
    assert result["symbol"][0] == "VCB"


def test_supabase_fetcher_graceful_without_url():
    from ourgraph.config import SupabaseSettings
    from ourgraph.ingest.supabase_fetcher import SupabaseFetcher

    settings = SupabaseSettings(db_url="")
    fetcher = SupabaseFetcher(settings)

    # All methods should return empty DataFrames, not raise
    assert fetcher.get_all_symbols() == []
    assert fetcher.get_company_overview().is_empty()
    assert fetcher.get_price_history("VCB").is_empty()
    assert fetcher.get_stats().is_empty()
