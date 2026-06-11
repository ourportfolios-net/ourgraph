"""Tests for graph schema and builder logic (unit — no real FalkorDB connection)."""

from __future__ import annotations

from ourgraph.graph.schema import NodeLabel, Prop, RelType


def _expect(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_node_labels_defined() -> None:
    _expect(NodeLabel.COMPANY == "Company", "NodeLabel.COMPANY mismatch")
    _expect(NodeLabel.SECTOR == "Sector", "NodeLabel.SECTOR mismatch")
    _expect(NodeLabel.INDUSTRY == "Industry", "NodeLabel.INDUSTRY mismatch")
    _expect(NodeLabel.STOCK_PRICE == "StockPrice", "NodeLabel.STOCK_PRICE mismatch")
    _expect(
        NodeLabel.FINANCIAL_STATEMENT == "FinancialStatement",
        "NodeLabel.FINANCIAL_STATEMENT mismatch",
    )
    _expect(NodeLabel.INDICATOR == "Indicator", "NodeLabel.INDICATOR mismatch")
    _expect(NodeLabel.PERSON == "Person", "NodeLabel.PERSON mismatch")


def test_rel_types_defined() -> None:
    _expect(RelType.BELONGS_TO == "BELONGS_TO", "RelType.BELONGS_TO mismatch")
    _expect(
        RelType.BELONGS_TO_INDUSTRY == "BELONGS_TO_INDUSTRY",
        "RelType.BELONGS_TO_INDUSTRY mismatch",
    )
    _expect(
        RelType.HAS_STOCK_PRICE == "HAS_STOCK_PRICE",
        "RelType.HAS_STOCK_PRICE mismatch",
    )
    _expect(RelType.SUBSIDIARY_OF == "SUBSIDIARY_OF", "RelType.SUBSIDIARY_OF mismatch")
    _expect(
        RelType.HOLDS_STAKE_IN == "HOLDS_STAKE_IN",
        "RelType.HOLDS_STAKE_IN mismatch",
    )
    _expect(RelType.IS_OFFICER == "IS_OFFICER", "RelType.IS_OFFICER mismatch")


def test_props_defined() -> None:
    _expect(Prop.SYMBOL == "symbol", "Prop.SYMBOL mismatch")
    _expect(Prop.DATE == "date", "Prop.DATE mismatch")
    _expect(Prop.CLOSE == "close", "Prop.CLOSE mismatch")
    _expect(Prop.PERIOD == "period", "Prop.PERIOD mismatch")
    _expect(Prop.PAYLOAD == "payload", "Prop.PAYLOAD mismatch")


def test_schema_no_collisions() -> None:
    """Ensure no two node labels are identical."""
    labels = [v for k, v in vars(NodeLabel).items() if not k.startswith("_")]
    _expect(
        len(labels) == len(set(labels)),
        "Duplicate node labels detected",
    )


def test_graph_builder_from_settings_does_not_connect() -> None:
    """Ensure GraphBuilder.from_settings does not open network connections.

    The actual connection happens only on the first query.
    """
    from unittest.mock import patch

    from ourgraph.config import FalkorDBSettings
    from ourgraph.graph.builder import GraphBuilder

    settings = FalkorDBSettings()

    with patch("ourgraph.db.falkordb.build_falkordb_client") as mock_client:
        mock_client.return_value = object()
        builder = GraphBuilder.from_settings(settings)
        _expect(builder is not None, "Expected builder instance")
        mock_client.assert_called_once()
