"""
Tests for graph schema and builder logic (unit — no real FalkorDB connection).
"""


from ourgraph.graph.schema import NodeLabel, Prop, RelType


def test_node_labels_defined():
    assert NodeLabel.COMPANY == "Company"
    assert NodeLabel.SECTOR == "Sector"
    assert NodeLabel.INDUSTRY == "Industry"
    assert NodeLabel.STOCK_PRICE == "StockPrice"
    assert NodeLabel.FINANCIAL_STATEMENT == "FinancialStatement"
    assert NodeLabel.FINANCIAL_INDICATOR == "FinancialIndicator"
    assert NodeLabel.OFFICER == "Officer"


def test_rel_types_defined():
    assert RelType.BELONGS_TO_INDUSTRY == "BELONGS_TO_INDUSTRY"
    assert RelType.HAS_PRICE == "HAS_PRICE"
    assert RelType.SUBSIDIARY_OF == "SUBSIDIARY_OF"
    assert RelType.HOLDS_STAKE_IN == "HOLDS_STAKE_IN"
    assert RelType.LED_BY == "LED_BY"


def test_props_defined():
    assert Prop.SYMBOL == "symbol"
    assert Prop.DATE == "date"
    assert Prop.CLOSE == "close"
    assert Prop.METRIC == "metric"
    assert Prop.VALUE == "value"


def test_schema_no_collisions():
    """Ensure no two node labels are identical."""
    labels = [v for k, v in vars(NodeLabel).items() if not k.startswith("_")]
    assert len(labels) == len(set(labels)), "Duplicate node labels detected"


def test_graph_builder_from_settings_does_not_connect():
    """
    GraphBuilder.from_settings() should not raise even without a running DB.
    The actual connection happens on the first query.
    """
    from unittest.mock import patch

    from ourgraph.config import FalkorDBSettings
    from ourgraph.graph.builder import GraphBuilder

    settings = FalkorDBSettings()

    # The constructor creates a FalkorDB object but doesn't connect
    # We patch build_falkordb_client to avoid network attempts
    with patch("ourgraph.graph.builder.build_falkordb_client") as mock_client:
        mock_client.return_value = object()
        builder = GraphBuilder.from_settings(settings)
        assert builder is not None
        mock_client.assert_called_once()
