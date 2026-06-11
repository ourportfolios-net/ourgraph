# Ourgraph Implementation Plan

> Last updated: 2026-05-26
> Author: Hermes Agent (deepseek-v4-flash)
> Base: `/home/dank/Documents/Codebases/ourportfolios-net/ourgraph`

---

## Status Summary

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1a (KBS Auditor) | ✅ Done | `AUDITED_BY` edges extracted from KBS overview |
| Phase 1b (VCI Events) | ✅ Done via subagent | `get_events()` in fetcher, wired into pipeline |
| Phase 1c (Fix affiliates) | ✅ Done | `type` column inference for VCI affiliate data |
| Phase 2a (CafeF scraper) | ❌ Broken | Subagent built it, but CafeF's API has changed |
| Phase 2b (HNX bonds) | ❌ Broken | Subagent built it, but URL/SSL issues |
| Phase 2c (SCIC scraper) | ❌ Broken | Subagent built it, but URL/Auth issues |
| Phase 3 (PDF+LLM) | ❌ Not started | Requires Phase 2 working first |
| Phase 4 (Schema expansion) | ✅ Done via subagent | 7 new RelTypes registered |
| Phase 5 (Validation) | ❌ Not started | |
| Discovery bugs | ❌ Pre-existing | Cypher alias errors in shared_insiders, subsidiary_chains |
| IMF macro | ❌ DNS fail | `dataservices.imf.org` not reachable from this network |
| yfinance macro | ❌ TypeError | `upsert_macro_indicator` value type parsing |

---

## What's Blocking Progress Now

### Bug 1: CafeF removed per-company CBTT pages
The scraper targets `cafef.vn/du-lieu/hose/{symbol}-cong-bo-thong-tin.chn` which no longer exists. All variants redirect to the generic company profile. The CBTT search page at `cafef.vn/du-lieu/cong-bo-thong-tin.chn` is fully JS-rendered (React-like client-side app). The old API endpoint `ajaxcongbothongtin.ashx` now only serves financial report data.

**Fix:** Use Playwright to render the CBTT search page and extract disclosures from the live DOM. Or reverse-engineer the new API endpoint from the rendered page's network requests.

### Bug 2: HNX SSL + URL change
`hnx.vn/en-vn/trai-phieu` and `hnx.vn/vi-vn/trai-phieu` both redirect to ASP.NET error pages. The site requires `verify=False` for httpx due to SSL cert issues.

**Fix:** Playwright to find the correct URL path. The site uses ASP.NET webforms which may require POSTbacks or session state.

### Bug 3: SCIC portfolio URL 404
`scic.vn/vi/danh-muc-dau-tu` and variations return 404. The main page has no portfolio tables in the static HTML.

**Fix:** Playwright to navigate SCIC and find portfolio data. May require authentication or be behind a login wall.

### Bug 4: Discovery shared_insiders FalkorDB alias error
```
_AR_EXP_UpdateEntityIdx: Unable to locate a value with alias co_roles within the record
```
The Cypher query in `src/ourgraph/graph/discovery.py` around line 212 uses `WITH ... co_roles ...` but the alias doesn't exist in the projection.

**Fix:** Read the query, trace the WITH clause projections, ensure `co_roles` is properly defined before being referenced.

### Bug 5: yfinance upsert_macro_indicator value type
```
Failed to parse query parameter 'value' value
```
yfinance returns data in a format that `builder.upsert_macro_indicator()` doesn't expect.

**Fix:** Check the yfinance fetcher output columns and ensure they match what `upsert_macro_indicator()` expects (column named `value`, correct float type).

---

## Rollout Plan

### Step 1: Fix Discovery Bugs (1 session, ~1 hour)

**Files:**
- `src/ourgraph/graph/discovery.py`

**What to do:**
1. Read `discover_subsidiary_chains()` — fix the `NOT EXISTS { MATCH }` syntax (partially done, but verify `WHERE NOT (z)-[:SUBSIDIARY_OF]->()` works)
2. Read `discover_shared_insiders()` — trace the Cypher WITH clause, find where `co_roles` should be projected but isn't
3. Run `uv run ourgraph ingest test` after fix to verify discovery completes without error

**Acceptance:** `ourgraph graph discover` runs without FalkorDB errors.

---

### Step 2: Install Playwright & Fix Scrapers (2 sessions, ~4 hours)

**Installation:**
```bash
cd ~/Documents/Codebases/ourportfolios-net/ourgraph
uv pip install playwright
playwright install chromium
```

**2a — Rewrite CafeF scraper (`src/ourgraph/ingest/cafef_scraper.py`)**

The scraper needs to:
1. Use Playwright's sync API (not async — simpler, avoid event loop conflicts)
2. Navigate to `https://cafef.vn/du-lieu/cong-bo-thong-tin.chn`
3. Wait for the disclosure table to render (wait for selector like `.render-table-information-disclosure` or `table` with rows)
4. Search for a symbol in the search box if needed
5. Extract disclosure rows: title, date, URL
6. Use httpx for detail page scraping (those ARE server-rendered HTML)
7. Filter by Vietnamese keyword list (already defined in current scraper)
8. Rate limit: 1 req/s

Alternative approach (if Playwright is too heavy):
1. Use httpx to hit `https://cafef.vn/du-lieu/cong-bo-thong-tin.chn`
2. Parse the page to find the API endpoint the JS calls
3. The page might call a different, undiscovered API endpoint that serves structured CBTT data
4. This requires loading the page in Playwright once to capture network requests

**2b — Rewrite HNX bond scraper (`src/ourgraph/ingest/hnx_bond_scraper.py`)**

1. Use Playwright with `ignore_https_errors=True`
2. Navigate to HNX bond page
3. Wait for bond table to render
4. Extract: issuer, underwriter, interest rate, maturity date, amount
5. Search for the correct URL path first (the Vietnamese path may work through Playwright with JS execution)

**2c — Rewrite SCIC scraper (`src/ourgraph/ingest/scic_scraper.py`)**

1. Use Playwright with `ignore_https_errors=True`
2. Navigate to `https://scic.vn`
3. Look for portfolio/investment section in the rendered DOM
4. If behind login, log that and return empty (graceful skip)
5. Extract company names and ownership percentages

**Acceptance:** Each scraper returns real data when tested individually.

---

### Step 3: Fix yfinance Macro Ingestion (1 session, ~30 min)

**Files:**
- `src/ourgraph/ingest/yfinance_fetcher.py`
- `src/ourgraph/graph/builder.py` (`upsert_macro_indicator`)

**What to do:**
1. Read `yfinance_fetcher.py` — check what columns the DataFrame has after `fetch_ticker()`
2. Read `builder.upsert_macro_indicator()` — check what column names it expects (likely `value`, `name`, `date`)
3. Fix the column mapping in the fetcher to match what the builder expects
4. Fix the `UnboundLocalError` for `pl` (line 85 — `pl` imported in try/except but used in the except handler where `import polars` failed)

**Acceptance:** `uv run ourgraph ingest macro` for yfinance source succeeds.

---

### Step 4: Full Pipeline Integration (1 session, ~1 hour)

**Files:**
- `src/ourgraph/ingest/pipeline.py`
- `src/ourgraph/cli.py`

**What to do:**
1. Wire the fixed scrapers into the pipeline as optional steps (already partially done by subagent)
2. The `--scrape` flag on `ingest test` and `ingest full` should:
   - Run CafeF disclosure scraper for each symbol
   - Run HNX bond scraper (daily, no per-symbol parameter)
   - Run SCIC portfolio scraper (monthly, no per-symbol parameter)
3. Add `--skip-scrape` flag or make scrapers opt-in per source
4. Store `last_scraped_<source>` timestamps on a metadata node to avoid re-scraping

**Acceptance:** `uv run ourgraph ingest test --scrape` produces real relationship data.

---

### Step 5: Validation Pipeline — Phase 5 (1 session, ~2 hours)

**New file:** `src/ourgraph/quality.py` (extend existing or create new)

**What to do:**
1. Add confidence scoring to every edge:
   - VCI/KBS API: 0.95
   - CafeF scrape: 0.80
   - HNX bond scrape: 0.85
   - SCIC scrape: 0.90
   - PDF+LLM: 0.60

2. Add `ourgraph graph validate-relationships` CLI command:
   - Count edges by type and confidence bucket
   - Flag edges with confidence < 0.7
   - Detect orphan nodes (Company with no edges)
   - Detect duplicate edges

3. Add confidence property to builder's edge creation methods (optional — edges already have properties)

**Acceptance:** `ourgraph graph validate-relationships` shows meaningful stats.

---

### Step 6: Frontend Polish (1 session, ~2 hours)

**Files:**
- `ourportfolios/ourportfolios/pages/graph/`

**What to do:**
1. Add all 7 new relationship types to Cytoscape styling (already done by subagent — verify)
2. Add a "confidence" badge to the node detail panel for scraped relationships
3. Add edge label filtering per relationship type (not just the broad "Own", "Compete", "People" categories)
4. Add a legend entry for audit firms (teal) and subsidiaries (gray) — the `company_type` colors
5. Ensure the graph renders properly after a fresh pipeline run (the company_type issue)

---

### Step 7: Daily Scheduler & Automation (1 session, ~1 hour)

**Files:**
- `src/ourgraph/ingest/scheduler.py`
- `src/ourgraph/cli.py`

**What to do:**
1. Add `--scrape` flag to the scheduler's daily cron job
2. Schedule weekly CafeF scraper runs (Sunday morning)
3. Schedule daily HNX bond snapshot
4. Schedule monthly SCIC portfolio check
5. Store last-run timestamps to avoid redundant scrapes

---

## File Index

### Existing (do not delete)
```
src/ourgraph/
├── graph/
│   ├── schema.py              # RelType, Prop constants — expanded by subagent
│   ├── relationship_schema.py  # Relationship descriptors — expanded
│   ├── builder.py              # Core write API — has upsert_auditor, upsert_company_events
│   ├── queries.py              # Read-only queries — export_graph_json fixed
│   ├── discovery.py            # Hidden relationship discovery — has bugs to fix
│   ├── orm.py                  # Pythonic query API
│   └── relationship_manager.py # CRUD+validation
├── ingest/
│   ├── pipeline.py             # ETL orchestrator — has --scrape wiring
│   ├── vnstock_fetcher.py      # vnstock wrapper — has get_events()
│   ├── cafef_scraper.py        # Needs Playwright rewrite
│   ├── hnx_bond_scraper.py     # Needs Playwright rewrite
│   ├── scic_scraper.py         # Needs Playwright rewrite
│   ├── yfinance_fetcher.py     # Has value type bug
│   ├── imf_fetcher.py          # DNS issue (network-dependent)
│   └── worldbank_fetcher.py    # Working
└── cli.py                      # Typer CLI — has --scrape flag
```

### Frontend (ourportfolios)
```
ourportfolios/ourportfolios/pages/graph/
├── components.py               # UI layout — fixed (state counts, layout restored)
├── state.py                    # Graph state — has new relationship colors
├── _cytoscape.py               # JS engine — has new edge labels, company_type colors
└── index.py                    # Page entry — layout restored
```

---

## Effort Estimate

| Step | Effort | Dependencies |
|------|--------|-------------|
| 1. Fix discovery bugs | 1 hour | None |
| 2. Playwright scrapers | 4 hours | Install Playwright |
| 3. Fix yfinance macro | 30 min | None |
| 4. Pipeline integration | 1 hour | Steps 1-3 |
| 5. Validation pipeline | 2 hours | Step 4 |
| 6. Frontend polish | 2 hours | None (can parallelize) |
| 7. Scheduler automation | 1 hour | Step 4 |

**Total remaining: ~11.5 hours** (about 2-3 focused coding sessions)
