# Session 1: Relationship System Redesign

## Objective
Fix the chaotic relationships in the graph and create a proper, comprehensive relationship schema that covers all types of connections between entities.

## Context
The user reports that "relationships are really chaotic and a lot are missing (subsidiaries for example)". Currently:
- `graph/schema.py` defines relationship types but they're incomplete
- Subsidiary relationships exist but are messy
- Many implicit relationships aren't captured
- No validation or consistency checks

## Tasks

### 1. Audit Current Relationships
**File**: `src/ourgraph/graph/schema.py` (read)

Current relationship types:
- `HOLDS_STAKE_IN` (Company|Person → Company)
- `SUBSIDIARY_OF` (Company → Company)
- `COMPETES_WITH` (Company → Company)
- `IS_OFFICER` (Person → Company)
- `BELONGS_TO` (Company → Sector)
- `BELONGS_TO_INDUSTRY` (Company → Industry)
- `HAS_STOCK_PRICE`, `HAS_INDICATOR`, `HAS_FINANCIAL_STATEMENTS`
- `RECORDED_ON`, `MEASURED_ON`, `FOR_QUARTER`, `FOR_YEAR`
- `IN_QUARTER`, `IN_YEAR`
- `HAS_MACRO_INDICATOR`, `AFFECTS_SECTOR`, `AFFECTS_INDUSTRY`

### 2. Design Comprehensive Relationship Taxonomy

Create **File**: `src/ourgraph/graph/relationship_schema.py`

```python
class RelationshipType:
    """Complete relationship taxonomy."""
    
    # === Ownership & Control ===
    SUBSIDIARY_OF = "SUBSIDIARY_OF"  # Company → Company (subsidiary)
    PARENT_COMPANY = "PARENT_COMPANY"  # Company → Company (inverse, for clarity)
    HOLDS_STAKE_IN = "HOLDS_STAKE_IN"  # (Company|Person) → Company
    OWNS_SHARES = "OWNS_SHARES"  # Clearer name for stake holding
    CONTROLLED_BY = "CONTROLLED_BY"  # Indirect control
    
    # === Competition & Market ===
    COMPETES_WITH = "COMPETES_WITH"  # Company → Company
    SUPPLIES_TO = "SUPPLIES_TO"  # Company → Company (supply chain)
    CUSTOMER_OF = "CUSTOMER_OF"  # Company → Company
    PARTNERS_WITH = "PARTNERS_WITH"  # Strategic partnerships
    
    # === People & Roles ===
    IS_OFFICER = "IS_OFFICER"  # Person → Company
    IS_BOARD_MEMBER = "IS_BOARD_MEMBER"  # Person → Company (explicit board role)
    IS_SHAREHOLDER = "IS_SHAREHOLDER"  # Person → Company
    IS_FOUNDER = "IS_FOUNDER"  # Person → Company
    IS_EXECUTIVE = "IS_EXECUTIVE"  # Person → Company (C-level, etc.)
    
    # === Temporal/Corporate Actions ===
    ACQUIRED = "ACQUIRED"  # Company → Company (M&A)
    MERGED_WITH = "MERGED_WITH"  # Company ↔ Company
    SPUN_OFF = "SPUN_OFF"  # Company → Company (spin-off)
    RENAMED_TO = "RENAMED_TO"  # Company → Company (name change)
    
    # === Macro & Economics ===
    AFFECTS_SECTOR = "AFFECTS_SECTOR"  # MacroIndicator → Sector
    AFFECTS_INDUSTRY = "AFFECTS_INDUSTRY"  # MacroIndicator → Industry
    CORRELATES_WITH = "CORRELATES_WITH"  # Company ↔ Company (price correlation)
    
    # === Data & Temporal ===
    BELONGS_TO = "BELONGS_TO"  # Company → Sector
    BELONGS_TO_INDUSTRY = "BELONGS_TO_INDUSTRY"  # Company → Industry
    HAS_STOCK_PRICE = "HAS_STOCK_PRICE"
    HAS_INDICATOR = "HAS_INDICATOR"
    HAS_FINANCIAL_STATEMENTS = "HAS_FINANCIAL_STATEMENTS"
```

### 3. Create Relationship Descriptors
**File**: `src/ourgraph/graph/relationship_schema.py` (continue)

For each relationship type, define:
- `name`: The Cypher relationship type
- `properties`: List of allowed properties (e.g., `stake_percent`, `ownership_percent`, `position`, `since_date`)
- `valid_sources`: Which node types can be source
- `valid_targets`: Which node types can be target
- `direction`: OUT/IN/BOTH
- `temporal`: Whether this relationship has validity periods

Example:
```python
SUBSIDIARY_OF = {
    "type": "SUBSIDIARY_OF",
    "properties": ["ownership_percent", "relation_type", "since_date"],
    "valid_sources": [NodeLabel.COMPANY],
    "valid_targets": [NodeLabel.COMPANY],
    "direction": "OUT",
    "temporal": True,
}
```

### 4. Build Relationship Manager
**File**: `src/ourgraph/graph/relationship_manager.py` (new)

Class `RelationshipManager`:
- `create_relationship(source, rel_type, target, properties, valid_at=None)`
- `update_relationship(source, rel_type, target, new_properties)`
- `invalidate_relationship(source, rel_type, target, invalid_at=None)`
- `find_relationships(filters)` - Query relationships
- `validate_relationship(source, rel_type, target)` - Check if valid
- `resolve_conflicts(source, rel_type, target, new_data)` - Handle contradictions

### 5. Fix Subsidiary Handling
**File**: `src/ourgraph/graph/builder.py` (modify `upsert_subsidiaries`)

Issues to fix:
- Currently creates subsidiaries with messy name-to-symbol mapping
- No validation that parent company exists
- Ownership percentage often missing or incorrect
- Should use proper company resolution

New approach:
```python
async def upsert_subsidiaries(self, df: pl.DataFrame, parent_symbol: str) -> None:
    # 1. Validate parent exists
    # 2. For each subsidiary:
    #    - Resolve subsidiary name to symbol (use name_to_symbol map)
    #    - Create Company node if new
    #    - Create SUBSIDIARY_OF edge with properties
    #    - Create inverse PARENT_COMPANY for easy traversal
```

### 6. Update GraphBuilder
**File**: `src/ourgraph/graph/builder.py` (modify)

- Use `RelationshipManager` for all relationship creation
- Add methods for new relationship types
- Ensure idempotency with MERGE + property updates
- Add relationship validation before creation

### 7. Update ORM (Pythonic API)
**File**: `src/ourgraph/graph/orm.py` (modify)

- Add traversal methods for new relationship types
- Example: `company.suppliers()`, `company.customers()`, `company.partners()`
- Add temporal relationship support

### 8. Tests
**File**: `tests/test_relationships.py` (new)

- Test relationship creation for each type
- Test relationship validation
- Test conflict resolution
- Test subsidiary chain queries
- Test temporal relationships

## Acceptance Criteria
- [ ] Comprehensive relationship taxonomy defined
- [ ] Relationship manager implemented with CRUD operations
- [ ] Subsidiary relationships fixed and validated
- [ ] New relationship types can be created via GraphBuilder
- [ ] ORM supports traversing all relationship types
- [ ] All tests pass: `pytest tests/test_relationships.py -v`

## CLI Testing
```bash
# Check current relationships
ourgraph graph network --symbol HPG

# After fix: subsidiaries should be properly linked
ourgraph graph subs HPG

# Test new relationship types (once implemented)
# ourgraph relate "HPG supplies steel to HSG"
# ourgraph graph relations HPG --type SUPPLIES_TO
```

## Notes
- Keep backward compatibility: old relationship types should still work
- Use MERGE in Cypher to maintain idempotency
- Consider performance: add indices on frequently queried relationship properties
- Temporal relationships (valid_at, invalid_at) are crucial for Session 5 (Context Updates)
