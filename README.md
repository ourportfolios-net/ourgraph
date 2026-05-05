# ourgraph

Vietnamese stock market knowledge graph built on FalkorDB + Graphiti + vnstock + Polars.

Based on the paper: *Knowledge Graph Construction for Stock Markets with LLM-Based Explainable Reasoning* (arXiv:2601.11528)

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| Graph DB | FalkorDB (Docker) | GraphBLAS, #1 GraphRAG-Bench, native Graphiti support |
| Temporal KG / GraphRAG | Graphiti | Hybrid BM25+vector+graph search, temporal facts |
| Data pipeline | Polars | Fast, memory-efficient, no pandas |
| Vietnamese stock data | vnstock 4.0 | HOSE/HNX coverage, company/financial/ownership data |
| Existing data | Supabase (PostgreSQL) | Your existing database — used as priority cache |
| Local LLM + embeddings | Ollama | OpenAI-compatible, fully local, modular |
| Scheduler | APScheduler | Daily batch updates via cron |
| Config | pydantic-settings | 12-factor, all env-vars, nothing hardcoded |
| CLI | Typer + Rich | Clean commands with coloured output |
| Project tooling | uv + ruff + ty | Fast, modern, from Astral |

---

## Prerequisites

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) installed
- [Docker](https://docs.docker.com/get-docker/) installed
- [Ollama](https://ollama.ai) installed and running

---

## Quick Start

### 1. Clone and install

```bash
git clone <your-repo>
cd ourgraph
uv sync
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your values. The minimum required config:

```env
# Required: your Ollama models
OLLAMA_LLM_MODEL=phi3.5          # or qwen3:4b, qwen2.5:7b, etc.
OLLAMA_LLM_SMALL_MODEL=phi3.5
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Optional: your Supabase database
SUPABASE_DB_URL=postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres
```

### 3. Pull Ollama models

```bash
# Embedding model (required by Graphiti)
ollama pull nomic-embed-text

# LLM model — choose one based on your hardware
ollama pull phi3.5          # 3.8B, fastest on your hardware (247 tok/s)
ollama pull qwen2.5:7b      # Better structured output, slower
```

### 4. Start FalkorDB

```bash
docker compose up -d
```

FalkorDB Browser UI will be available at http://localhost:3000

### 5. First-time setup

```bash
uv run ourgraph setup
```

This creates all graph indices in FalkorDB and initialises Graphiti's schema.

### 6. Run the pipeline

```bash
# Ingest everything (all symbols — takes a while)
uv run ourgraph ingest full

# Ingest a single symbol for testing
uv run ourgraph ingest symbol VCB

# Daily price update only (lightweight)
uv run ourgraph ingest daily
```

---

## Commands Reference

```bash
# Show all commands
uv run ourgraph --help

# Show effective configuration
uv run ourgraph info

# === INGESTION ===

# Full pipeline (all symbols)
uv run ourgraph ingest full

# Full pipeline for specific symbols
uv run ourgraph ingest full VCB ACB TCB VNM FPT

# Single symbol
uv run ourgraph ingest symbol ACB

# Today's price update only
uv run ourgraph ingest daily

# === SCHEDULER ===

# Start daily scheduler daemon (blocks, use Ctrl+C to stop)
uv run ourgraph schedule

# === GRAPHRAG QUERIES ===

# Natural language query over the temporal knowledge graph
uv run ourgraph query "What are VCB's main subsidiaries?"
uv run ourgraph query "Which companies does Mizuho Bank hold stakes in?"
uv run ourgraph query "What is FPT's revenue trend over the last 4 quarters?"

# With custom result count
uv run ourgraph query "Top performing stocks by ROE" --results 20

# === GRAPH QUERIES ===

# Get sector peers
uv run ourgraph graph peers VCB
uv run ourgraph graph peers VCB --limit 30

# Get subsidiaries
uv run ourgraph graph subs VCB

# Get major shareholders
uv run ourgraph graph shareholders VCB

# Get price history
uv run ourgraph graph prices ACB
uv run ourgraph graph prices ACB --start 2024-01-01 --end 2024-12-31

# Find cross-shareholding pairs
uv run ourgraph graph cross-shareholding
```

---

## Graph Schema

The knowledge graph implements the schema from the paper:

### Nodes

| Label | Key Properties | Description |
|---|---|---|
| `Company` | `symbol`, `name`, `exchange`, `market_cap` | Listed company |
| `Industry` | `name` | ICB industry classification |
| `Sector` | `name` | ICB sector (top-level) |
| `StockPrice` | `symbol`, `date`, `open`, `high`, `low`, `close`, `volume` | Daily OHLCV |
| `FinancialStatement` | `symbol`, `statement_type`, `period`, `year`, `quarter`, `payload` | Balance sheet / income / cash flow (JSON payload) |
| `FinancialIndicator` | `symbol`, `metric`, `year`, `quarter`, `value` | Financial ratios (PE, ROE, etc.) |
| `Officer` | `officer_name`, `position`, `own_percent` | Board member / executive |

### Relationships

| Type | From → To | Properties |
|---|---|---|
| `BELONGS_TO_INDUSTRY` | Company → Industry | — |
| `INDUSTRY_IN_SECTOR` | Industry → Sector | — |
| `HAS_PRICE` | Company → StockPrice | — |
| `HAS_STATEMENT` | Company → FinancialStatement | — |
| `HAS_INDICATOR` | Company → FinancialIndicator | — |
| `SUBSIDIARY_OF` | Company → Company | `ownership_percent`, `relation_type` |
| `HOLDS_STAKE_IN` | Company → Company | `stake_percent` |
| `LED_BY` | Company → Officer | — |

---

## Architecture

```
ourgraph/
├── src/ourgraph/
│   ├── config.py              # pydantic-settings — all env-driven config
│   ├── cli.py                 # Typer CLI entry point
│   │
│   ├── db/
│   │   ├── falkordb.py        # FalkorDB async client factory
│   │   └── supabase.py        # Supabase/PostgreSQL reader (connectorx + polars)
│   │
│   ├── graph/
│   │   ├── schema.py          # Node labels, rel types, property keys (constants)
│   │   ├── builder.py         # Async graph builder (Cypher MERGE operations)
│   │   └── queries.py         # Read-only graph query helpers
│   │
│   ├── ingest/
│   │   ├── vnstock_fetcher.py # vnstock 4.0 data fetcher → polars DataFrames
│   │   ├── supabase_fetcher.py# Your existing Supabase data → polars DataFrames
│   │   ├── pipeline.py        # ETL orchestrator (batched, idempotent, async)
│   │   └── scheduler.py       # APScheduler daily batch scheduler
│   │
│   ├── llm/
│   │   └── factory.py         # LLM + embedder + reranker factory (modular)
│   │
│   └── graphiti_layer/
│       ├── client.py          # Graphiti + FalkorDriver builder
│       └── search.py          # GraphRAG search interface
│
├── tests/
│   ├── test_config.py
│   ├── test_pipeline.py
│   └── test_graph.py
│
├── .env.example               # All config options documented
├── docker-compose.yml         # FalkorDB service
└── pyproject.toml             # uv project config
```

### Data flow

```
vnstock API ─────────────────────────────────────────────────────┐
                                                                  │
Supabase DB ──► SupabaseFetcher ──► polars DataFrame ──► Pipeline ──► GraphBuilder ──► FalkorDB
(your existing)   (priority cache)    (Polars ETL)         (batched)   (Cypher MERGE)   (raw KG)
                                                                                          │
                                                               Graphiti ◄─────────────────┘
                                                               (temporal KG, GraphRAG)
                                                                  │
                                                            GraphRAGSearch
                                                            (hybrid search)
                                                                  │
                                                              Ollama LLM
                                                            (local inference)
```

### Two graph layers

1. **Raw structured graph** (`ourgraph` graph in FalkorDB)
   Built directly by `GraphBuilder` using Cypher. Contains all structured data: companies, prices, financial statements, ownership. Queried directly via `GraphQueries`.

2. **Temporal knowledge graph** (`ourgraph_graphiti` graph in FalkorDB)
   Managed by Graphiti. Used for GraphRAG queries, temporal fact management, and LLM-powered search. Fed via `GraphRAGSearch.add_text_episode()`.

Both graphs live in the same FalkorDB instance, separate graph names.

---

## Data Sources and Priority

The pipeline uses a **Supabase-first** strategy:

| Data type | Primary | Fallback |
|---|---|---|
| Symbol list | Supabase `tickers.overview_df` | vnstock `Listing.all_symbols()` |
| Company overview | Supabase `tickers.overview_df` | vnstock `Company.overview()` |
| Price history | Supabase `tickers.price_history` | vnstock `Quote.history()` |
| Financial ratios | Supabase `tickers.ratio_quarterly` | vnstock `Finance.ratio()` |
| Officers | Supabase `tickers.officers_df` | vnstock `Company.officers()` |
| Shareholders | Supabase `tickers.shareholders_df` | vnstock `Company.shareholders()` |
| Subsidiaries | — | vnstock `Company.subsidiaries()` (always fresh) |
| Financial statements | — | vnstock `Finance.balance_sheet/income_statement/cash_flow()` |

If `SUPABASE_DB_URL` is not set, the pipeline falls back to vnstock entirely.

---

## Local LLM Notes

Graphiti's entity extraction uses structured output. Performance with small models:

| Model | Structured Output | Speed | Recommendation |
|---|---|---|---|
| `phi3.5` (3.8B) | ⚠️ Unreliable | Fast | Use for query-time only |
| `qwen2.5:7b` | ✅ Good | Medium | Best for entity extraction |
| `qwen3:4b` | ✅ Good | Fast | Good balance |

**Important**: The raw structured graph (Company, StockPrice, etc.) is built directly from structured data **without any LLM calls**. Ollama is only used for:
1. GraphRAG queries at query time
2. Graphiti's `add_text_episode()` for free-text ingestion

This means the knowledge graph works fully even if the LLM is slow or unreliable.

### Recommended Ollama setup for your hardware (AMD Ryzen 7 8845H, 27GB RAM)

```bash
# Best embedding model (required)
ollama pull nomic-embed-text

# Best LLM for structured output at your hardware level
ollama pull qwen2.5:7b     # ~4GB VRAM, good structured output
# or
ollama pull phi3.5          # ~2GB VRAM, fastest, less reliable for JSON

# After pulling, update .env:
# OLLAMA_LLM_MODEL=qwen2.5:7b
# OLLAMA_LLM_SMALL_MODEL=qwen2.5:7b
```

---

## Switching LLM Provider

The LLM layer is fully modular. To switch from Ollama to a different provider, only `src/ourgraph/llm/factory.py` needs to change — no other code is affected.

Current factory builds: `OpenAIGenericClient` → `OpenAIEmbedder` → `OpenAIRerankerClient`, all pointed at Ollama.

To use a cloud provider instead, replace the factory functions with the appropriate Graphiti client classes (e.g. `AnthropicClient`, `GeminiClient`).

---

## Production Deployment

The project is designed for local dev with one-line migration to production.

### FalkorDB

Local: `docker compose up -d`

Production: Same Docker image, or [FalkorDB Cloud](https://app.falkordb.com). Change only:
```env
FALKORDB_HOST=your-production-host
FALKORDB_PORT=6379
FALKORDB_USERNAME=your-user
FALKORDB_PASSWORD=your-password
```

### Scheduler

Run `uv run ourgraph schedule` as a systemd service or Docker container.

### LLM

Replace Ollama with a cloud API by editing `llm/factory.py`. Everything else stays the same.

---

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/

# Type check
uv run ty check src/

# Format
uv run ruff format src/ tests/
```

---

## Troubleshooting

**FalkorDB not reachable**
```
ConnectionRefusedError: [Errno 111] Connect call failed
```
→ Run `docker compose up -d` and wait for the health check to pass.

**Ollama model not found**
```
model "phi3.5" not found
```
→ Run `ollama pull phi3.5` (or whichever model is in your `.env`).

**Graphiti structured output failures**
```
1 validation error for ExtractedEntities
```
→ Try a larger/better model (`qwen2.5:7b`). Or reduce `body` length in `add_text_episode()`. The raw graph ingestion is unaffected.

**vnstock rate limiting**
```
HTTPError 429
```
→ Increase `PIPELINE_BATCH_DELAY` in `.env` (e.g. `5.0`).

**Supabase connection failure**
```
RuntimeError: Supabase query failed
```
→ Check `SUPABASE_DB_URL` format. The pipeline falls back to vnstock automatically if this is not set.