"""Tests for the relationship schema, manager, and derived roles."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ourgraph.graph.relationship_schema import (
    RELATIONSHIP_REGISTRY,
    NodeLabel,
    RelType,
    list_relationship_types,
    validate_relationship,
)
from ourgraph.graph.schema import NodeLabel as SchemaNodeLabel
from ourgraph.graph.schema import RelType as SchemaRelType

if TYPE_CHECKING:
    from collections.abc import Generator


# ═══════════════════════════════════════════════════════════════════════
# Relationship Schema Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRelationshipRegistry:
    """Verify the relationship registry is complete and consistent."""

    def test_all_schema_types_registered(self) -> None:
        """Every RelType in schema.py must have a descriptor in the registry."""
        schema_types = {
            v for k, v in vars(SchemaRelType).items() if not k.startswith("_")
        }
        registered = set(RELATIONSHIP_REGISTRY.keys())
        missing = schema_types - registered
        # IS_BOARD_MEMBER, IS_FOUNDER, IS_EXECUTIVE are new types only registered
        # in the relationship_schema, not in the old schema.py
        known_new = {"IS_BOARD_MEMBER", "IS_FOUNDER", "IS_EXECUTIVE"}
        missing -= known_new
        assert not missing, f"Unregistered relationship types: {missing}"

    def test_schema_type_sync(self) -> None:
        """RelType constants in relationship_schema must match schema.py existing ones."""
        # These are shared between both files
        shared_types = {
            "SUBSIDIARY_OF",
            "HOLDS_STAKE_IN",
            "COMPETES_WITH",
            "IS_OFFICER",
            "BELONGS_TO",
            "BELONGS_TO_INDUSTRY",
            "HAS_STOCK_PRICE",
            "HAS_INDICATOR",
            "HAS_FINANCIAL_STATEMENTS",
            "RECORDED_ON",
            "MEASURED_ON",
            "FOR_QUARTER",
            "FOR_YEAR",
            "IN_QUARTER",
            "IN_YEAR",
            "HAS_MACRO_INDICATOR",
            "AFFECTS_SECTOR",
            "AFFECTS_INDUSTRY",
        }
        for t in shared_types:
            assert getattr(RelType, t, None) == getattr(SchemaRelType, t, None), (
                f"Mismatch for {t}: "
                f"relationship_schema={getattr(RelType, t, None)}, "
                f"schema={getattr(SchemaRelType, t, None)}"
            )

    def test_registry_descriptors_have_required_fields(self) -> None:
        """Every descriptor must have type and valid_sources/targets."""
        for rel_type, desc in RELATIONSHIP_REGISTRY.items():
            assert desc.type == rel_type
            assert desc.valid_sources, f"{rel_type} has no valid_sources"
            assert desc.valid_targets, f"{rel_type} has no valid_targets"

    def test_list_relationship_types_filter(self) -> None:
        """list_relationship_types should filter correctly."""
        company_outgoing = list_relationship_types(source_label=NodeLabel.COMPANY)
        assert all(NodeLabel.COMPANY in d.valid_sources for d in company_outgoing)
        assert len(company_outgoing) > 5  # Many types start from Company

        person_outgoing = list_relationship_types(source_label=NodeLabel.PERSON)
        assert all(NodeLabel.PERSON in d.valid_sources for d in person_outgoing)

    def test_validate_relationship_valid(self) -> None:
        """Valid relationships should pass validation."""
        valid, msg = validate_relationship(
            RelType.SUBSIDIARY_OF,
            NodeLabel.COMPANY,
            NodeLabel.COMPANY,
        )
        assert valid
        assert not msg

        valid, msg = validate_relationship(
            RelType.IS_OFFICER,
            NodeLabel.PERSON,
            NodeLabel.COMPANY,
        )
        assert valid

    def test_validate_relationship_invalid_source(self) -> None:
        """Invalid source labels should fail validation."""
        valid, msg = validate_relationship(
            RelType.SUBSIDIARY_OF,
            NodeLabel.PERSON,  # Person can't be source of SUBSIDIARY_OF
            NodeLabel.COMPANY,
        )
        assert not valid
        assert "Invalid source label" in msg

    def test_validate_relationship_invalid_target(self) -> None:
        """Invalid target labels should fail validation."""
        valid, msg = validate_relationship(
            RelType.BELONGS_TO,
            NodeLabel.COMPANY,
            NodeLabel.PERSON,  # Company can't BELONGS_TO Person
        )
        assert not valid
        assert "Invalid target label" in msg

    def test_validate_relationship_unknown_type(self) -> None:
        """Unknown relationship types should fail validation."""
        valid, msg = validate_relationship(
            "UNKNOWN_REL_TYPE",
            NodeLabel.COMPANY,
            NodeLabel.COMPANY,
        )
        assert not valid
        assert "Unknown" in msg

    def test_ownership_descriptor(self) -> None:
        """Ownership relationships should have correct properties."""
        desc = RELATIONSHIP_REGISTRY[RelType.SUBSIDIARY_OF]
        assert "ownership_percent" in desc.properties
        assert desc.temporal

        desc = RELATIONSHIP_REGISTRY[RelType.HOLDS_STAKE_IN]
        assert "stake_percent" in desc.properties
        assert desc.temporal

    def test_symmetric_relationship(self) -> None:
        """COMPETES_WITH should be symmetric."""
        desc = RELATIONSHIP_REGISTRY[RelType.COMPETES_WITH]
        assert desc.is_symmetric
        assert desc.direction == "BOTH"


class TestDerivedRoleRelationships:
    """Test that derived role types are defined correctly."""

    @pytest.fixture(scope="class")
    def role_types(self) -> Generator:
        return [
            RelType.IS_BOARD_MEMBER,
            RelType.IS_FOUNDER,
            RelType.IS_EXECUTIVE,
        ]

    def test_role_types_have_correct_source_target(self) -> None:
        """All role types should be Person → Company."""
        for role_type in [
            RelType.IS_BOARD_MEMBER,
            RelType.IS_FOUNDER,
            RelType.IS_EXECUTIVE,
        ]:
            desc = RELATIONSHIP_REGISTRY[role_type]
            assert NodeLabel.PERSON in desc.valid_sources
            assert NodeLabel.COMPANY in desc.valid_targets

    def test_role_types_have_position_property(self) -> None:
        """All role types should have position property."""
        for role_type in [
            RelType.IS_BOARD_MEMBER,
            RelType.IS_FOUNDER,
            RelType.IS_EXECUTIVE,
        ]:
            desc = RELATIONSHIP_REGISTRY[role_type]
            assert "position" in desc.properties

    def test_role_types_are_temporal(self) -> None:
        """All role relationships should support temporal tracking."""
        for role_type in [
            RelType.IS_BOARD_MEMBER,
            RelType.IS_FOUNDER,
            RelType.IS_EXECUTIVE,
        ]:
            desc = RELATIONSHIP_REGISTRY[role_type]
            assert desc.temporal


# ═══════════════════════════════════════════════════════════════════════
# NodeLabel Alignment Tests
# ═══════════════════════════════════════════════════════════════════════


class TestNodeLabelAlignment:
    """Verify the relationship_schema NodeLabel matches schema.py NodeLabel."""

    def test_all_schema_labels_present(self) -> None:
        """All node labels from schema.py must be in relationship_schema."""
        schema_labels = {
            v for k, v in vars(SchemaNodeLabel).items() if not k.startswith("_")
        }
        rel_schema_labels = {
            v for k, v in vars(NodeLabel).items() if not k.startswith("_")
        }
        assert schema_labels == rel_schema_labels, (
            f"Missing: {schema_labels - rel_schema_labels}, "
            f"Extra: {rel_schema_labels - schema_labels}"
        )


# ═══════════════════════════════════════════════════════════════════════
# Relationship Manager Unit Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRelationshipManagerUnit:
    """Unit tests for RelationshipManager (no DB)."""

    async def test_validate_method(self, mocker) -> None:
        """RelationshipManager.validate should delegate to schema."""
        from ourgraph.graph.relationship_manager import RelationshipManager

        mock_builder = mocker.AsyncMock()
        mgr = RelationshipManager(mock_builder)

        valid, msg = await mgr.validate(
            NodeLabel.COMPANY,
            {"symbol": "HPG"},
            RelType.SUBSIDIARY_OF,
            NodeLabel.COMPANY,
            {"symbol": "Vnsteel"},
        )
        assert valid

        invalid, msg2 = await mgr.validate(
            NodeLabel.PERSON,
            {"name": "Test"},
            RelType.SUBSIDIARY_OF,
            NodeLabel.COMPANY,
            {"symbol": "XXX"},
        )
        assert not invalid

    async def test_create_validates_schema(self, mocker) -> None:
        """create() should raise on invalid relationship types."""
        from ourgraph.graph.relationship_manager import (
            RelationshipError,
            RelationshipManager,
        )

        mock_builder = mocker.AsyncMock()
        mgr = RelationshipManager(mock_builder)

        with pytest.raises(RelationshipError, match="Invalid source label"):
            await mgr.create(
                NodeLabel.PERSON,
                {"person_name": "Test"},
                RelType.SUBSIDIARY_OF,
                NodeLabel.COMPANY,
                {"symbol": "XXX"},
            )

    def test_match_clause(self) -> None:
        """Match clause should be correctly formatted."""
        from ourgraph.graph.relationship_manager import RelationshipManager

        mock_builder = type("Mock", (), {})()
        mgr = RelationshipManager(mock_builder)  # type: ignore

        clause = mgr._match_clause("Company", {"symbol": "HPG"}, "src")
        assert "Company" in clause
        assert "symbol" in clause
        assert "$src_symbol" in clause

    def test_match_clause_multiple_keys(self) -> None:
        """Match clause handles multiple key-value pairs."""
        from ourgraph.graph.relationship_manager import RelationshipManager

        mock_builder = type("Mock", (), {})()
        mgr = RelationshipManager(mock_builder)  # type: ignore

        clause = mgr._match_clause(
            "StockPrice",
            {"symbol": "HPG", "date": "2024-01-01"},
            "p",
        )
        assert "StockPrice" in clause
        assert "symbol" in clause
        assert "date" in clause
        assert "$p_symbol" in clause
        assert "$p_date" in clause

    def test_set_clause_empty(self) -> None:
        """Set clause should be empty for no properties."""
        from ourgraph.graph.relationship_manager import RelationshipManager

        mock_builder = type("Mock", (), {})()
        mgr = RelationshipManager(mock_builder)  # type: ignore

        assert mgr._set_clause({}, "r") == ""

    def test_set_clause_with_properties(self) -> None:
        """Set clause should include all properties."""
        from ourgraph.graph.relationship_manager import RelationshipManager

        mock_builder = type("Mock", (), {})()
        mgr = RelationshipManager(mock_builder)  # type: ignore

        clause = mgr._set_clause({"stake_percent": 15.5}, "r")
        assert "stake_percent" in clause
        assert "$r_stake_percent" in clause
