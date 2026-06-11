# OurGraph: Graph Schema Documentation

> LLM-ready knowledge graph for the Vietnamese stock market (VNIndex/HOSE + HNX)

## Project Structure

```
ourgraph/
├── src/ourgraph/
│   ├── __init__.py                # Public API exports
│   ├── config.py                  # Pydantic-settings (all env vars)
│   ├── constants.py               # App constants & defaults
│   ├── cli.py                     # Typer CLI entry point
│   ├── quality.py                 # Graph quality checks
│   ├── db/
│   │   ├── falkordb.py            # FalkorDB async client factory
│   │   └── engine.py              # SQLAlchemy engine (Tiger Data - placeholder)
│   ├── graph/
│   │   ├── __init__.py            # Package exports
│   │   ├── schema.py              # NodeLabel, RelType, Prop constants
│   │   ├── relationship_schema.py # Relationship taxonomy (20 types)
│   │   ├── relationship_manager.py# CRUD + validation for relationships
│   │   ├── discovery.py           # ★ NEW: Hidden relationship discovery engine
│   │   ├── builder.py             # GraphBuilder — core write API
│   │   ├── orm.py                 # Pythonic query API (SQLAlchemy-style)
│   │   └── queries.py             # GraphQueries — read-only polars API
│   ├── graphiti_layer/
│   │   ├── client.py              # Graphiti client factory
│   │   ├── ingester.py            # Episode ingestion logic
│   │   └── search.py              # GraphRAG query interface
│   ├── ingest/
│   │   ├── pipeline.py            # Main ETL orchestrator
│   │   ├── scheduler.py           # APScheduler daemon
│   │   ├── vnstock_fetcher.py     # vnstock API wrapper
│   │   ├── vnstock_macro_fetcher.py
│   │   ├── yfinance_fetcher.py    # Yahoo Finance commodities/indices
│   │   ├── worldbank_fetcher.py   # World Bank indicators
│   │   └── imf_fetcher.py         # IMF indicators
│   ├── llm/
│   │   └── factory.py             # LLM/embedder/reranker factories
│   └── utils/
│       └── retry.py               # Async/sync retry utilities
├── tests/
│   ├── test_graph.py              # Schema & builder unit tests
│   ├── test_config.py             # Config loading tests
│   ├── test_pipeline.py           # Pipeline unit tests
│   ├── test_macro.py              # Macro fetcher tests
│   ├── test_relationships.py      # Relationship system tests (20)
│   └── test_discovery.py          # ★ NEW: Discovery engine tests (23)
├── docs/
│   └── graph-schema.md            # This file
├── scripts/                       # Utility scripts
├── docker-compose.yml             # FalkorDB service
└── pyproject.toml                 # Project config & dependencies
```

## Two-Graph Architecture

Two complementary graphs live in the same FalkorDB instance:

| Graph | Purpose | Query Method |
|-------|---------|-------------|
| `ourgraph` | Raw structured graph (Cypher-queryable) | `GraphBuilder`, `GraphQueries`, ORM |
| `ourgraph_graphiti` | Temporal graph with NL episodes | `GraphRAGSearch.query()` |

## Node Labels (12 types)

| Node Label | Key Property(s) | Description |
|-----------|-----------------|-------------|
| `Company` | `symbol` | Listed company or institutional entity |
| `Person` | `person_name` | Individual — officer, shareholder, or both |
| `Sector` | `name` | Broad sector grouping (e.g., "Financials") |
| `Industry` | `name` | ICB industry classification |
| `StockPrice` | `symbol`, `date` | Daily OHLCV snapshot |
| `Indicator` | `symbol`, `year`, `quarter` | Financial ratios (PBR, PER, EPS) |
| `FinancialStatement` | `symbol`, `statement_type`, `year`, `quarter` | BS/IS/CF in JSON payload |
| `Date` | `date` | Calendar date (ISO format) |
| `Quarter` | `year`, `quarter` | Fiscal quarter |
| `Year` | `year` | Fiscal year |
| `MacroIndicator` | `name`, `date`, `country`, `source` | Economic indicators |
| `Country` | `code` | ISO 2-letter country code |

### Company Node Properties

| Property | Type | Description |
|----------|------|-------------|
| `symbol` | str | Ticker symbol (indexed) |
| `name` | str | Full company name |
| `exchange` | str | HOSE or HNX |
| `market_cap` | float | Market capitalization (VND) |
| `no_employees` | int | Employee count |
| `established_year` | str | Founding year |
| `website` | str | Company website |
| `outstanding_share` | float | Shares outstanding |
| `foreign_percent` | float | Foreign ownership % |

## Relationship Types (20 types)

### Ownership & Control

| Relationship | Source → Target | Properties | Temporal |
|-------------|----------------|------------|----------|
| `SUBSIDIARY_OF` | `Company` → `Company` | `ownership_percent`, `relation_type` | Yes |
| `HOLDS_STAKE_IN` | `Company` \| `Person` → `Company` | `stake_percent` | Yes |

### Competition & Market

| Relationship | Source → Target | Properties | Notes |
|-------------|----------------|------------|-------|
| `COMPETES_WITH` | `Company` ↔ `Company` | — | Symmetric (BOTH direction) |

### People & Roles (★ expanded in Session 1)

| Relationship | Source → Target | Properties | Temporal |
|-------------|----------------|------------|----------|
| `IS_OFFICER` | `Person` → `Company` | `position`, `own_percent` | Yes |
| `IS_BOARD_MEMBER` | `Person` → `Company` | `position`, `since_date` | Yes |
| `IS_FOUNDER` | `Person` → `Company` | `position`, `since_date` | Yes |
| `IS_EXECUTIVE` | `Person` → `Company` | `position`, `since_date` | Yes |

Derived role edges are created automatically during ingestion by `upsert_officer_roles()`, which classifies officers by position keywords:
- **Board**: chairman, vice chairman, independent director, board member (Vietnamese: chủ tịch HĐQT, phó chủ tịch HĐQT, thành viên HĐQT)
- **Founder**: founder, co-founder, sáng lập, đồng sáng lập
- **Executive**: CEO, CFO, COO, CTO, president, general director (Vietnamese: tổng giám đốc, giám đốc)

### Company Classification

| Relationship | Source → Target | Description |
|-------------|----------------|-------------|
| `BELONGS_TO` | `Company` → `Sector` | Sector membership |
| `BELONGS_TO_INDUSTRY` | `Company` → `Industry` | Industry membership |

### Temporal / Data Hierarchy

| Relationship | Source → Target | Description |
|-------------|----------------|-------------|
| `HAS_STOCK_PRICE` | `Company` → `StockPrice` | Company → price record |
| `HAS_INDICATOR` | `Company` → `Indicator` | Company → financial ratio |
| `HAS_FINANCIAL_STATEMENTS` | `Company` → `FinancialStatement` | Company → financial statement |
| `RECORDED_ON` | `StockPrice` → `Date` | Price → date |
| `MEASURED_ON` | `Indicator` \| `MacroIndicator` → `Quarter` \| `Date` | Measurement period |
| `FOR_QUARTER` | `FinancialStatement` → `Quarter` | Statement → quarter |
| `FOR_YEAR` | `FinancialStatement` → `Year` | Statement → year |
| `IN_QUARTER` | `Date` → `Quarter` | Date → quarter |
| `IN_YEAR` | `Quarter` → `Year` | Quarter → year |

### Macro

| Relationship | Source → Target | Properties |
|-------------|----------------|------------|
| `HAS_MACRO_INDICATOR` | `Country` → `MacroIndicator` | — |
| `AFFECTS_SECTOR` | `MacroIndicator` → `Sector` | `reason` |
| `AFFECTS_INDUSTRY` | `MacroIndicator` → `Industry` | `reason` |

## Database Indices

Created by `GraphBuilder.ensure_indices()` on first `ourgraph setup`:

```cypher
CREATE INDEX ON :Company(symbol)
CREATE INDEX ON :Company(name)
CREATE INDEX ON :Person(person_name)
CREATE INDEX ON :Sector(name)
CREATE INDEX ON :Industry(name)
CREATE INDEX ON :StockPrice(symbol, date)
CREATE INDEX ON :FinancialStatement(symbol, year, quarter)
CREATE INDEX ON :Indicator(symbol, year, quarter)
CREATE INDEX ON :Date(date)
CREATE INDEX ON :Quarter(year, quarter)
CREATE INDEX ON :Year(year)
CREATE INDEX ON :MacroIndicator(name)
CREATE INDEX ON :MacroIndicator(date)
CREATE INDEX ON :MacroIndicator(country)
CREATE INDEX ON :MacroIndicator(category)
CREATE INDEX ON :Country(code)
CREATE INDEX ON :Country(name)
```

Graphiti maintains its own internal BM25, vector, and graph indices on the `ourgraph_graphiti` graph.

## Relationship Schema Registry (★ NEW in Session 1)

The `relationship_schema.py` module defines a complete taxonomy with validation:

```python
RELATIONSHIP_REGISTRY: dict[str, RelationshipDescriptor]
```

Each descriptor validates:
- **Source/target labels**: e.g., `SUBSIDIARY_OF` only allows `Company → Company`
- **Allowed properties**: e.g., `IS_OFFICER` allows `position`, `own_percent` but not `stake_percent`
- **Direction**: OUT, IN, or BOTH (symmetric)
- **Temporal support**: Whether the relationship tracks `since_date`/`until_date`

### Validation API

```python
from ourgraph.graph import validate_relationship, list_relationship_types

# Validate a relationship
valid, msg = validate_relationship("SUBSIDIARY_OF", "Company", "Company")
# → (True, "")

valid, msg = validate_relationship("SUBSIDIARY_OF", "Person", "Company")
# → (False, "Invalid source label 'Person' for relationship SUBSIDIARY_OF...")

# List all types involving Company
types = list_relationship_types(source_label="Company")
```

## Hidden Relationship Discovery Engine (★ NEW in Session 2)

The `GraphDiscovery` class in `graph/discovery.py` infers non-obvious relationships from the existing graph structure and price data. All methods are exposed via `ourgraph graph discover`.

### Discovery Methods

| Method | What It Finds | Min Threshold |
|--------|---------------|---------------|
| `discover_cross_shareholdings()` | Companies that hold mutual stakes in each other | Combined ≥ 5% |
| `discover_subsidiary_chains()` | Multi-level ownership chains (up to depth 5) | ≥ 1% per link |
| `discover_shared_insiders()` | People serving at 2+ companies with influence scoring | ≥ 2 companies |
| `discover_competitive_insiders()` | People connected to companies that compete with each other | — |
| `infer_supply_chain()` | Supplier → Customer pairs by industry adjacency | Industry match |
| `map_influence_networks()` | Conglomerates, indirect control, board interlocks | 3+ subsidiaries / 2+ boards |
| `discover_correlation_relationships()` | Price-correlated pairs via Pearson r | \|r\| ≥ 0.85, 90d min |

### Supply Chain Industry Map

Supply chain inference matches supplier → customer industries:

| Supplier Industry | Customer Industries |
|-------------------|-------------------|
| Steel | Automotive, Construction, Manufacturing |
| Oil & Gas | Energy, Transportation, Manufacturing |
| Technology | Finance, Retail, Healthcare, Education, Telecom |
| Real Estate | Construction, Finance, Retail |
| Mining | Steel, Energy, Manufacturing |
| Agriculture | Food & Beverage, Retail, Textiles |
| Energy | Manufacturing, Technology, Residential |
| Logistics / Transport | Retail, Manufacturing, E-Commerce |
| Construction | Real Estate, Infrastructure, Industrial |
| Telecom | Technology, Media, Finance |

### Influence Scoring

Shared insiders are scored based on role type:

- **Officer roles** (CEO, CFO, board member): weight = 2.0
- **Shareholder roles**: weight = 1.0
- Score = sum of role weights across all companies held

### CLI Usage

```bash
# Discover all hidden relationships
ourgraph graph discover

# Discover for a specific symbol
ourgraph graph discover --symbol HPG

# With price correlation analysis
ourgraph graph discover --correlation
```

## CLI Commands

```bash
ourgraph setup                         # Create indices + Graphiti constraints
ourgraph ingest full [symbols...]      # Full pipeline
ourgraph ingest daily                  # Daily price update
ourgraph ingest symbol ACB             # Single symbol
ourgraph ingest graphiti               # Re-feed Graphiti from raw graph
ourgraph ingest macro [sources...]     # Macro indicators
ourgraph schedule                      # Daily scheduler daemon
ourgraph query "..."                   # GraphRAG query
ourgraph graph peers ACB               # Sector peers
ourgraph graph subs VCB                # Subsidiaries
ourgraph graph shareholders ACB        # Major shareholders
ourgraph graph insiders VCB            # Officers + individual shareholders
ourgraph graph person "Name"           # Person roles across companies
ourgraph graph prices ACB              # Price history
ourgraph graph discover                # Hidden relationship discovery
ourgraph graph discover --symbol HPG   # Discovery for one symbol
ourgraph graph discover --correlation  # With price correlation
ourgraph graph cross-shareholding      # Mutual holdings
ourgraph graph macro                   # Macro indicators
ourgraph graph stats                   # Graph statistics
ourgraph quality                       # Run quality checks
```

## Configuration

All via environment variables (`.env` file):

| Prefix | Key Settings | Default |
|--------|-------------|---------|
| `FALKORDB_` | `host`, `port`, `graph_name` | localhost:6379, "ourgraph" |
| `OLLAMA_` | `base_url`, `llm_model`, `embedding_model` | localhost:11434, phi3.5, nomic-embed-text |
| `VNSTOCK_` | `source`, `api_delay` | KBS, 3.5s |
| `PIPELINE_` | `batch_size`, `batch_delay`, `financial_quarters` | 5, 10s, 8 |
| `SCHEDULER_` | `cron` | 0 7 * * 1-5 (weekdays 7am) |
| `GRAPHITI_` | `semaphore_limit` | 2 |
| `MACRO_` | `sources`, `start_year` | worldbank,imf,yfinance; 2010 |
