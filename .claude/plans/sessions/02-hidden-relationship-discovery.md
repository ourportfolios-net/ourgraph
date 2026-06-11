# Session 2: Hidden Relationship Discovery Engine

## Objective
Build algorithms to automatically discover hidden relationships in the knowledge graph that aren't explicitly stated in the data sources.

## Context
The user wants the graph to "illustrate hidden relationships between entities that aren't necessarily clear from first sight." This includes:
- Cross-shareholdings (already partially implemented)
- Shared insiders (already partially implemented)
- Subsidiary chains (multi-level ownership)
- Supply chain inference
- Influence networks
- Price correlation → potential relationships

## Tasks

### 1. Enhance Cross-Shareholding Detection
**File**: `src/ourgraph/graph/discovery.py` (new)

Improve existing logic in `graph/queries.py::find_cross_shareholding()`:
```python
async def discover_cross_shareholdings(self, min_stake_pct: float = 1.0) -> list[dict]:
    """Find A holds stake in B, and B holds stake in A."""
    cypher = """
        MATCH (a:Company)-[r1:HOLDS_STAKE_IN]->(b:Company)
              -[r2:HOLDS_STAKE_IN]->(a)
        WHERE r1.stake_percent >= $min_pct AND r2.stake_percent >= $min_pct
        RETURN a.symbol, b.symbol, r1.stake_percent, r2.stake_percent
    """
    # Return enriched with context: industry overlap, etc.
```

### 2. Multi-Level Subsidiary Chain Analysis
**File**: `src/ourgraph/graph/discovery.py` (continue)

```python
async def discover_subsidiary_chains(self, max_depth: int = 5) -> list[dict]:
    """Find A owns B owns C owns D... patterns."""
    cypher = """
        MATCH path = (a:Company)-[:SUBSIDIARY_OF*2..{max_depth}]->(z:Company)
        RETURN [n in nodes(path) | n.symbol] AS chain,
               [r in relationships(path) | r.ownership_percent] AS ownership_pcts
        ORDER BY length(path) DESC
    """
    # Calculate effective ownership: pct1 * pct2 * ... * pctN / 100^(N-1)
```

### 3. Shared Insider Networks
**File**: `src/ourgraph/graph/discovery.py` (continue)

Enhance `find_shared_insiders()` from `graph/queries.py`:
- Find people who sit on boards of competing companies
- Find people who hold stakes in multiple competitors
- Calculate "influence score" based on positions + stake percentages
- Detect cascading influence: Person → Company A → Subsidiary B → Company C

### 4. Supply Chain Inference
**File**: `src/ourgraph/graph/discovery.py` (continue)

Infer supply chain from:
- **Industry relationships**: Steel companies supply auto manufacturers
- **Financial statement clues**: Large "cost of goods sold" might indicate suppliers
- **Geographic clustering**: Companies in same industrial zones often have supply relationships
- **Price correlation**: If A's stock moves with B's input costs, they might be supplier-customer

```python
async def infer_supply_chain(self) -> list[dict]:
    """Infer supplier-customer relationships."""
    # Method 1: Industry-based
    # Steel companies supply to:
    #   - Automotive (HPG, HSG → car manufacturers)
    #   - Construction (HPG → real estate, infrastructure)
    #   - Appliances (HPG → electronics)
    
    # Method 2: Financial statement analysis
    # Look for "major suppliers" or "major customers" in notes
    
    # Method 3: Correlation + industry logic
```

### 5. Influence Network Mapping
**File**: `src/ourgraph/graph/discovery.py` (continue)

Map hidden influence:
- **Conglomerate detection**: Companies with 3+ subsidiaries
- **Indirect control**: A controls B (51%), B controls C (60%) → A effectively controls C (30.6%)
- **Board interlocks**: Person on boards of A and B → implicit A-B relationship
- **Cross-shareholding influence**: A holds 10% of B, B holds 10% of A → mutual influence

```python
async def map_influence_networks(self) -> dict[str, list]:
    """Map all influence relationships."""
    return {
        "conglomerates": await self._detect_conglomerates(),
        "indirect_control": await self._calculate_indirect_ownership(),
        "board_interlocks": await self._find_board_interlocks(),
        "cross_influence": await self._analyze_cross_shareholding_influence(),
    }
```

### 6. Price Correlation → Relationship Discovery
**File**: `src/ourgraph/graph/discovery.py` (continue)

Use historical price data to find correlations:
```python
async def discover_correlation_relationships(self, min_corr: float = 0.7) -> list[dict]:
    """Find companies whose stock prices move together."""
    # For each pair of companies:
    # 1. Get price history
    # 2. Calculate Pearson correlation
    # 3. If > threshold, flag as potential relationship
    # 4. Cross-reference with known relationships
    # 5. Suggest new relationship if correlation unexplained
```

### 7. Integrate with Graphiti Episodes
**File**: `src/ourgraph/graphiti_layer/ingester.py` (modify)

After discovery runs, create episodes for discovered relationships:
```python
async def _ingest_discovered_relationships(self) -> None:
    """Create Graphiti episodes for discovered hidden relationships."""
    discovery = GraphDiscovery(self._raw_client, self._raw_graph_name)
    
    # Cross-shareholdings
    cross = await discovery.discover_cross_shareholdings()
    for item in cross:
        body = f"{item['a']} and {item['b']} have mutual stakeholding..."
        await self._graphiti.add_episode(...)
    
    # Influence networks
    influence = await discovery.map_influence_networks()
    # Create episodes for each influence type...
```

### 8. CLI Command for Discovery
**File**: `src/ourgraph/cli.py` (modify)

Add command:
```python
@graph_app.command("discover")
def graph_discover(
    symbol: str = typer.Option(None, "--symbol", "-s"),
    type: str = typer.Option("all", "--type", "-t"),
):
    """Discover hidden relationships in the graph."""
    # Run discovery algorithms
    # Display results in nice table
```

### 9. Tests
**File**: `tests/test_discovery.py` (new)

- Test each discovery algorithm
- Mock graph data for consistent testing
- Test integration with Graphiti ingestion
- Performance test: discovery on full ~400 symbol graph

## Acceptance Criteria
- [ ] Cross-shareholding detection improved (with context)
- [ ] Multi-level subsidiary chains discovered (up to 5 levels)
- [ ] Shared insider networks mapped with influence scores
- [ ] Supply chain inference implemented (at least 2 methods)
- [ ] Influence networks mapped (conglomerates, indirect control)
- [ ] Price correlation discovery implemented
- [ ] Discovered relationships fed to Graphiti
- [ ] CLI command `ourgraph graph discover` works
- [ ] All tests pass: `pytest tests/test_discovery.py -v`

## CLI Testing
```bash
# Discover all hidden relationships
ourgraph graph discover

# Discover for specific symbol
ourgraph graph discover --symbol HPG

# Discover specific type
ourgraph graph discover --type cross-shareholding
ourgraph graph discover --type supply-chain
ourgraph graph discover --type influence
```

## Notes
- Discovery algorithms should be explainable: "Why was this relationship suggested?"
- Store discovery provenance: "Discovered via price correlation (r=0.85)"
- Some discoveries might be wrong - allow user confirmation before creating edges
- Performance: Discovery on 400 symbols could be expensive - consider batching
