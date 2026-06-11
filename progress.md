# Progress

## Status
Phase 0 (baseline) + Phase 3 (CLI helper) + Phase 5 (dead code removal) complete.

## Tasks Completed

### Phase 0 — Baseline Hygiene
- `ruff format` across both repos (25 + 4 files reformatted)
- `ruff check --fix` (170 + 4 auto-fixes across ourgraph + ourportfolios)
- Fixed Ty type-checker issues in quality.py, retry.py, vnstock_macro_fetcher.py

### Phase 3 — CLI Helper (cli.py)
- Added `_run_graph_query()` helper that encapsulates the async-query → print cycle
- Refactored 8 commands (peers, subs, shareholders, insiders, person, shared-insiders, network, cross-shareholding, macro) to use it, saving ~200 lines
- Removed stale `ingest_daily` command (was already a no-op)
- Removed unused `DEFAULT_PRICE_HISTORY_TAIL` import
- Added missing `from rich.panel import Panel` import (was used but never imported)

### Phase 5 — Dead Code Removal
- Removed `src/ourgraph/graph/relationship_manager.py` (263 lines, fully dead — instantiated at builder.py:214 but `self._rel_manager` never read/called)
- Removed `src/ourgraph/graph/relationship_schema.py` (only used by relationship_manager.py + tests)
- Removed corresponding re-exports from `graph/__init__.py` + simplified `__all__`
- Removed `tests/test_relationships.py` (only tested dead RelationshipManager)
- Removed builder.py import of `RelationshipManager` + `self._rel_manager = RelationshipManager(self)`
- Deleted root-level dev scripts: `debug_fpt.py`, `debug_fpt2.py`, `ingest_217.py`, `ingest_5.py`, `ingest_full.py`, `ingest_sync.py`
- Moved `_SUPPLY_CHAIN_MAP` from discovery.py into `constants.py` as `SUPPLY_CHAIN_MAP`
- Updated all references in discovery.py

## Group B — Frontend Optimizations (state.py, components.py, _cytoscape.py)
- **Cache TTL**: 300s → 3600s (1 hour) for `_GRAPH_CACHE`
- **Parsed JSON cache**: Renamed `_raw_graph` → `_parsed_graph`, click handlers now use cached dict instead of re-parsing `json.loads(self.graph_json)` on every click
- **19 toggle methods → 1**: Added `_FILTER_TOGGLE_MAP` + single `toggle_filter("name")` method, replaced all 19 call sites in components.py
- **Removed redundant setInterval watcher**: `components.py` no longer polls every 1s — `MutationObserver` is sufficient
- **Cytoscape cleanup**: Removed duplicated `_edgeLabel` map (was 1:1 with `_EDGE_LABELS` in state.py), added `appendElements()` for lazy loading support
- **Pagination scaffolding**: Added `page`, `page_size`, `has_more` state fields + `load_more_edges()` method
- Ruff errors in graph files: **70 → 30** (all 30 are pre-existing, 0 new from changes)

## Lint & Type Check Status
- **0 new ruff violations** in all Group files (remaining errors are pre-existing in original builder.py/ingesters)
- **Ty on builder package: 0 diagnostics** ✅
- **Ty on full src: 6** (down from 25 baseline — all 6 are pre-existing third-party import issues)
- **Ruff on src: 120** (all pre-existing, none new from changes)
- No CI regressions

## Files Changed (Group A2 — Builder Split)
- **NEW**: `src/ourgraph/graph/builder/_helpers.py` — shared helper functions (is_company_name, normalize_person_name, etc.)
- **NEW**: `src/ourgraph/graph/builder/core.py` — `_GraphBuilderCore` class (connection, index, lifecycle)
- **NEW**: `src/ourgraph/graph/builder/companies.py` — `_CompanyMixin` (companies, sectors, industries, subsidiaries)
- **NEW**: `src/ourgraph/graph/builder/financials.py` — `_FinancialMixin` (statements, indicators)
- **NEW**: `src/ourgraph/graph/builder/people.py` — `_PeopleMixin` (officers, shareholders, persons)
- **NEW**: `src/ourgraph/graph/builder/relations.py` — `_RelationsMixin` (macro, country, auditor, events, bonds, scrapers)
- **NEW**: `src/ourgraph/graph/builder/dedup.py` — `_DedupMixin` (all 9 deduplication methods)
- **NEW**: `src/ourgraph/graph/builder/__init__.py` — combines mixins into final `GraphBuilder` class
- **MODIFIED**: `src/ourgraph/graph/builder.py` — now a 3-line thin re-export
- **MODIFIED**: `src/ourgraph/graph/schema.py` — restored 12 missing Prop constants (PRICE_CURRENT, etc.)
- **MODIFIED**: `src/ourgraph/cli.py` — fixed import of `normalize_person_name` to new location
- **MODIFIED**: `src/ourgraph/ingest/pipeline.py` — added `# type: ignore[attr-defined]` on deduplicate_nodes call

## Files Deleted
- `src/ourgraph/graph/relationship_manager.py` (263 lines, dead code)
- `src/ourgraph/graph/relationship_schema.py` (dead code)
- `tests/test_relationships.py` (tested only dead RelationshipManager)
- `debug_fpt.py`, `debug_fpt2.py`, `ingest_217.py`, `ingest_5.py`, `ingest_full.py`, `ingest_sync.py`

## Architecture Change
- **1,831-line monolith** → **8 files, ~9KB each** with clear domain boundaries
- Mixin inheritance allows Ty to resolve all methods statically (no `setattr` needed)
- `from ourgraph.graph.builder import GraphBuilder` works exactly as before
- All 34 methods verified present

## Notes
- Running alongside parallel Groups A (builder/queries split) and C (CLI + dead code removal) — their file outputs are present on disk but untouched by this group

## Group A1 — Server-Side Layout + Merged Cypher Queries

### Completed
- **Created `src/ourgraph/graph/graph_layout.py`**: Python equivalent of the JS `_formatElements()` function. Includes:
  - Style constants (node colors/shapes, rel colors/styles, edge labels, category map)
  - `_build_sector_map()` — sector assignment from BELONGS_TO edges
  - `_build_node_element()` — single-node formatter (filtering + degree + sizing)
  - `_build_edge_element()` — single-edge formatter (ID generation with stake hash)
  - `format_elements()` — orchestrator
  - `_apply_cluster_layout()` — sector-cluster positioning (large circle of sectors, small circle of companies per sector)
  - `build_style_json()` — serializable style dict for the frontend
  - Taylor-series trig helpers (avoids numpy dependency)

- **Merged Cypher queries in `queries.py`**:
  - `export_graph_json()` now uses a SINGLE MATCH with priority ORDER BY (BELONGS_TO first, then other types)
  - Added `page`, `page_size` parameters with SKIP/LIMIT
  - Returns `has_more` flag for lazy loading
  - Calls `format_elements()` + `build_style_json()` in the response
  - Updated `_export_egonet_json()` to return the same enriched format
  - Refactored `_node_key()` to use dict lookup (fixes PLR0911)

- **Cleaned up `_cytoscape.py`**:
  - `_formatElements()` is now a thin passthrough (returns `graphData.elements` directly)
  - `_buildCyStyle()` reads from `window._graphData.style` instead of hardcoded JS constants
  - Removed ~200 lines of duplicated JS element-building logic (sector map, cluster layout, edge helpers)
  - Removed `_edgeLabel`, `_edgeArrow`, `_edgeLineStyle`, `_edgeWidth`, `_edgeOpacity`, `_nodeFontSize`, `_deriveLabel`, `_sectorToColor` helper functions
  - `initCyGraph()` now accepts `graphData` directly (with `elements` and `style`)
  - Reduced setTimeout init delay from 1100ms to 200ms

- **Updated `state.py`**:
  - `load_graph()` now passes `page=1, page_size=500` to `export_graph_json()`
  - Full response (elements + style) is cached and sent to JS as-is

### Lint & Type Check
- `ruff check src/ourgraph/graph/graph_layout.py src/ourgraph/graph/queries.py` — **0 errors**
- `ruff format --check` — **both files formatted**
- `ty check src/ourgraph/graph/graph_layout.py` — **all checks passed** (0 new diagnostics)
- Pre-existing ty errors in builder.py (unrelated) — unchanged

### Files Changed/Created
- **NEW**: `src/ourgraph/graph/graph_layout.py` (13KB, 250+ lines)
- **MODIFIED**: `src/ourgraph/graph/queries.py` — merged Cypher, pagination, layout integration
- **MODIFIED**: `ourportfolios/pages/graph/_cytoscape.py` — simplified, reads from server style
- **MODIFIED**: `ourportfolios/pages/graph/state.py` — passes page params
