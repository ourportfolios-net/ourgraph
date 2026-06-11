# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ourgraph is a Vietnamese stock market knowledge graph built on FalkorDB + Graphiti, enabling LLM-powered reasoning over company relationships, ownership chains, sector groupings, and insider networks across all VNIndex (HOSE) constituents.

Two complementary graphs live in the same FalkorDB instance:
- **`ourgraph`** — raw structured graph with precise Cypher-queryable nodes (Company, Person, Sector, StockPrice, etc.)
- **`ourgraph_graphiti`** — temporal graph with natural-language episodes for LLM queries

## Common Commands

```bash
# Install dependencies
uv sync

# Lint
uvx ruff check .

# Type check (used in CI)
uvx ty check

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_graph.py -v

# Run a specific test
uv run pytest tests/test_graph.py::test_node_labels_defined -v

# Run the CLI
uv run ourgraph --help

# First-time setup (indices + Graphiti constraints)
uv run ourgraph setup

# Full pipeline (all ~400 VNIndex symbols)
uv run ourgraph ingest full

# Single symbol (useful for testing)
uv run ourgraph ingest symbol HPG

# Re-feed Graphiti from existing raw graph
uv run ourgraph ingest graphiti

# Query the knowledge graph
uv run ourgraph query "What are HPG's main subsidiaries?"
```

## Architecture

```
vnstock API / Supabase
    │
    ▼
Pipeline (ingest/pipeline.py)
    ├─► GraphBuilder (graph/builder.py) ──────► FalkorDB (raw graph: ourgraph)
    │       MERGE-based idempotent writes
    │       Nodes: Company, Person, Sector, Industry,
    │              StockPrice, Indicator, FinancialStatement
    │
    └─► GraphitiIngester (graphiti_layer/ingester.py) ──► FalkorDB (temporal: ourgraph_graphiti)
            Text episodes per company/sector/conglomerate
                    │
                    ▼
              GraphRAGSearch (graphiti_layer/search.py)
              LLM-powered queries via ourgraph query "..."
```

## Key Patterns

- **Async throughout**: Most code is async (FalkorDB writes, pipeline steps). Tests use `asyncio_mode = "auto"` in pytest.
- **Configuration**: Centralized in `config.py` using pydantic-settings. All values come from environment variables / `.env` file with `FALKORDB_`, `OLLAMA_`, `VNSTOCK_`, `PIPELINE_`, `GRAPHITI_`, `SCHEDULER_` prefixes.
- **Idempotent writes**: GraphBuilder uses Cypher `MERGE` — safe to re-run pipelines.
- **Person vs Company classification**: `graph/builder.py` classifies shareholders using Vietnamese-aware heuristics (`_is_company_name()`). Person nodes can have both `IS_OFFICER` and `HOLDS_STAKE_IN` edges.
- **Batch + delay**: Pipeline processes symbols in batches (`PIPELINE_BATCH_SIZE`) with delays (`PIPELINE_BATCH_DELAY`) to respect vnstock rate limits.

## Code Style

- **Linter**: ruff with ALL rules enabled (see `pyproject.toml` for ignored rules: ANN201, D100-D104, D107, D203, D213, E501, ERA001, PLC0415)
- **Type checker**: ty (in CI via `ty check`)
- **Python version**: 3.13+
- **No docstrings required**: Ruff rule D100-D104 are ignored

## CI

GitHub Actions runs on PRs to main and pushes to main:
- `ruff` check (astral-sh/ruff-action)
- `ty` check (JacobCoffee/ty-action)
- On main pushes: python-semantic-release for versioning

## Prerequisites for Local Development

- FalkorDB: `docker compose up -d` (or `docker run -p 6379:6379 falkordb/falkordb`)
  - Browser UI available at `http://localhost:3333` for visual graph exploration
- Ollama with `phi3.5` (LLM) and `nomic-embed-text` (embeddings)
- Optional: Supabase DB for cached data (speeds up ingestion)

Use `docker compose up -d` to start FalkorDB with persistent volume (`falkordb_data`).
