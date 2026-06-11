# Session 8: Advanced Query Capabilities + Visualization

## Objective
Enhance query capabilities with multi-hop reasoning, temporal queries, and add graph visualization support.

## Context
The user wants to "query using raw text via an LLM, that might even be able to illustrate hidden relationships between entities." We have basic GraphRAG search (Sessions 1-3), but need more advanced capabilities.

## Tasks

### 1. Enhance GraphRAG Search
**File**: `src/ourgraph/graphiti_layer/search.py` (modify)

Add advanced search capabilities:

```python
class GraphRAGSearch:
    """Enhanced GraphRAG search."""
    
    async def query_multi_hop(
        self,
        question: str,
        max_hops: int = 3,
        num_results: int = 10,
    ) -> list[dict]:
        """Query with multi-hop reasoning.
        
        Example: "How is HPG connected to VCB?"
        → Might find: HPG → subsidiary → parent → shareholder → VCB
        """
        # 1. Start with entity extraction from question
        # 2. Find direct relationships (1-hop)
        # 3. Expand to 2-hop, 3-hop, ... up to max_hops
        # 4. Return all paths found
    
    async def query_comparative(
        self,
        entities: list[str],
        question: str,
    ) -> dict:
        """Compare multiple entities.
        
        Example: "Compare HPG and HSG"
        → Returns comparative analysis across metrics
        """
        # Fetch data for each entity
        # Use LLM to generate comparison
    
    async def query_temporal(
        self,
        question: str,
        at_time: str | None = None,
    ) -> list[dict]:
        """Temporal query: what was true at a specific time?
        
        Example: "What was HPG's ownership structure in 2022?"
        → Uses valid_at/invalid_at from Session 5
        """
        # Query graph with temporal filters
        # Combine with Graphiti's temporal search
```

### 2. Add Query Templates
**File**: `src/ourgraph/graph/query_templates.py` (new)

Pre-built templates for common questions:

```python
COMMON_QUERIES = {
    "subsidiaries": "What are {symbol}'s subsidiaries?",
    "ownership": "Who owns {symbol} and what are their stakes?",
    "competitors": "Who are {symbol}'s main competitors?",
    "influence": "What is {symbol}'s influence network?",
    "correlation": "Which stocks move with {symbol}?",
    "macro_impact": "How do macro indicators affect {symbol}?",
    "compare": "Compare {symbol1} and {symbol2}",
    "hidden_relationships": "What hidden relationships involve {symbol}?",
}
```

### 3. Query Result Explanation
**File**: `src/ourgraph/graph/explanation.py` (new)

Use LLM to explain query results:

```python
class QueryExplainer:
    """Explain query results in natural language."""
    
    async def explain_results(
        self,
        question: str,
        results: list[dict],
    ) -> str:
        """Generate natural language explanation of results."""
        prompt = f"""
        Question: {question}
        
        Results:
        {self._format_results(results)}
        
        Explain these results in 2-3 sentences, highlighting key insights.
        """
        return await self._llm.chat(prompt)
    
    async def suggest_follow_up(self, question: str, results: list[dict]) -> list[str]:
        """Suggest follow-up questions based on results."""
        # Use LLM to generate related questions
```

### 4. Graph Visualization CLI
**File**: `src/ourgraph/cli.py` (modify)

Add `visualize` command:

```python
@graph_app.command("visualize")
def graph_visualize(
    symbol: str = typer.Argument(..., help="Center node symbol"),
    depth: int = typer.Option(2, "--depth", "-d"),
    format: str = typer.Option("gexf", "--format", "-f"),
    output: str = typer.Option("graph.gexf", "--output", "-o"),
):
    """Visualize subgraph around a company.
    
    Exports to formats:
    - gexf: For Gephi
    - graphml: For yEd, Cytoscape
    - json: For D3.js, vis.js
    - dot: For Graphviz
    
    Examples:
        ourgraph graph visualize HPG --depth 2
        ourgraph graph visualize HPG --format json --output hpg.json
    """
    # 1. Query subgraph (BFS up to `depth` hops)
    # 2. Format as requested output format
    # 3. Write to file
```

### 5. Implement Export Functions
**File**: `src/ourgraph/graph/export.py` (new)

```python
def export_subgraph(
    center: str,
    depth: int,
    format: str,
) -> str:
    """Export subgraph to various formats."""
    # Query FalkorDB for subgraph
    # Convert to format:
    # - GEXF: XML format for Gephi
    # - GraphML: XML format for yEd
    # - JSON: Custom format for D3.js
    # - DOT: Graphviz DOT language
```

### 6. Interactive Query Session
**File**: `src/ourgraph/cli.py` (modify)

Add interactive mode:

```python
@app.command("chat")
def chat():
    """Start interactive query session."""
    console.print("[bold]ourgraph interactive query session[/bold]")
    console.print("Type 'exit' to quit.\n")
    
    while True:
        question = Prompt.ask("ourgraph")
        if question.lower() == "exit":
            break
        
        results = asyncio.run(_query(question))
        explanation = asyncio.run(_explain(question, results))
        
        console.print(f"\n[cyan]Answer:[/cyan] {explanation}\n")
        if results:
            # Show table of results...
```

### 7. Tests
**File**: `tests/test_advanced_queries.py` (new)

- Test multi-hop queries
- Test comparative queries
- Test temporal queries
- Test export functions
- Test visualization output format

## Acceptance Criteria
- [ ] Multi-hop reasoning works: `ourgraph query "How is HPG connected to VCB?"`
- [ ] Comparative queries work: `ourgraph query "Compare HPG and HSG"`
- [ ] Temporal queries work: `ourgraph query "What was HPG's structure in 2022?"`
- [ ] Query result explanation generated by LLM
- [ ] Follow-up questions suggested
- [ ] Visualization export: `ourgraph graph visualize HPG --depth 2`
- [ ] Interactive mode: `ourgraph chat`
- [ ] All tests pass: `pytest tests/test_advanced_queries.py -v`

## CLI Testing
```bash
# Multi-hop query
ourgraph query "How is HPG connected to VCB in 2 hops?"

# Comparative query
ourgraph query "Compare HPG and HSG"

# Temporal query
ourgraph query "What was HPG's ownership in 2022?"

# Visualize
ourgraph graph visualize HPG --depth 2 --format json

# Interactive mode
ourgraph chat
> What are HPG's subsidiaries?
> How does macro affect HPG?
> exit
```

## Notes
- Multi-hop queries may be expensive - consider limiting depth or caching
- Visualization: For very large graphs, consider sampling or filtering
- Interactive mode: Consider adding command history and auto-complete
- Export formats: GEXF and GraphML are widely supported by graph visualization tools
