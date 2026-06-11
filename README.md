# ourgraph

A Vietnamese stock market knowledge graph built on FalkorDB + Graphiti, enabling LLM-powered reasoning over company relationships, ownership chains, sector groupings, and insider networks across all VNIndex (HOSE) constituents.

---

## What it does

ourgraph builds two complementary graphs from vnstock data:

**Raw structured graph (FalkorDB)** — a precise, queryable Cypher graph encoding:
- Company nodes with financials, sector, and exchange metadata
- Person nodes (officers and individual shareholders, deduplicated)
- Ownership chains: `SUBSIDIARY_OF`, `HOLDS_STAKE_IN`
- Insider roles: `IS_OFFICER` (with position as edge property)
- Sector/industry groupings: `BELONGS_TO`, `BELONGS_TO_INDUSTRY`
- Competition: `COMPETES_WITH`
- Price history: `StockPrice → Date → Quarter → Year`

**Graphiti temporal graph** — natural-language episodes ingested from the raw graph, enabling LLM queries like:
- *"What are HPG's main subsidiaries?"*
- *"Which companies would be affected if VCB's stock drops?"*
- *"Who are the shared insiders between ACB and TCB?"*

---

## Architecture

```
vnstock API
    │
    ▼
Pipeline
    ├─► GraphBuilder ──────────────────► FalkorDB (raw structured graph)
    │       Company, Person, Sector,          ourgraph graph
    │       StockPrice, Indicator,
    │       FinancialStatement nodes
    │
    └─► GraphitiIngester ─────────────► FalkorDB (Graphiti temporal graph)
            Text episodes per company,        ourgraph_graphiti graph
            sector groups, conglomerates,
            shared insider networks
                    │
                    ▼
              ourgraph query "..."
              (LLM-powered GraphRAG)
```

Both graphs live in the same FalkorDB instance under different graph names (`ourgraph` and `ourgraph_graphiti`).

---

## Node & relationship schema

### Nodes

| Label | Key property | Description |
|---|---|---|
| `Company` | `symbol` | Listed company or institutional entity |
| `Person` | `person_name` | Individual — officer, shareholder, or both |
| `Sector` | `name` | Broad sector grouping |
| `Industry` | `name` | ICB industry classification |
| `StockPrice` | `symbol, date` | Daily OHLCV snapshot |
| `Indicator` | `symbol, year, quarter` | Financial ratios (PBR, PER, EPS) |
| `FinancialStatement` | `symbol, statement_type, year, quarter` | Balance sheet / income / cash flow (JSON payload) |
| `Date` | `date` | Calendar date |
| `Quarter` | `year, quarter` | Fiscal quarter |
| `Year` | `year` | Fiscal year |

### Relationships

| Relationship | From → To | Key properties |
|---|---|---|
| `IS_OFFICER` | Person → Company | `position`, `own_percent` |
| `HOLDS_STAKE_IN` | Person\|Company → Company | `stake_percent` |
| `SUBSIDIARY_OF` | Company → Company | `ownership_percent`, `relation_type` |
| `COMPETES_WITH` | Company ↔ Company | — |
| `BELONGS_TO` | Company → Sector | — |
| `BELONGS_TO_INDUSTRY` | Company → Industry | — |
| `HAS_STOCK_PRICE` | Company → StockPrice | — |
| `RECORDED_ON` | StockPrice → Date | — |
| `HAS_INDICATOR` | Company → Indicator | — |
| `MEASURED_ON` | Indicator → Quarter | — |
| `HAS_FINANCIAL_STATEMENTS` | Company → FinancialStatement | — |
| `FOR_QUARTER` | FinancialStatement → Quarter | — |
| `FOR_YEAR` | FinancialStatement → Year | — |
| `IN_QUARTER` | Date → Quarter | — |
| `IN_YEAR` | Quarter → Year | — |

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- FalkorDB running locally (`docker run -p 6379:6379 falkordb/falkordb`)
- Ollama running locally with at least:
  - `ollama pull phi3.5` (LLM)
  - `ollama pull nomic-embed-text` (embeddings)

---

## Installation

```bash
git clone <repo>
cd ourgraph
uv sync
```

Copy `.env.example` to `.env` and configure:

```env
# FalkorDB
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
FALKORDB_GRAPH_NAME=ourgraph

# Ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_LLM_MODEL=phi3.5
OLLAMA_LLM_SMALL_MODEL=phi3.5
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_EMBEDDING_DIM=768

# vnstock source (KBS works everywhere, VCI richer but local-only)
VNSTOCK_SOURCE=KBS
VNSTOCK_API_DELAY=1.0

# Pipeline tuning
PIPELINE_BATCH_SIZE=5
PIPELINE_BATCH_DELAY=10.0

# Optional: Supabase for cached data (speeds up ingestion significantly)
SUPABASE_DB_URL=postgresql://...
```

---

## First-time setup

```bash
# Create FalkorDB indices and Graphiti constraints (run once)
uv run ourgraph setup
```

---

## Running the pipeline

```bash
# Full pipeline: fetch all VNIndex (HOSE) stocks → raw graph + Graphiti
uv run ourgraph ingest full

# Single symbol (useful for testing)
uv run ourgraph ingest symbol HPG

# If the raw graph exists but Graphiti is empty, re-feed without re-fetching:
uv run ourgraph ingest graphiti

# Daily price refresh (lightweight, no Graphiti re-ingest)
uv run ourgraph ingest daily

# Run as a daemon on a cron schedule (default: weekdays 07:00)
uv run ourgraph schedule
```

The full pipeline on all ~400 VNIndex symbols takes several hours due to vnstock rate limiting. Use `PIPELINE_BATCH_DELAY` to tune throughput vs. API friendliness.

---

## Querying

### LLM queries (Graphiti)

```bash
uv run ourgraph query "What are HPG's main subsidiaries?"
uv run ourgraph query "Which companies would be affected if VCB's stock drops?"
uv run ourgraph query "Who are the shared insiders between ACB and TCB?"
uv run ourgraph query "What sector does MSN operate in and who are its competitors?"
uv run ourgraph query "Which conglomerates control the most companies on VNIndex?"
```

> **Note:** `ourgraph query` searches Graphiti, which is only populated after running `ourgraph ingest full` or `ourgraph ingest graphiti`. If it returns nothing, run the graphiti ingest first.

### Structured graph queries (Cypher via CLI)

```bash
# Company network (ownership + competition only — no price/indicator noise)
uv run ourgraph graph network
uv run ourgraph graph network --symbol HPG

# Sector peers
uv run ourgraph graph peers VCB

# Ownership
uv run ourgraph graph subs MSN          # subsidiaries
uv run ourgraph graph shareholders VCB  # companies + individual people

# People
uv run ourgraph graph insiders HPG      # officers + individual shareholders for one company
uv run ourgraph graph person "Tran Dinh Long"  # all roles a person holds
uv run ourgraph graph shared-insiders   # people on boards of multiple companies

# Cross-shareholding detection
uv run ourgraph graph cross-shareholding

# Price history
uv run ourgraph graph prices ACB --start 2024-01-01

# Validation
uv run ourgraph graph stats
```

### Direct Cypher (FalkorDB browser or redis-cli)

For visualising the network graph directly in FalkorDB browser:

```cypher
-- Company-to-company network only (no price/fin noise)
MATCH (a:Company)-[r:HOLDS_STAKE_IN|SUBSIDIARY_OF|COMPETES_WITH]->(b:Company)
RETURN a, r, b
LIMIT 200

-- Ego-network for one company
MATCH (c:Company {symbol: 'HPG'})-[r:HOLDS_STAKE_IN|SUBSIDIARY_OF|COMPETES_WITH|IS_OFFICER|BELONGS_TO_INDUSTRY]-(n)
RETURN c, r, n

-- People with roles at multiple companies (hidden influence network)
MATCH (p:Person)-[r:IS_OFFICER|HOLDS_STAKE_IN]->(c:Company)
WITH p, collect(DISTINCT c.symbol) AS companies, COUNT(DISTINCT c) AS n
WHERE n > 1
RETURN p.person_name, companies, n
ORDER BY n DESC

-- All relationships a specific person has
MATCH (p:Person {person_name: 'Tran Dinh Long'})-[r]->(c:Company)
RETURN p, r, c
```

---

## Maintenance

```bash
# Remove duplicate nodes (safe to run multiple times)
uv run ourgraph graph dedupe

# Wipe the entire graph (requires --yes confirmation)
uv run ourgraph graph clear --yes

# Print current configuration
uv run ourgraph info
```

---

## How cross-ticker relationship reasoning works

The LLM can infer relationships like "HPG drop → steel sector drop" because the Graphiti ingester builds three types of episodes that encode these links explicitly:

**Company episodes** include sentences like:
> *"HPG competes directly with: NKG, TIS, POM, HSG. A significant change in HPG's stock price may influence investor sentiment toward its sector peers."*

**Sector group episodes** list all companies in the same industry:
> *"The following Vietnamese companies all operate in the Steel Manufacturing industry: HPG, NKG, TIS, POM, HSG... A significant stock price movement in one of these companies is often a leading indicator for the others."*

**Conglomerate episodes** encode parent-subsidiary chains:
> *"MSN (Masan Group) is a conglomerate that controls: MML (Masan MeatLife, 85.7% owned), MHT (Masan High-Tech Materials, 52.1% owned)... Poor performance in any major subsidiary will negatively impact MSN's consolidated earnings and stock price."*

**Shared insider episodes** capture the hidden influence network:
> *"Nguyen Dang Quang has insider roles at multiple VNIndex companies: MSN, MML, VCF... decisions by Nguyen Dang Quang or events affecting their holdings may simultaneously affect the stock prices of all these companies."*

---

## Person vs. Company classification

Shareholders are automatically classified as `Person` or `Company` nodes using a Vietnamese-aware heuristic in `utils/name_classifier.py`. The classifier:

1. Checks for known Vietnamese surnames (Nguyen, Tran, Le, Pham, ...) at position 0 → **Person**
2. Checks for Vietnamese legal form markers (CTCP, TNHH, MTV, ...) → **Company**
3. Checks for institution keywords (Ngân hàng, Quỹ, Tập đoàn, ...) → **Company**
4. Checks for English corporate tokens (JSC, Corp, Fund, Capital, ...) → **Company**
5. Names longer than 6 tokens → **Company**
6. Default → **Person** (conservative — misclassifying a company as a person is recoverable)

A person who is both an officer and a shareholder at the same company is represented as a single `Person` node with both `IS_OFFICER` and `HOLDS_STAKE_IN` edges.

To validate the classifier:
```bash
pytest tests/test_name_classifier.py -v
```

---

## Project structure

```
src/ourgraph/
├── config.py                    # Pydantic-settings, all env vars
├── cli.py                       # Typer CLI entry point
├── db/
│   ├── engine.py                # SQLAlchemy async + sync engines (Supabase)
│   ├── models.py                # ORM models for all Supabase tables
│   ├── fetch_data.py            # Typed query functions → polars DataFrames
│   └── falkordb.py              # FalkorDB async client factory
├── graph/
│   ├── schema.py                # NodeLabel, RelType, Prop constants
│   ├── builder.py               # GraphBuilder — MERGE-based upserts
│   └── queries.py               # GraphQueries — read-only Cypher queries
├── graphiti_layer/
│   ├── client.py                # Graphiti client factory (Ollama + FalkorDB)
│   ├── ingester.py              # GraphitiIngester — raw graph → text episodes
│   └── search.py                # GraphRAGSearch — query interface
├── ingest/
│   ├── pipeline.py              # Main ETL orchestrator
│   ├── vnstock_fetcher.py       # vnstock API wrapper → polars
│   ├── supabase_fetcher.py      # Supabase ORM fetcher → polars
│   └── scheduler.py             # APScheduler daily cron
├── llm/
│   └── factory.py               # Ollama LLM + embedder + reranker factories
└── utils/
    ├── name_classifier.py       # Vietnamese person/company name heuristic
    └── retry.py                 # Async + sync retry decorators
tests/
└── test_name_classifier.py      # Unit tests for name classification (no DB needed)
```