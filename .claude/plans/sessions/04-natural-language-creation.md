# Session 4: Natural Language Creation

## Objective
Allow users to create new relationships using natural language via CLI, with LLM extracting the structured relationship from text.

## Context
The user wants to "interact with the Knowledge Graph to query for specific data, create new relationships, and infer insights effortlessly." Currently, relationships can only be created through data ingestion. We need a natural language interface.

## Tasks

### 1. Create NLP Relationship Extractor
**File**: `src/ourgraph/nlp/extractor.py` (new)

Use LLM to extract (subject, predicate, object) triples from natural language:

```python
class RelationshipExtractor:
    """Extract relationship triples from natural language."""
    
    def __init__(self, llm_provider: LLMProvider):
        self._llm = llm_provider
    
    async def extract(self, text: str, context: dict | None = None) -> list[dict]:
        """Extract (subject, predicate, object) triples from text.
        
        Returns:
            [{
                "subject": "HPG",
                "subject_type": "Company",
                "predicate": "SUBSIDIARY_OF",
                "object": "HPG Group",
                "object_type": "Company",
                "properties": {"ownership_percent": 51.0},
                "confidence": 0.95,
                "reasoning": "Text states HPG is a subsidiary of HPG Group with 51% ownership"
            }]
        """
        prompt = self._build_extraction_prompt(text, context)
        response = await self._llm.chat(prompt)
        return self._parse_response(response)
    
    def _build_extraction_prompt(self, text: str, context: dict | None) -> list[dict]:
        """Build prompt for relationship extraction."""
        # Include known entities from graph for disambiguation
        # Include valid relationship types
        # Ask for JSON output with specific schema
```

### 2. Create Entity Resolver
**File**: `src/ourgraph/nlp/entity_resolver.py` (new)

Resolve entity names to graph nodes (handling ambiguity):

```python
class EntityResolver:
    """Resolve natural language entity names to graph nodes."""
    
    async def resolve(self, name: str, expected_type: str | None = None) -> list[dict]:
        """Find matching nodes in graph.
        
        Handles:
        - Exact match: "HPG" → Company with symbol HPG
        - Fuzzy match: "Hoa Phat" → Company with name containing "Hoa Phat" (symbol HPG)
        - Ambiguity: "Nguyen Van A" might match multiple Person nodes
        """
        # 1. Try exact symbol match (for companies)
        # 2. Try exact name match
        # 3. Try fuzzy match (contains, Levenshtein)
        # 4. Return top matches with confidence scores
```

### 3. Add CLI Command for Relationship Creation
**File**: `src/ourgraph/cli.py` (modify)

Add `relate` command:

```python
@app.command("relate")
def relate(
    statement: str = typer.Argument(..., help="Natural language relationship statement"),
    auto_confirm: bool = typer.Option(False, "--yes", "-y"),
):
    """Create relationship from natural language.
    
    Examples:
        ourgraph relate "HPG is a subsidiary of HPG Group"
        ourgraph relate "Nguyen Van A is a board member of VCB"
        ourgraph relate "HPG supplies steel to HSG"
    """
    # 1. Extract relationship using LLM
    # 2. Resolve entities to graph nodes
    # 3. Show confirmation to user
    # 4. Create relationship via GraphBuilder
    # 5. Optionally update Graphiti episode
```

### 4. Confirmation Flow
**File**: `src/ourgraph/cli.py` (continue)

When entities are ambiguous or confidence is low:

```python
def _show_confirmation(self, extracted: list[dict], resolved: list[dict]) -> bool:
    """Show extracted relationship and ask user to confirm."""
    table = Table(title="Extracted Relationship")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Subject", extracted[0]["subject"])
    table.add_row("Predicate", extracted[0]["predicate"])
    table.add_row("Object", extracted[0]["object"])
    table.add_row("Confidence", f"{extracted[0]['confidence']:.0%}")
    
    # If ambiguous, show options
    if len(resolved) > 1:
        console.print("Multiple matches found:")
        for i, match in enumerate(resolved):
            console.print(f"  {i+1}. {match}")
        # Ask user to select
    
    # Ask for confirmation
    return Confirm.ask("Create this relationship?")
```

### 5. Relationship Creation via GraphBuilder
**File**: `src/ourgraph/graph/builder.py` (modify)

Add method to create relationships from extracted data:

```python
async def create_relationship_from_extraction(self, extraction: dict) -> None:
    """Create relationship from LLM-extracted data."""
    subject = extraction["subject"]
    predicate = extraction["predicate"]
    object_ = extraction["object"]
    properties = extraction.get("properties", {})
    
    # Validate predicate is valid
    if predicate not in RelationshipType.ALL:
        raise ValueError(f"Invalid relationship type: {predicate}")
    
    # Create relationship using MERGE
    cypher = f"""
        MATCH (a) WHERE a.symbol = $sub OR a.name = $sub
        MATCH (b) WHERE b.symbol = $obj OR b.name = $obj
        MERGE (a)-[r:{predicate}]->(b)
        SET r += $props
    """
    await self._run(cypher, {
        "sub": subject, "obj": object_, "props": properties
    })
```

### 6. Update Graphiti Episode
**File**: `src/ourgraph/graphiti_layer/ingester.py` (modify)

When a new relationship is created, add a Graphiti episode:

```python
async def add_relationship_episode(self, extraction: dict) -> None:
    """Add episode for newly created relationship."""
    body = f"{extraction['subject']} {self._predicate_to_text(extraction['predicate'])} {extraction['object']}."
    if extraction.get("properties"):
        props = extraction["properties"]
        if "ownership_percent" in props:
            body += f" Ownership: {props['ownership_percent']}%."
        if "since_date" in props:
            body += f" Since: {props['since_date']}."
    
    await self._graphiti.add_episode(
        name=f"user_created_{extraction['subject']}_{extraction['object']}",
        episode_body=body,
        source=EpisodeType.text,
        source_description="User-created relationship via CLI",
        reference_time=datetime.now(UTC),
        group_id=self._group_id,
    )
```

### 7. Tests
**File**: `tests/test_nlp_extraction.py` (new)

- Test relationship extraction with various phrasings
- Test entity resolution (exact, fuzzy, ambiguous)
- Test CLI command with mocked input
- Test confirmation flow
- Test Graphiti episode creation

## Acceptance Criteria
- [ ] `ourgraph relate "HPG is a subsidiary of HPG Group"` works
- [ ] LLM correctly extracts (subject, predicate, object) from various phrasings
- [ ] Entity resolver handles ambiguity and asks user to disambiguate
- [ ] Confirmation flow shows extracted relationship before creation
- [ ] Relationship created in raw graph (FalkorDB)
- [ ] Graphiti episode created for LLM querying
- [ ] User can skip confirmation with `--yes` flag
- [ ] All tests pass: `pytest tests/test_nlp_extraction.py -v`

## CLI Testing
```bash
# Basic relationship creation
ourgraph relate "HPG is a subsidiary of HPG Group"

# With ownership percentage
ourgraph relate "HPG owns 51% of its subsidiary ABC"

# Person relationship
ourgraph relate "Nguyen Van A is the CEO of VCB"

# Supply chain
ourgraph relate "HPG supplies steel to HSG"

# Skip confirmation
ourgraph relate "A is related to B" --yes

# Query the newly created relationship
ourgraph query "What are HPG's subsidiaries?"
```

## Notes
- The LLM prompt should include valid relationship types to constrain extraction
- Entity resolution should be case-insensitive and handle Vietnamese diacritics
- Store provenance: "Created by user via CLI on 2024-01-15"
- Consider adding a `--dry-run` flag to preview without creating
