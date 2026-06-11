"""Tests for the hidden relationship discovery engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ourgraph.graph.discovery import GraphDiscovery


@pytest.fixture
def mock_queries() -> AsyncMock:
    """Create a mock GraphQueries that returns deterministic data."""
    queries = AsyncMock()

    # Default empty responses for all queries
    queries.query_raw = AsyncMock(return_value=[])
    return queries


@pytest.fixture
def discovery(mock_queries) -> GraphDiscovery:
    return GraphDiscovery(mock_queries)


class TestCrossShareholding:
    """Cross-shareholding discovery tests."""

    @pytest.mark.asyncio
    async def test_empty_graph(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = []
        results = await discovery.discover_cross_shareholdings()
        assert results == []

    @pytest.mark.asyncio
    async def test_single_pair(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            ["HPG", "Hoa Phat Group", "HSG", "Hoa Sen Group", 15.0, 8.0],
        ]
        results = await discovery.discover_cross_shareholdings()
        assert len(results) == 1
        item = results[0]
        assert item["type"] == "cross_shareholding"
        assert item["source_symbol"] == "HPG"
        assert item["target_symbol"] == "HSG"
        assert item["a_holds_b_pct"] == 15.0
        assert item["b_holds_a_pct"] == 8.0
        assert "explanation" in item

    @pytest.mark.asyncio
    async def test_multiple_pairs_sorted(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            ["C", "C Corp", "D", "D Corp", 50.0, 20.0],
            ["A", "A Corp", "B", "B Corp", 10.0, 5.0],
        ]
        results = await discovery.discover_cross_shareholdings()
        assert len(results) == 2
        # Results should be in DB ORDER BY desc order (C+D has 70, A+B has 15)
        assert results[0]["source_symbol"] == "C"


class TestSubsidiaryChains:
    """Multi-level subsidiary chain discovery tests."""

    @pytest.mark.asyncio
    async def test_no_chains(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = []
        results = await discovery.discover_subsidiary_chains()
        assert results == []

    @pytest.mark.asyncio
    async def test_two_level_chain(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            [["VIC", "VHM"], [65.0], 1],
        ]
        results = await discovery.discover_subsidiary_chains()
        assert len(results) == 1
        item = results[0]
        assert item["chain"] == ["VIC", "VHM"]
        assert item["effective_ownership_pct"] == 65.0
        assert item["chain_length"] == 1

    @pytest.mark.asyncio
    async def test_three_level_chain(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            [["VIC", "VHM", "VHMLAND"], [65.0, 51.0], 2],
        ]
        results = await discovery.discover_subsidiary_chains()
        item = results[0]
        assert item["chain"] == ["VIC", "VHM", "VHMLAND"]
        # Effective: 65% * 51% = 33.15%
        assert abs(item["effective_ownership_pct"] - 33.15) < 0.01

    def test_calc_effective_ownership(self) -> None:
        """Effective ownership through a chain."""
        result = GraphDiscovery._calc_effective_ownership([60.0, 50.0])
        assert abs(result - 30.0) < 0.01

        result = GraphDiscovery._calc_effective_ownership([100.0])
        assert abs(result - 100.0) < 0.01

        result = GraphDiscovery._calc_effective_ownership([51.0, 60.0, 70.0])
        # 51% * 60% * 70% = 21.42%
        assert abs(result - 21.42) < 0.01

    def test_calc_effective_with_none(self) -> None:
        """None ownership values should be skipped."""
        result = GraphDiscovery._calc_effective_ownership([60.0, None])
        assert abs(result - 60.0) < 0.01


class TestSharedInsiders:
    """Shared insider discovery tests."""

    @pytest.mark.asyncio
    async def test_no_shared_insiders(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = []
        results = await discovery.discover_shared_insiders()
        assert results == []

    @pytest.mark.asyncio
    async def test_single_shared_insider(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            [
                "Nguyen Van A",
                ["HPG", "HSG", "NKG"],
                ["officer", "shareholder", "officer"],
                ["CEO", None, "Director"],
                3,
            ],
        ]
        results = await discovery.discover_shared_insiders()
        assert len(results) == 1
        item = results[0]
        assert item["person"] == "Nguyen Van A"
        assert len(item["companies"]) == 3
        assert item["influence_score"] > 0

    def test_score_influence(self) -> None:
        """Influence score calculation."""
        # Officer roles score higher
        officer_score = GraphDiscovery._score_influence(
            ["officer", "officer"],
            2,
        )
        shareholder_score = GraphDiscovery._score_influence(
            ["shareholder", "shareholder"],
            2,
        )
        assert officer_score > shareholder_score


class TestCompetitiveInsiders:
    """Competitive insider detection tests."""

    @pytest.mark.asyncio
    async def test_no_competitive_insiders(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = []
        results = await discovery.discover_competitive_insiders()
        assert results == []

    @pytest.mark.asyncio
    async def test_competitive_insider_found(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            ["Nguyen Van A", "HPG", "HSG", "IS_OFFICER", "HOLDS_STAKE_IN"],
        ]
        results = await discovery.discover_competitive_insiders()
        assert len(results) == 1
        assert results[0]["person"] == "Nguyen Van A"
        assert results[0]["company_a"] == "HPG"
        assert results[0]["company_b"] == "HSG"


class TestSupplyChain:
    """Supply chain inference tests."""

    def test_is_supply_chain_pair(self) -> None:
        """Industry-based supply chain matching."""
        # Steel supplier → Automotive customer
        assert GraphDiscovery._is_supply_chain_pair("Steel", "Automotive")
        # Steel supplier → Construction customer
        assert GraphDiscovery._is_supply_chain_pair("Steel", "Construction")
        # Technology → any
        assert GraphDiscovery._is_supply_chain_pair("Technology", "Finance")
        # Unrelated
        assert not GraphDiscovery._is_supply_chain_pair("Agriculture", "Technology")
        assert not GraphDiscovery._is_supply_chain_pair("Retail", "Mining")

    @pytest.mark.asyncio
    async def test_supply_chain_empty(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = []
        results = await discovery.infer_supply_chain()
        assert results == []

    @pytest.mark.asyncio
    async def test_supply_chain_returns_matches(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        """Should return results for Steel → Automotive pairs."""
        mock_queries.query_raw.return_value = [
            [
                "HPG",
                "Hoa Phat Group",
                "Steel",
                "VIC",
                "Vinhomes",
                "Construction",
                100000,
                200000,
            ],
            [
                "HPG",
                "Hoa Phat Group",
                "Steel",
                "HSG",
                "Hoa Sen Group",
                "Steel",
                100000,
                80000,
            ],  # Self-industry, should not match
        ]
        results = await discovery.infer_supply_chain(limit=100)
        assert len(results) == 1  # Only the Steel→Construction pair
        assert results[0]["supplier_symbol"] == "HPG"
        assert results[0]["customer_symbol"] == "VIC"
        assert results[0]["explanation"]


class TestInfluenceNetworks:
    """Influence network mapping tests."""

    @pytest.mark.asyncio
    async def test_conglomerates(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            ["VIC", "Vingroup", 5, ["VHM", "VIC", "VRE", "SSI", "VCB"], ["names"]],
        ]
        results = await discovery._detect_conglomerates(min_subsidiaries=3)
        assert len(results) == 1
        assert results[0]["n_subsidiaries"] == 5
        assert results[0]["parent_symbol"] == "VIC"

    @pytest.mark.asyncio
    async def test_indirect_ownership(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            ["VIC", "VHMLAND", ["VIC", "VHM", "VHMLAND"], [65.0, 51.0]],
        ]
        results = await discovery._calculate_indirect_ownership()
        assert len(results) == 1
        # Effective: 65 * 51 / 100 = 33.15 > 5.0
        assert abs(results[0]["effective_ownership_pct"] - 33.15) < 0.01

    @pytest.mark.asyncio
    async def test_board_interlocks(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = [
            ["Nguyen Van A", ["HPG", "VIC", "VCB"], 3],
        ]
        results = await discovery._find_board_interlocks(min_companies=2)
        assert len(results) == 1
        assert results[0]["n_companies"] == 3


class TestPriceCorrelation:
    """Price correlation discovery tests."""

    @pytest.mark.asyncio
    async def test_pearson(self) -> None:
        """Pearson correlation calculation."""
        # Perfect positive correlation
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        corr = GraphDiscovery._pearson(x, y)
        assert abs(corr - 1.0) < 0.01

        # Perfect negative correlation
        y_neg = [10.0, 8.0, 6.0, 4.0, 2.0]
        corr = GraphDiscovery._pearson(x, y_neg)
        assert abs(corr - (-1.0)) < 0.01

        # No correlation
        y_zero = [1.0, 1.0, 1.0, 1.0, 1.0]
        corr = GraphDiscovery._pearson(x, y_zero)
        assert abs(corr) < 0.01

    @pytest.mark.asyncio
    async def test_pearson_too_few_points(self) -> None:
        """Pearson with too few data points should return 0."""
        assert GraphDiscovery._pearson([1.0, 2.0], [3.0, 4.0]) == 0.0


class TestDiscoverAll:
    """Integration-level discover_all tests."""

    @pytest.mark.asyncio
    async def test_discover_all_empty(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = []
        results = await discovery.discover_all()
        assert isinstance(results, dict)
        for key, value in results.items():
            if isinstance(value, list):
                assert value == []

    @pytest.mark.asyncio
    async def test_discover_for_symbol(
        self, discovery: GraphDiscovery, mock_queries: AsyncMock,
    ) -> None:
        mock_queries.query_raw.return_value = []
        mock_queries.get_company_insiders = AsyncMock(
            return_value=MagicMock(to_dicts=list),
        )
        mock_queries.get_sector_peers = AsyncMock(
            return_value=MagicMock(to_dicts=list),
        )

        results = await discovery.discover_for_symbol("HPG")
        assert isinstance(results, dict)
        assert "cross_shareholdings" in results
        assert "subsidiary_chains" in results
        assert "insiders" in results
