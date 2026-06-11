# Session 7: Performance Optimization + Comprehensive Testing

## Objective
Make the system "blazing fast" and reliable with comprehensive testing and benchmarking.

## Context
The user wants everything "blazing fast and extremely free." We need to:
1. Profile and optimize the ingestion pipeline
2. Optimize Cypher queries
3. Add caching where appropriate
4. Comprehensive test coverage
5. Performance benchmarks

## Tasks

### 1. Profile Ingestion Pipeline
**File**: `scripts/profile_pipeline.py` (new)

Profile the full pipeline to find bottlenecks:

```python
"""Profile the ingestion pipeline."""
import cProfile
import pstats
from ourgraph.ingest.pipeline import Pipeline
from ourgraph.config import get_settings

async def main():
    settings = get_settings()
    pipeline = Pipeline(settings)
    
    # Profile full pipeline
    profiler = cProfile.Profile()
    profiler.enable()
    
    await pipeline.run_full(symbols=["HPG", "VCB", "TCB"][:5])  # Subset for profiling
    
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    stats.print_stats(20)
```

### 2. Optimize Cypher Queries
**Review files**: All files with Cypher queries

Common optimizations:
- **Use parameters**: Already done (`:param` syntax) - good!
- **Add indices**: Already in `ensure_indices()` - good!
- **Avoid Cartesian products**: Review MATCH patterns
- **Use LIMIT**: Already used - good!
- **Profile slow queries**: Use `EXPLAIN` on complex queries

Specific areas to review:
- `graph/builder.py`: Deduplication queries are complex - may be slow on large graph
- `graph/discovery.py`: Discovery algorithms may be expensive (cross-product joins)
- `graphiti_layer/ingester.py`: Episode generation queries

### 3. Add Batch Operations
**File**: `src/ourgraph/graph/builder.py` (modify)

Currently, most operations loop and do individual MERGE. Add batch variants:

```python
async def upsert_companies_batch(self, df: pl.DataFrame) -> None:
    """Batch upsert companies using UNWIND."""
    # Instead of looping through df.to_dicts(), use:
    cypher = """
        UNWIND $rows AS row
        MERGE (c:Company {symbol: row.symbol})
        SET c.name = row.name,
            c.market_cap = row.market_cap,
            ...
    """
    await self._run(cypher, {"rows": df.to_dicts()})
```

Apply batching to:
- `upsert_companies()`
- `upsert_stock_prices()`
- `upsert_financial_indicators()`
- `upsert_officers()`
- `upsert_shareholders()`

### 4. Implement Caching
**File**: `src/ourgraph/utils/cache.py` (new)

Add caching for expensive operations:

```python
"""Caching utilities."""
import functools
import hashlib
import pickle
from pathlib import Path

class QueryCache:
    """Cache for Cypher query results."""
    
    def __init__(self, cache_dir: str = ".cache/ourgraph"):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get(self, query: str, params: dict) -> list | None:
        """Get cached result."""
        key = self._make_key(query, params)
        cache_file = self._cache_dir / f"{key}.pkl"
        if cache_file.exists():
            with open(cache_file, "rb") as f:
                return pickle.load(f)
        return None
    
    def set(self, query: str, params: dict, result: list) -> None:
        """Cache result."""
        ...
    
    def _make_key(self, query: str, params: dict) -> str:
        """Generate cache key from query + params."""
        content = f"{query}:{params}"
        return hashlib.md5(content.encode()).hexdigest()
```

Use caching for:
- Graph statistics (don't recalculate every time)
- Company lookups (symbol → node ID)
- Discovery algorithms (cache intermediate results)

### 5. Memory Optimization
**Review**: Large graph handling

- Use streaming for large DataFrames (polars lazy frames?)
- Clean up large temporary objects
- Monitor memory usage during ingestion of ~400 symbols

### 6. Comprehensive Unit Tests
**Files**: `tests/test_*.py` (review and enhance)

Ensure coverage for:
- `test_graph.py`: ORM tests (already exists)
- `test_config.py`: Config tests (already exists)
- `test_pipeline.py`: Pipeline tests (already exists)
- `test_macro.py`: Macro fetcher tests (already exists)
- `test_relationships.py`: Relationship system (Session 1)
- `test_discovery.py`: Discovery algorithms (Session 2)
- `test_llm_providers.py`: LLM providers (Session 3)
- `test_nlp_extraction.py`: NLP extraction (Session 4)
- `test_context_update.py`: Context updates (Session 5)
- `test_plugins.py`: Plugin system (Session 6)

### 7. Integration Tests
**File**: `tests/test_integration.py` (new)

Test full workflows:
```python
async def test_full_pipeline():
    """Test full ingest → query → discover → update workflow."""
    # 1. Run pipeline with test symbols
    # 2. Query the graph
    # 3. Run discovery
    # 4. Update from context
    # 5. Verify changes
```

### 8. Performance Benchmarks
**File**: `tests/test_performance.py` (new)

```python
"""Performance benchmarks."""
import time

async def benchmark_ingestion(benchmark):
    """Benchmark full ingestion of N symbols."""
    start = time.time()
    # Run pipeline with 10 symbols
    duration = time.time() - start
    # Assert: should complete within X seconds
    assert duration < 60, f"Ingestion took {duration}s, expected < 60s"

async def benchmark_query(benchmark):
    """Benchmark query performance."""
    # Test various queries
    # Assert: simple queries < 100ms, complex queries < 1s
```

### 9. Update CI/CD
**File**: `.github/workflows/ci.yml` (modify)

Add:
- Test coverage reporting
- Performance benchmark step
- `pip install ourgraph` test

## Acceptance Criteria
- [ ] Ingestion pipeline profiled and bottlenecks identified
- [ ] Batch operations implemented for all upsert methods
- [ ] Caching implemented for expensive operations
- [ ] Test coverage > 80% (measure with `pytest --cov`)
- [ ] All integration tests pass
- [ ] Performance benchmarks established
- [ ] Full pipeline (10 symbols) completes in < 60 seconds
- [ ] Simple queries respond in < 100ms
- [ ] Complex queries (discovery) respond in < 5s
- [ ] CI/CD updated with coverage and benchmarks

## CLI Testing
```bash
# Run with profiling
python scripts/profile_pipeline.py

# Run tests with coverage
pytest --cov=src/ourgraph --cov-report=html

# Run performance benchmarks
pytest tests/test_performance.py -v

# Run all tests
pytest -v
```

## Notes
- "Blazing fast" is relative - focus on optimizing the biggest bottlenecks first
- Batch operations can dramatically speed up ingestion (10x+ for some operations)
- Caching helps for repeated queries
- Consider async parallelization for independent operations
- Memory: With ~400 symbols, the graph could have 10,000+ nodes - test at scale
