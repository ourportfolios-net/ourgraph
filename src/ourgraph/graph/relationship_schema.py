"""Comprehensive relationship taxonomy with descriptors.

Defines every relationship type in the graph with its properties,
valid source/target node types, direction, and temporal semantics.
This is the single source of truth for relationship metadata.
"""

from __future__ import annotations


class NodeLabel:
    """Mirror of graph.schema.NodeLabel — kept local to avoid circular imports."""

    COMPANY = "Company"
    PERSON = "Person"
    SECTOR = "Sector"
    INDUSTRY = "Industry"
    FINANCIAL_STATEMENT = "FinancialStatement"
    INDICATOR = "Indicator"
    DATE = "Date"
    QUARTER = "Quarter"
    YEAR = "Year"
    MACRO_INDICATOR = "MacroIndicator"
    COUNTRY = "Country"
    BOND = "Bond"


class RelType:
    """All relationship type constants in the graph.

    This mirrors and extends graph.schema.RelType, kept here so that
    relationship descriptors can reference themselves without circularity.
    """

    # Ownership & Control
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    HOLDS_STAKE_IN = "HOLDS_STAKE_IN"

    # Competition & Market
    COMPETES_WITH = "COMPETES_WITH"

    # People & Roles
    IS_OFFICER = "IS_OFFICER"
    IS_BOARD_MEMBER = "IS_BOARD_MEMBER"
    IS_FOUNDER = "IS_FOUNDER"
    IS_EXECUTIVE = "IS_EXECUTIVE"

    # Company → Sector/Industry
    BELONGS_TO = "BELONGS_TO"
    BELONGS_TO_INDUSTRY = "BELONGS_TO_INDUSTRY"

    # Temporal / Data hierarchy
    HAS_INDICATOR = "HAS_INDICATOR"
    HAS_FINANCIAL_STATEMENTS = "HAS_FINANCIAL_STATEMENTS"
    MEASURED_ON = "MEASURED_ON"
    FOR_QUARTER = "FOR_QUARTER"
    FOR_YEAR = "FOR_YEAR"
    IN_QUARTER = "IN_QUARTER"
    IN_YEAR = "IN_YEAR"

    # Audit
    AUDITED_BY = "AUDITED_BY"  # Company → Company (audit firm)

    # Macro
    HAS_MACRO_INDICATOR = "HAS_MACRO_INDICATOR"
    AFFECTS_SECTOR = "AFFECTS_SECTOR"
    AFFECTS_INDUSTRY = "AFFECTS_INDUSTRY"

    # Phase 2: Structured scrapers — corporate disclosure relationships
    RELATED_PARTY_TRANSACTION = "RELATED_PARTY_TRANSACTION"
    GUARANTEES = "GUARANTEES"
    LENDS_TO = "LENDS_TO"
    HAS_JOINT_VENTURE_WITH = "HAS_JOINT_VENTURE_WITH"
    UNDERWRITTEN_BY = "UNDERWRITTEN_BY"
    HAS_BUSINESS_COOPERATION = "HAS_BUSINESS_COOPERATION"
    STATE_OWNS = "STATE_OWNS"
    HAS_BOND = "HAS_BOND"


# ---------------------------------------------------------------------------
# Relationship descriptor
# ---------------------------------------------------------------------------


class RelationshipDescriptor:
    """Metadata descriptor for a relationship type.

    Attributes:
        type: Cypher relationship type string.
        properties: List of allowed property keys on the edge.
        valid_sources: NodeLabel values allowed as source.
        valid_targets: NodeLabel values allowed as target.
        direction: ``OUT`` (source→target), ``IN`` (source←target),
            or ``BOTH`` (symmetric).
        temporal: Whether this edge carries validity periods
            (``since_date`` / ``until_date``).
        description: Human-readable description of the relationship.

    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        type: str,  # noqa: A002
        properties: list[str] | None = None,
        valid_sources: list[str] | None = None,
        valid_targets: list[str] | None = None,
        direction: str = "OUT",
        temporal: bool = False,
        description: str = "",
    ) -> None:
        self.type = type
        self.properties = properties or []
        self.valid_sources = valid_sources or []
        self.valid_targets = valid_targets or []
        self.direction = direction
        self.temporal = temporal
        self.description = description

    @property
    def is_symmetric(self) -> bool:
        return self.direction == "BOTH"

    def validate(self, source_label: str, target_label: str) -> str | None:
        """Return an error message if the (source, target) pair is invalid, else None."""
        if self.valid_sources and source_label not in self.valid_sources:
            return (
                f"Invalid source label '{source_label}' for relationship "
                f"{self.type}: allowed {self.valid_sources}"
            )
        if self.valid_targets and target_label not in self.valid_targets:
            return (
                f"Invalid target label '{target_label}' for relationship "
                f"{self.type}: allowed {self.valid_targets}"
            )
        return None


# ---------------------------------------------------------------------------
# Complete relationship registry
# ---------------------------------------------------------------------------

RELATIONSHIP_REGISTRY: dict[str, RelationshipDescriptor] = {}


def _reg(  # noqa: PLR0913
    type: str,  # noqa: A002
    properties: list[str] | None = None,
    valid_sources: list[str] | None = None,
    valid_targets: list[str] | None = None,
    direction: str = "OUT",
    *,
    temporal: bool = False,
    description: str = "",
) -> RelationshipDescriptor:
    """Register and return a relationship descriptor."""
    d = RelationshipDescriptor(
        type=type,
        properties=properties,
        valid_sources=valid_sources,
        valid_targets=valid_targets,
        direction=direction,
        temporal=temporal,
        description=description,
    )
    RELATIONSHIP_REGISTRY[type] = d
    return d


# ═══════════════════════════════════════════════════════════════════════════
# Ownership & Control
# ═══════════════════════════════════════════════════════════════════════════

SUBSIDIARY_OF = _reg(
    type=RelType.SUBSIDIARY_OF,
    properties=["ownership_percent", "relation_type"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Child company is a subsidiary of parent company",
)

HOLDS_STAKE_IN = _reg(
    type=RelType.HOLDS_STAKE_IN,
    properties=["stake_percent"],
    valid_sources=[NodeLabel.COMPANY, NodeLabel.PERSON],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Entity holds an equity stake in a company",
)

# ═══════════════════════════════════════════════════════════════════════════
# Competition & Market
# ═══════════════════════════════════════════════════════════════════════════

COMPETES_WITH = _reg(
    type=RelType.COMPETES_WITH,
    properties=[],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="BOTH",
    temporal=False,
    description="Companies compete in the same industry",
)

# ═══════════════════════════════════════════════════════════════════════════
# Audit
# ═══════════════════════════════════════════════════════════════════════════

AUDITED_BY = _reg(
    type=RelType.AUDITED_BY,
    properties=["auditor_name"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=False,
    description="Company is audited by an audit firm",
)

# ═══════════════════════════════════════════════════════════════════════════
# People & Roles
# ═══════════════════════════════════════════════════════════════════════════

IS_OFFICER = _reg(
    type=RelType.IS_OFFICER,
    properties=["position", "own_percent"],
    valid_sources=[NodeLabel.PERSON],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Person holds an officer/management role at a company",
)

IS_BOARD_MEMBER = _reg(
    type=RelType.IS_BOARD_MEMBER,
    properties=["position", "since_date"],
    valid_sources=[NodeLabel.PERSON],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Person serves on the board of directors",
)

IS_FOUNDER = _reg(
    type=RelType.IS_FOUNDER,
    properties=["position", "since_date"],
    valid_sources=[NodeLabel.PERSON],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Person is a founder of the company",
)

IS_EXECUTIVE = _reg(
    type=RelType.IS_EXECUTIVE,
    properties=["position", "since_date"],
    valid_sources=[NodeLabel.PERSON],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Person holds a C-level executive position",
)

# ═══════════════════════════════════════════════════════════════════════════
# Company Classification
# ═══════════════════════════════════════════════════════════════════════════

BELONGS_TO = _reg(
    type=RelType.BELONGS_TO,
    properties=[],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.SECTOR],
    direction="OUT",
    temporal=False,
    description="Company belongs to a sector",
)

BELONGS_TO_INDUSTRY = _reg(
    type=RelType.BELONGS_TO_INDUSTRY,
    properties=[],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.INDUSTRY],
    direction="OUT",
    temporal=False,
    description="Company belongs to an industry",
)

# ═══════════════════════════════════════════════════════════════════════════
# Data & Temporal
# ═══════════════════════════════════════════════════════════════════════════

HAS_INDICATOR = _reg(
    type=RelType.HAS_INDICATOR,
    properties=[],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.INDICATOR],
    direction="OUT",
    description="Company has a financial indicator record",
)

HAS_FINANCIAL_STATEMENTS = _reg(
    type=RelType.HAS_FINANCIAL_STATEMENTS,
    properties=[],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.FINANCIAL_STATEMENT],
    direction="OUT",
    description="Company has a financial statement",
)

MEASURED_ON = _reg(
    type=RelType.MEASURED_ON,
    properties=[],
    valid_sources=[NodeLabel.INDICATOR, NodeLabel.MACRO_INDICATOR],
    valid_targets=[NodeLabel.QUARTER, NodeLabel.DATE],
    direction="OUT",
    description="Measurement was taken in a period",
)

FOR_QUARTER = _reg(
    type=RelType.FOR_QUARTER,
    properties=[],
    valid_sources=[NodeLabel.FINANCIAL_STATEMENT],
    valid_targets=[NodeLabel.QUARTER],
    direction="OUT",
    description="Financial statement is for a quarter",
)

FOR_YEAR = _reg(
    type=RelType.FOR_YEAR,
    properties=[],
    valid_sources=[NodeLabel.FINANCIAL_STATEMENT],
    valid_targets=[NodeLabel.YEAR],
    direction="OUT",
    description="Financial statement is for a year",
)

IN_QUARTER = _reg(
    type=RelType.IN_QUARTER,
    properties=[],
    valid_sources=[NodeLabel.DATE],
    valid_targets=[NodeLabel.QUARTER],
    direction="OUT",
    description="Date falls within a quarter",
)

IN_YEAR = _reg(
    type=RelType.IN_YEAR,
    properties=[],
    valid_sources=[NodeLabel.QUARTER],
    valid_targets=[NodeLabel.YEAR],
    direction="OUT",
    description="Quarter falls within a year",
)

# ═══════════════════════════════════════════════════════════════════════════
# Macro
# ═══════════════════════════════════════════════════════════════════════════

HAS_MACRO_INDICATOR = _reg(
    type=RelType.HAS_MACRO_INDICATOR,
    properties=[],
    valid_sources=[NodeLabel.COUNTRY],
    valid_targets=[NodeLabel.MACRO_INDICATOR],
    direction="OUT",
    description="Country has a macro-economic indicator",
)

AFFECTS_SECTOR = _reg(
    type=RelType.AFFECTS_SECTOR,
    properties=["reason"],
    valid_sources=[NodeLabel.MACRO_INDICATOR],
    valid_targets=[NodeLabel.SECTOR],
    direction="OUT",
    description="Macro indicator affects a sector",
)

AFFECTS_INDUSTRY = _reg(
    type=RelType.AFFECTS_INDUSTRY,
    properties=["reason"],
    valid_sources=[NodeLabel.MACRO_INDICATOR],
    valid_targets=[NodeLabel.INDUSTRY],
    direction="OUT",
    description="Macro indicator affects an industry",
)

# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Corporate Disclosure Relationships
# ═══════════════════════════════════════════════════════════════════════════

RELATED_PARTY_TRANSACTION = _reg(
    type=RelType.RELATED_PARTY_TRANSACTION,
    properties=["amount", "description", "transaction_date"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Company engaged in a related-party transaction with counterparty",
)

GUARANTEES = _reg(
    type=RelType.GUARANTEES,
    properties=["amount", "description", "transaction_date"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Company provides a guarantee for another entity",
)

LENDS_TO = _reg(
    type=RelType.LENDS_TO,
    properties=["amount", "interest_rate", "maturity_date", "transaction_date"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Company extends a loan to another entity",
)

HAS_JOINT_VENTURE_WITH = _reg(
    type=RelType.HAS_JOINT_VENTURE_WITH,
    properties=["description", "transaction_date"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="BOTH",
    temporal=True,
    description="Companies are in a joint venture together",
)

UNDERWRITTEN_BY = _reg(
    type=RelType.UNDERWRITTEN_BY,
    properties=[
        "issue_amount",
        "interest_rate",
        "maturity_date",
        "issue_date",
        "description",
    ],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="Bond issuance is underwritten by a bank or financial institution",
)

HAS_BUSINESS_COOPERATION = _reg(
    type=RelType.HAS_BUSINESS_COOPERATION,
    properties=["description", "transaction_date"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="BOTH",
    temporal=True,
    description="Companies have a business cooperation agreement",
)

STATE_OWNS = _reg(
    type=RelType.STATE_OWNS,
    properties=["stake_percent", "description", "transaction_date"],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.COMPANY],
    direction="OUT",
    temporal=True,
    description="State entity holds ownership stake in a company",
)

HAS_BOND = _reg(
    type=RelType.HAS_BOND,
    properties=[
        "bond_code",
        "interest_rate",
        "maturity_date",
        "issue_date",
        "issue_amount",
        "currency",
    ],
    valid_sources=[NodeLabel.COMPANY],
    valid_targets=[NodeLabel.BOND],
    direction="OUT",
    temporal=False,
    description="Company has issued a bond",
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get_descriptor(rel_type: str) -> RelationshipDescriptor | None:
    """Get the descriptor for a relationship type, or None if unknown."""
    return RELATIONSHIP_REGISTRY.get(rel_type)


def validate_relationship(
    rel_type: str,
    source_label: str,
    target_label: str,
) -> tuple[bool, str]:
    """Validate a relationship by type and source/target labels.

    Returns (is_valid, error_message).
    """
    desc = get_descriptor(rel_type)
    if desc is None:
        return False, f"Unknown relationship type: {rel_type}"
    error = desc.validate(source_label, target_label)
    if error:
        return False, error
    return True, ""


def allowed_properties(rel_type: str) -> list[str]:
    """Return allowed property keys for a relationship type."""
    desc = get_descriptor(rel_type)
    return list(desc.properties) if desc else []


def list_relationship_types(
    source_label: str | None = None,
    target_label: str | None = None,
) -> list[RelationshipDescriptor]:
    """List relationship descriptors, optionally filtered."""
    results = list(RELATIONSHIP_REGISTRY.values())
    if source_label:
        results = [d for d in results if source_label in d.valid_sources]
    if target_label:
        results = [d for d in results if target_label in d.valid_targets]
    return results
