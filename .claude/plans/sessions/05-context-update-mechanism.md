# Session 5: Context Update Mechanism

## Objective
Build a mechanism for the graph to self-adapt and update according to new information from context sources (text files, news, user input, etc.). The design should be extremely modular to support various context sources in the future.

## Context
The user wants the graph to "self-adapt and update according to news as well." However, they've decided to focus on building the mechanism first:
> "Since news have a lot of noises, this would require a lot of thinking. For now just focus on making the graph automatically updated by adding context - a text file for instance, or another graph. (for instance if A is owned by B, and the user adds news that A is no longer owned by B, then the relationship between A and B in ourgraph would be automatically updated accordingly. Build the mechanism first.)"

## Tasks

### 1. Design Context Update Architecture
**File**: `src/ourgraph/context/updater.py` (new)

Create a modular context update system:

```python
class ContextUpdater:
    """Update graph based on context sources."""
    
    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._parsers: dict[str, ContextParser] = {
            "text": TextContextParser(),
            "json": JSONContextParser(),
            "graph": GraphContextParser(),
            # Future: "news": NewsContextParser(),
            # Future: "rss": RSSContextParser(),
        }
    
    async def update_from_file(self, filepath: str) -> dict:
        """Update graph from a context file."""
        # 1. Detect file type (by extension or content)
        # 2. Parse context using appropriate parser
        # 3. Extract relationships and facts
        # 4. Update graph (create/invalidate relationships)
        # 5. Return summary of changes
    
    async def update_from_text(self, text: str, source: str = "user") -> dict:
        """Update graph from raw text."""
        # Similar to above, but from string
        
    async def update_from_graph(self, graph_name: str) -> dict:
        """Update graph from another FalkorDB graph."""
        # Import relationships from another graph
```

### 2. Create Context Parsers
**File**: `src/ourgraph/context/parser.py` (new)

Different parsers for different context formats:

```python
class ContextParser(ABC):
    """Abstract base class for context parsers."""
    
    @abstractmethod
    async def parse(self, content: str | dict) -> list[dict]:
        """Parse content and return extracted facts.
        
        Returns:
            [{
                "type": "relationship",  # or "fact", "entity"
                "subject": "HPG",
                "predicate": "SUBSIDIARY_OF",
                "object": "HPG Group",
                "properties": {"ownership_percent": 51.0},
                "valid_at": "2024-01-15",
                "invalid_at": None,
                "source": "user",
                "confidence": 1.0,
            }]
        """
        pass

class TextContextParser(ContextParser):
    """Parse natural language text using LLM."""
    # Uses RelationshipExtractor from Session 4
    
class JSONContextParser(ContextParser):
    """Parse structured JSON context."""
    # Expects format: [{"subject": ..., "predicate": ..., "object": ...}]
    
class GraphContextParser(ContextParser):
    """Parse relationships from another graph."""
    # Reads relationships from a FalkorDB graph
```

### 3. Temporal Relationship Management
**File**: `src/ourgraph/graph/temporal.py` (new)

Handle validity periods for relationships:

```python
class TemporalRelationshipManager:
    """Manage relationships with validity periods."""
    
    async def create_with_validity(
        self,
        source: str,
        predicate: str,
        target: str,
        properties: dict,
        valid_at: str | None = None,
        source_info: str = "user",
    ) -> None:
        """Create relationship with validity period."""
        # In FalkorDB, store:
        #   - valid_at: When this relationship became true
        #   - invalid_at: When this relationship stopped being true (NULL = still valid)
        #   - source: Where this info came from
        #   - confidence: How reliable is this info (0.0-1.0)
    
    async def invalidate_relationship(
        self,
        source: str,
        predicate: str,
        target: str,
        invalid_at: str | None = None,
        reason: str = "",
    ) -> None:
        """Mark a relationship as no longer valid."""
        # Set invalid_at on the relationship
        # Create new relationship if replacement provided
    
    async def get_valid_at_time(
        self,
        query_time: str,
        source: str | None = None,
        target: str | None = None,
    ) -> list[dict]:
        """Get relationships valid at a specific point in time."""
        # Query: WHERE valid_at <= $time AND (invalid_at IS NULL OR invalid_at > $time)
```

### 4. Conflict Resolution Strategy
**File**: `src/ourgraph/context/conflict.py` (new)

Handle conflicting information:

```python
class ConflictResolver:
    """Resolve conflicts when new context contradicts existing data."""
    
    def resolve(
        self,
        existing: list[dict],
        new: dict,
        strategy: str = "newest",
    ) -> dict:
        """Resolve conflict between existing and new data.
        
        Strategies:
        - "newest": Trust the most recent (default)
        - "highest_confidence": Trust the most confident source
        - "manual": Ask user to decide (CLI interactive)
        - "keep_both": Keep both with validity periods
        """
        # For "A is owned by B" (existing) vs "A is no longer owned by B" (new):
        # 1. Invalidate old relationship (set invalid_at)
        # 2. Create new relationship (or delete if no longer exists)
        # 3. Record provenance
```

### 5. CLI Command for Context Updates
**File**: `src/ourgraph/cli.py` (modify)

Add `update` command:

```python
@app.command("update")
def update(
    context: str = typer.Argument(..., help="Context file path or 'stdin' for piped input"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    strategy: str = typer.Option("newest", "--strategy"),
):
    """Update graph from context source.
    
    Examples:
        ourgraph update context.txt
        ourgraph update news.json --dry-run
        echo "HPG no longer owns ABC" | ourgraph update stdin
    """
    # 1. Read context
    # 2. Parse using appropriate parser
    # 3. Show what will change (if dry-run)
    # 4. Apply updates
    # 5. Show summary
```

### 6. Audit Trail
**File**: `src/ourgraph/graph/audit.py` (new)

Track all changes for accountability:

```python
class AuditTrail:
    """Track all graph changes with provenance."""
    
    async def log_change(self, change: dict) -> None:
        """Log a graph change.
        
        Change format:
        {
            "timestamp": "2024-01-15T10:30:00",
            "action": "invalidate_relationship",
            "details": {
                "source": "HPG",
                "predicate": "SUBSIDIARY_OF",
                "target": "ABC",
                "old_invalid_at": None,
                "new_invalid_at": "2024-01-15",
                "reason": "Context update from user file",
            },
            "user": "cli",
            "source_info": "context.txt",
        }
        """
        # Store in a special "audit_log" node or separate structure
```

### 7. Integrate with Graphiti
**File**: `src/ourgraph/graphiti_layer/ingester.py` (modify)

When context updates occur, also update Graphiti:

```python
async def ingest_context_update(self, changes: list[dict]) -> None:
    """Ingest context updates into Graphiti."""
    for change in changes:
        if change["action"] == "invalidate_relationship":
            body = f"{change['details']['source']} is NO LONGER {change['details']['predicate']} {change['details']['target']}."
        elif change["action"] == "create_relationship":
            body = f"{change['details']['source']} IS {change['details']['predicate']} {change['details']['target']}."
        
        await self._graphiti.add_episode(
            name=f"context_update_{change['timestamp']}",
            episode_body=body,
            source=EpisodeType.text,
            source_description=f"Context update: {change['details']['reason']}",
            reference_time=datetime.now(UTC),
            group_id=self._group_id,
        )
```

### 8. Tests
**File**: `tests/test_context_update.py` (new)

- Test context file parsing (text, JSON)
- Test temporal relationship management
- Test conflict resolution strategies
- Test CLI command
- Test audit trail
- Integration test: full update flow

## Acceptance Criteria
- [ ] `ourgraph update context.txt` updates graph from text file
- [ ] Temporal relationships: old relationships marked invalid when new context contradicts
- [ ] Conflict resolution works (newest, highest_confidence, manual, keep_both)
- [ ] Audit trail logs all changes
- [ ] Graphiti updated with context changes
- [ ] `--dry-run` flag shows changes without applying
- [ ] Can read from stdin: `echo "text" | ourgraph update stdin`
- [ ] All tests pass: `pytest tests/test_context_update.py -v`

## CLI Testing
```bash
# Create a context file
cat > context.txt << EOF
HPG is no longer a subsidiary of ABC Group as of 2024-01-01.
HPG now is a subsidiary of XYZ Holdings with 60% ownership.
Nguyen Van A resigned as CEO of VCB on 2023-12-31.
EOF

# Apply update
ourgraph update context.txt

# Dry run first
ourgraph update context.txt --dry-run

# From stdin
echo "HPG now supplies steel to HSG" | ourgraph update stdin

# Check audit trail
ourgraph audit --limit 10
```

## Example Context File Formats

**Text file (context.txt)**:
```
HPG is no longer a subsidiary of ABC Group as of 2024-01-01.
HPG now is a subsidiary of XYZ Holdings with 60% ownership.
Nguyen Van A resigned as CEO of VCB on 2023-12-31.
VCB now has a new CEO: Tran Thi B.
```

**JSON file (context.json)**:
```json
[
  {
    "subject": "HPG",
    "predicate": "SUBSIDIARY_OF",
    "object": "XYZ Holdings",
    "properties": {"ownership_percent": 60.0, "since_date": "2024-01-01"},
    "valid_at": "2024-01-01",
    "source": "user"
  },
  {
    "subject": "HPG",
    "predicate": "SUBSIDIARY_OF",
    "object": "ABC Group",
    "properties": {},
    "invalid_at": "2024-01-01",
    "source": "user"
  }
]
```

## Notes
- Mechanism should be extremely modular: adding new context sources (news, RSS, APIs) should be trivial
- All updates should be reversible (via audit trail + invalid_at timestamps)
- Consider implementing "ourgraph rollback" command using audit trail
- Future: Add support for specific news sources (CafeF, VnExpress, etc.) as plugins
