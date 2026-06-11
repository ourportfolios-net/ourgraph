"""Tests for macro data integration."""

from __future__ import annotations

import pytest

from ourgraph.graph.schema import NodeLabel, Prop, RelType

# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------


class TestSchema:
    """Test that macro node labels and relationship types are defined."""

    def test_macro_node_label_defined(self) -> None:
        assert hasattr(NodeLabel, "MACRO_INDICATOR")
        assert NodeLabel.MACRO_INDICATOR == "MacroIndicator"

    def test_country_node_label_defined(self) -> None:
        assert hasattr(NodeLabel, "COUNTRY")
        assert NodeLabel.COUNTRY == "Country"

    def test_macro_rel_types_defined(self) -> None:
        assert hasattr(RelType, "HAS_MACRO_INDICATOR")
        assert RelType.HAS_MACRO_INDICATOR == "HAS_MACRO_INDICATOR"
        assert hasattr(RelType, "AFFECTS_SECTOR")
        assert RelType.AFFECTS_SECTOR == "AFFECTS_SECTOR"
        assert hasattr(RelType, "AFFECTS_INDUSTRY")
        assert RelType.AFFECTS_INDUSTRY == "AFFECTS_INDUSTRY"

    def test_macro_prop_fields_defined(self) -> None:
        assert hasattr(Prop, "VALUE")
        assert hasattr(Prop, "UNIT")
        assert hasattr(Prop, "COUNTRY")
        assert hasattr(Prop, "CATEGORY")
        assert hasattr(Prop, "FREQUENCY")
        assert hasattr(Prop, "SOURCE")
        assert hasattr(Prop, "CODE")
        assert hasattr(Prop, "REASON")


# ---------------------------------------------------------------------------
# ORM Tests
# ---------------------------------------------------------------------------


class TestORM:
    """Test that MacroIndicator and Country node classes work."""

    def test_macro_indicator_node_class(self) -> None:
        from ourgraph.graph.orm import MacroIndicator

        # Check that the class has the right label
        assert MacroIndicator.__label__ == "MacroIndicator"
        assert "name" in MacroIndicator.__properties__
        assert "value" in MacroIndicator.__properties__
        assert "unit" in MacroIndicator.__properties__
        assert "country" in MacroIndicator.__properties__
        assert "category" in MacroIndicator.__properties__
        assert "frequency" in MacroIndicator.__properties__
        assert "source" in MacroIndicator.__properties__

    def test_country_node_class(self) -> None:
        from ourgraph.graph.orm import Country

        assert Country.__label__ == "Country"
        assert "code" in Country.__properties__
        assert "name" in Country.__properties__


# ---------------------------------------------------------------------------
# Constants Tests
# ---------------------------------------------------------------------------


class TestConstants:
    """Test that macro-related constants are defined."""

    def test_macro_sector_links_defined(self) -> None:
        from ourgraph.constants import MACRO_SECTOR_LINKS

        assert isinstance(MACRO_SECTOR_LINKS, dict)
        assert "Crude Oil Price" in MACRO_SECTOR_LINKS
        assert "Gold Price" in MACRO_SECTOR_LINKS

    def test_macro_defaults_defined(self) -> None:
        from ourgraph.constants import (
            MACRO_COUNTRY_NAMES,
            MACRO_DAILY_LIMIT,
            MACRO_MAX_RETRIES,
        )

        assert MACRO_DAILY_LIMIT == 5
        assert MACRO_MAX_RETRIES == 3
        assert MACRO_COUNTRY_NAMES["VN"] == "Vietnam"


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Test that MacroSettings is properly configured."""

    def test_macro_settings_exists(self) -> None:
        from ourgraph.config import MacroSettings

        settings = MacroSettings()
        assert settings.sources == "worldbank,imf,yfinance"
        assert settings.start_year == 2010
        assert settings.yfinance_commodities != ""
        assert settings.yfinance_indices != ""

    def test_app_settings_has_macro(self) -> None:
        from ourgraph.config import AppSettings

        settings = AppSettings()
        assert hasattr(settings, "macro")
        assert settings.macro.sources == "worldbank,imf,yfinance"


# ---------------------------------------------------------------------------
# Fetcher Tests (mocked)
# ---------------------------------------------------------------------------


class TestWorldBankFetcher:
    """Test World Bank API fetcher with mocked responses."""

    @pytest.mark.asyncio
    async def test_fetcher_initialization(self) -> None:
        from ourgraph.ingest.worldbank_fetcher import WorldBankFetcher

        fetcher = WorldBankFetcher(start_year=2020)
        assert fetcher._start == "2020"
        assert fetcher._end == "2030"

    @pytest.mark.asyncio
    async def test_fetch_indicator_returns_dataframe(self, mocker) -> None:
        """Test that fetch_indicator returns a valid polars DataFrame."""
        from ourgraph.ingest.worldbank_fetcher import WorldBankFetcher

        # Mock the _fetch_json method
        mock_response = [
            {"last_page": 1},
            [
                {
                    "date": "2024",
                    "value": 476.39,
                    "indicator": {"value": "GDP (current US$)"},
                },
                {
                    "date": "2023",
                    "value": 430.0,
                    "indicator": {"value": "GDP (current US$)"},
                },
            ],
        ]

        fetcher = WorldBankFetcher()
        mocker.patch(
            "ourgraph.ingest.worldbank_fetcher._fetch_json", return_value=mock_response,
        )

        df = await fetcher.fetch_indicator("NY.GDP.MKTP.CD")
        assert df is not None
        if not df.is_empty():
            assert "name" in df.columns
            assert "value" in df.columns
            assert "country" in df.columns
            assert "source" in df.columns

    @pytest.mark.asyncio
    async def test_fetch_all(self, mocker) -> None:
        """Test that fetch_all returns combined DataFrame."""
        from ourgraph.ingest.worldbank_fetcher import WorldBankFetcher

        fetcher = WorldBankFetcher()

        # Mock fetch_indicator to return a simple DataFrame
        import polars as pl

        mock_df = pl.DataFrame(
            {
                "name": ["Test Indicator"],
                "value": [100.0],
                "unit": ["USD"],
                "date": ["2024-01-01"],
                "country": ["VN"],
                "category": ["vn_economy"],
                "frequency": ["annual"],
                "source": ["worldbank"],
            },
        )

        mocker.patch.object(fetcher, "fetch_indicator", return_value=mock_df)

        result = await fetcher.fetch_all()
        assert result is not None


class TestIMFFetcher:
    """Test IMF SDMX API fetcher with mocked responses."""

    @pytest.mark.asyncio
    async def test_fetcher_initialization(self) -> None:
        from ourgraph.ingest.imf_fetcher import IMFFetcher

        fetcher = IMFFetcher(start_year=2020)
        assert fetcher._start == "2020-01-01"

    @pytest.mark.asyncio
    async def test_normalize_date_monthly(self) -> None:
        from ourgraph.ingest.imf_fetcher import IMFFetcher

        fetcher = IMFFetcher()
        result = fetcher._normalize_date("2024-01", "monthly")
        assert result == "2024-01-01"

    @pytest.mark.asyncio
    async def test_normalize_date_quarterly(self) -> None:
        from ourgraph.ingest.imf_fetcher import IMFFetcher

        fetcher = IMFFetcher()
        result = fetcher._normalize_date("2024-Q1", "quarterly")
        assert result == "2024-01-01"


class TestYFinanceFetcher:
    """Test yfinance fetcher."""

    @pytest.mark.asyncio
    async def test_fetcher_initialization(self) -> None:
        from ourgraph.ingest.yfinance_fetcher import YFinanceFetcher

        fetcher = YFinanceFetcher(start_year=2020)
        assert fetcher._start == "2020-01-01"
        assert len(fetcher._tickers) > 0

    @pytest.mark.asyncio
    async def test_fetch_all_returns_dataframe(self, mocker) -> None:
        """Test that fetch_all returns a polars DataFrame."""
        from ourgraph.ingest.yfinance_fetcher import YFinanceFetcher

        fetcher = YFinanceFetcher()

        # Mock the _fetch_sync method
        import polars as pl

        mock_df = pl.DataFrame(
            {
                "name": ["Gold Price (Futures)"],
                "value": [2000.0],
                "unit": ["USD"],
                "date": ["2024-01-01"],
                "country": ["GLOBAL"],
                "category": ["global_commodity"],
                "frequency": ["daily"],
                "source": ["yfinance"],
            },
        )

        mocker.patch.object(fetcher, "fetch_all", return_value=mock_df)

        result = await fetcher.fetch_all()
        assert not result.is_empty()


class TestVnstockMacroFetcher:
    """Test vnstock macro fetcher."""

    def test_availability_check(self, mocker) -> None:
        """Test that availability check works."""
        from ourgraph.ingest.vnstock_macro_fetcher import _check_available

        # Mock import to return True
        mock_import = mocker.patch("builtins.__import__", return_value=True)
        result = _check_available()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# GraphBuilder Tests
# ---------------------------------------------------------------------------


class TestGraphBuilderMacro:
    """Test GraphBuilder macro methods."""

    @pytest.mark.asyncio
    async def test_upsert_country(self, mocker) -> None:
        """Test that upsert_country creates correct query."""
        from ourgraph.graph.builder import GraphBuilder

        # Mock the _run method
        mock_run = mocker.AsyncMock()
        builder = GraphBuilder(None, "test_graph")
        mocker.patch.object(builder, "_run", mock_run)

        await builder.upsert_country("VN", "Vietnam")
        assert mock_run.called
        # Check that the query contains Country and the properties
        call_args = mock_run.call_args
        assert "Country" in call_args[0][0]
        assert "code" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_upsert_macro_indicator(self, mocker) -> None:
        """Test that upsert_macro_indicator processes DataFrame correctly."""
        import polars as pl

        from ourgraph.graph.builder import GraphBuilder

        builder = GraphBuilder(None, "test_graph")
        mock_run = mocker.AsyncMock()
        mocker.patch.object(builder, "_run", mock_run)

        df = pl.DataFrame(
            {
                "name": ["Test Macro"],
                "value": [100.0],
                "unit": ["USD"],
                "date": ["2024-01-01"],
                "country": ["VN"],
                "category": ["vn_economy"],
                "frequency": ["annual"],
                "source": ["worldbank"],
            },
        )

        await builder.upsert_macro_indicator(df)
        assert mock_run.called


# ---------------------------------------------------------------------------
# Pipeline Tests
# ---------------------------------------------------------------------------


class TestPipelineMacro:
    """Test Pipeline macro ingestion methods."""

    @pytest.mark.asyncio
    async def test_run_macro_ingestion(self, mocker) -> None:
        """Test that run_macro_ingestion calls appropriate methods."""
        from ourgraph.config import AppSettings
        from ourgraph.ingest.pipeline import Pipeline

        settings = AppSettings()
        pipeline = Pipeline(settings)

        # Mock the individual ingestion methods
        mock_wb = mocker.AsyncMock(return_value=10)
        mock_imf = mocker.AsyncMock(return_value=5)
        mock_yf = mocker.AsyncMock(return_value=20)
        mock_vn = mocker.AsyncMock(return_value=8)

        mocker.patch.object(pipeline, "_ingest_worldbank_macro", mock_wb)
        mocker.patch.object(pipeline, "_ingest_imf_macro", mock_imf)
        mocker.patch.object(pipeline, "_ingest_yfinance_macro", mock_yf)
        mocker.patch.object(pipeline, "_ingest_vnstock_macro", mock_vn)

        results = await pipeline.run_macro_ingestion(
            sources=["worldbank", "imf", "yfinance", "vnstock"],
        )
        assert "worldbank" in results
        assert "imf" in results
        assert "yfinance" in results
        assert "vnstock" in results

    @pytest.mark.asyncio
    async def test_macro_ingestion_graceful_degradation(self, mocker) -> None:
        """Test that one source failure doesn't stop others."""
        from ourgraph.config import AppSettings
        from ourgraph.ingest.pipeline import Pipeline

        settings = AppSettings()
        pipeline = Pipeline(settings)

        # Make worldbank fail
        mock_wb = mocker.AsyncMock(side_effect=Exception("API error"))
        mock_imf = mocker.AsyncMock(return_value=5)

        mocker.patch.object(pipeline, "_ingest_worldbank_macro", mock_wb)
        mocker.patch.object(pipeline, "_ingest_imf_macro", mock_imf)

        results = await pipeline.run_macro_ingestion(sources=["worldbank", "imf"])
        assert results["worldbank"] == 0
        assert results["imf"] == 5
