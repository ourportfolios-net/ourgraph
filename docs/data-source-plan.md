# Ourgraph Data Source Plan

> Research date: 2026-05-25
> Goal: Find free/accessible data sources for hidden corporate relationships in the Vietnamese stock market.
> Rule: **Only scrape when no API exists.**

---

## Executive Summary

**Current state:** Pipeline uses `vnstock` (VCI + KBS sources) for company overviews, shareholders, subsidiaries, officers, prices, financials, and ratios. This covers ~60% of useful relationships.

**Gap:** No free API provides lending, related-party transactions, guarantees, supply chain, JV, or underwriting relationships. These require scraping or PDF parsing.

**Key finding:** VCI's `/relationship` endpoint and KBS's `/profile` endpoint already provide richer data than what the pipeline currently uses. **First step is enabling existing unused endpoints before building scrapers.**

---

## Phase 1: Enable Existing Unused API Endpoints (No Scraping)

### 1a. KBS Profile — Single-call company data

**Source:** `https://kbbuddywts.kbsec.com.vn/iis-server/investment/stockinfo/profile/{symbol}`
**Cost:** Free, no auth
**Currently:** Not used (pipeline only uses VCI via vnstock)

Add a `KbsFetcher` class that calls this endpoint once per symbol and extracts:

| Field | Graph Relationship |
|-------|-------------------|
| `Subsidiaries[].name` + `ownership_percent` | `SUBSIDIARY_OF` (enriched) |
| `Leaders[].name` + `position` | `IS_OFFICER` / `IS_BOARD_MEMBER` / `IS_EXECUTIVE` |
| `Shareholders[].name` + `ownership_percentage` | `HOLDS_STAKE_IN` (enriched) |
| `Ownership[].owner_type` + `ownership_percentage` | Ownership structure breakdown |
| `Auditor` | **NEW:** `AUDITED_BY` → `Company` node |
| `CharterCapital[].date` + `value` | Capital history (metadata) |

**Implementation:** `src/ourgraph/ingest/kbs_fetcher.py` — ~150 lines, pure `httpx` GET + JSON parse.

### 1b. VCI Events/News — Corporate action signals

**Source:** `https://iq.vietcap.com.vn/api/iq-insight-service/v1/news-events-for-chart?ticker={symbol}`
**Cost:** Free, no auth
**Currently:** Not used

Provides corporate action codes: `DIV` (dividend), `ISS` (issuance), etc. Useful for:
- Detecting bond issuances → triggers deeper bond data collection
- Detecting capital changes → triggers re-fetch of ownership data
- Detecting JV announcements → **NEW:** `HAS_JOINT_VENTURE_WITH`

**Implementation:** Add to `VnstockFetcher` as `get_events(symbol)` method.

### 1c. VCI Relationship endpoint — Already in vnstock, verify coverage

**Source:** `https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{symbol}/relationship`
**Cost:** Free, no auth
**Currently:** Used via `company.subsidiaries()` but only extracts subsidiary name + ownership

The raw response also includes `affiliate` companies (20-50% ownership). Currently the pipeline may discard these. **Fix:** Parse both `subsidiary` and `affiliate` arrays, create:
- `SUBSIDIARY_OF` (ownership > 50%)
- `HOLDS_STAKE_IN` (ownership 20-50%, labeled as affiliate)

**Implementation:** Modify `_normalize_subsidiary_columns` and the builder to handle both types.

---

## Phase 2: Structured Scraping (No PDF, No LLM)

### 2a. CafeF Corporate Disclosures (CBTT)

**Source:** `https://cafef.vn/du-lieu/hose/{symbol}-cong-bo-thong-tin.chn`
**Cost:** Free, public HTML
**Method:** BeautifulSoup parse of disclosure tables

Target disclosure types and the relationships they reveal:

| Disclosure Type (Vietnamese) | Graph Relationship |
|------------------------------|-------------------|
| "Giao dịch với bên liên quan" | `RELATED_PARTY_TRANSACTION` |
| "Bảo lãnh cho khoản vay" | `GUARANTEES` |
| "Cho vay / Tín dụng" | `LENDS_TO` |
| "Liên doanh / Liên kết" | `HAS_JOINT_VENTURE_WITH` |
| "Phát hành trái phiếu" | `UNDERWRITTEN_BY` (from underwriter field) |
| "Thay đổi cổ đông lớn" | `HOLDS_STAKE_IN` (update) |
| "Hợp tác kinh doanh" | `HAS_BUSINESS_COOPERATION` |

**Extraction approach:**
1. Scrape disclosure list page → get URLs + titles + dates
2. Filter by keywords in title (related-party, guarantee, loan, JV, bond, cooperation)
3. For each matching disclosure, scrape the detail page
4. Parse HTML tables for counterparty names, amounts, dates
5. Match counterparty names to known company nodes (fuzzy match on `Company.name`)

**Implementation:** `src/ourgraph/ingest/cafef_scraper.py` — ~300 lines
**Rate limit:** 1 request/second, run once per week (disclosures don't change fast)

### 2b. HNX Bond Market Data

**Source:** `https://hnx.vn/en-vn/trai-phieu` (bond trading page)
**Cost:** Free, public HTML/JSON
**Method:** Parse bond issuance tables

Provides: issuer, underwriter, interest rate, maturity date, issue date

**Relationships:**
- `UNDERWRITTEN_BY` (bond issuer → underwriter bank)
- `LENDS_TO` (bond issuer → lending bank, if bank is the underwriter)

**Implementation:** `src/ourgraph/ingest/hnx_bond_scraper.py` — ~150 lines
**Rate limit:** 1 request/day (daily snapshot is enough)

### 2c. SCIC State Capital Investment Corp

**Source:** `https://scic.vn` (portfolio page)
**Cost:** Free, public HTML
**Method:** Parse portfolio table

Provides: SCIC's ownership stakes in state-owned enterprises

**Relationships:**
- `STATE_OWNS` (SCIC → Company, with ownership %)
- Enriches existing `HOLDS_STAKE_IN` with state ownership flag

**Implementation:** `src/ourgraph/ingest/scic_scraper.py` — ~100 lines
**Rate limit:** 1 request/month (portfolio changes slowly)

---

## Phase 3: PDF Parsing + LLM Extraction (Last Resort)

### 3a. Annual Report PDFs

**Source:** CafeF hosts PDF annual reports at URLs like:
`https://s.cafef.vn/bao-cao-tai-chinh/{symbol}/...`
**Cost:** Free, public PDFs
**Method:** Download PDF → extract text → LLM entity extraction

Target sections in annual reports:
1. **"Giao dịch với bên liên quan"** (Related-party transactions) → `RELATED_PARTY_TRANSACTION`
2. **"Bảo lãnh và cam kết"** (Guarantees and commitments) → `GUARANTEES`
3. **"Khách hàng trọng yếu"** (Major customers) → `CUSTOMER_OF`
4. **"Nhà cung cấp trọng yếu"** (Major suppliers) → `SUPPLIER_TO`
5. **"Khoản vay và nợ"** (Loans and debts) → `LENDS_TO` (with bank names)
6. **"Liên doanh, liên kết"** (Joint ventures, associates) → `HAS_JOINT_VENTURE_WITH`

**Implementation:**
- `src/ourgraph/ingest/pdf_extractor.py` — PDF download + text extraction (PyMuPDF)
- `src/ourgraph/ingest/llm_extractor.py` — LLM entity extraction (reuse existing Ollama setup)
- Prompt template for extracting structured relationships from Vietnamese financial text

**Cost:** Free (local Ollama). ~2 minutes per PDF on CPU, ~20 seconds on GPU.
**Rate limit:** Process 10-20 reports per day to avoid overloading.

### 3b. Bond Issuance Prospectuses

**Source:** HNX or issuer websites publish bond prospectuses as PDF
**Method:** Same PDF pipeline as 3a, target:
- Underwriter → `UNDERWRAN_BY`
- Guarantor → `GUARANTEES`
- Use of proceeds (if lending to specific entities) → `LENDS_TO`

---

## Phase 4: New Relationship Types in Schema

Add to `src/ourgraph/graph/schema.py`:

```python
class RelType:
    # ... existing types ...

    # Phase 1 (from KBS enrichment)
    AUDITED_BY = "AUDITED_BY"  # Company → Company (audit firm)

    # Phase 2 (from scraping)
    RELATED_PARTY_TRANSACTION = "RELATED_PARTY_TRANSACTION"  # Company ↔ Company
    GUARANTEES = "GUARANTEES"  # Company → Company
    LENDS_TO = "LENDS_TO"  # Company → Company (bank → borrower)
    HAS_JOINT_VENTURE_WITH = "HAS_JOINT_VENTURE_WITH"  # Company ↔ Company
    UNDERWRITTEN_BY = "UNDERWRITTEN_BY"  # Company → Company (issuer → bank)
    HAS_BUSINESS_COOPERATION = "HAS_BUSINESS_COOPERATION"  # Company ↔ Company
    STATE_OWNS = "STATE_OWNS"  # Company → Company (state entity)

    # Phase 3 (from PDF parsing)
    CUSTOMER_OF = "CUSTOMER_OF"  # Company → Company
    SUPPLIER_TO = "SUPPLIER_TO"  # Company → Company
```

Add to `src/ourgraph/graph/relationship_schema.py` with proper source/target validation.

---

## Phase 5: Relationship Validation Pipeline

Build a validation layer that runs after every ingestion batch:

### 5a. Schema Validation (already exists)
`RelationshipManager.create()` validates source/target labels. **Keep as-is.**

### 5b. Confidence Scoring (new)
Every new edge gets a confidence score based on source:

| Source | Confidence | Reason |
|--------|-----------|--------|
| VCI/KBS API (direct) | 0.95 | Official securities company data |
| CafeF disclosure scrape | 0.80 | Official disclosure, but parsed from HTML |
| HNX bond scrape | 0.85 | Official exchange data |
| PDF + LLM extraction | 0.60 | LLM may hallucinate; needs human review |
| SCIC scrape | 0.90 | Official state data |

### 5c. Validation CLI command (new)
```bash
ourgraph graph validate-relationships
```
Outputs:
- Total edges by type and confidence bucket
- Edges with confidence < 0.7 (flagged for review)
- Orphan edges (company node missing)
- Duplicate edges (same source/target/type)

### 5d. Manual Review Queue (new)
Low-confidence edges go into a review queue. In ourportfolios dashboard:
- Show "unverified" badge on low-confidence edges
- Allow manual approve/reject
- Approved edges get confidence bumped to 1.0

---

## Implementation Order

| Phase | Task | Effort | Impact |
|-------|------|--------|--------|
| **1a** | KBS profile fetcher | 2 hours | High — adds AUDITED_BY, enriches ownership |
| **1b** | VCI events endpoint | 1 hour | Medium — corporate action signals |
| **1c** | Fix VCI relationship parsing | 1 hour | High — captures affiliates |
| **2a** | CafeF disclosure scraper | 1 day | **Highest** — related-party, guarantees, JVs |
| **2b** | HNX bond scraper | 4 hours | Medium — underwriting relationships |
| **2c** | SCIC scraper | 2 hours | Low — state ownership enrichment |
| **3a** | PDF + LLM pipeline | 2 days | High — supply chain, lending from reports |
| **3b** | Bond prospectus PDFs | 1 day | Medium — underwriting enrichment |
| **4** | Schema expansion | 2 hours | Required for all above |
| **5** | Validation pipeline | 1 day | Required for data quality |

**Total: ~1 week of focused work**

---

## What NOT to Do

1. **Don't pay for FMP/EOD APIs** — VCI/KBS are richer for VN data and free
2. **Don't scrape cafef.vn for data available via VCI API** — redundant
3. **Don't use LLM for structured data** — only use for free-text PDF extraction
4. **Don't build a generic web scraper** — build targeted parsers for specific pages
5. **Don't skip validation** — scraped data will have errors; confidence scoring is essential

---

## Data Source Quick Reference

| Source | URL Pattern | Auth | Cost | Data |
|--------|------------|------|------|------|
| VCI Company | `iq.vietcap.com.vn/api/iq-insight-service/v1/company/` | None | Free | Shareholders, subsidiaries, events |
| KBS Profile | `kbbuddywts.kbsec.com.vn/iis-server/investment/stockinfo/profile/` | None | Free | Full profile in one call |
| CafeF Disclosures | `cafef.vn/du-lieu/hose/{symbol}-cong-bo-thong-tin.chn` | None | Free | Related-party, guarantees, JVs, bonds |
| HNX Bonds | `hnx.vn/en-vn/trai-phieu` | None | Free | Bond underwriting |
| SCIC | `scic.vn` | None | Free | State ownership |
| CafeF PDFs | `s.cafef.vn/bao-cao-tai-chinh/` | None | Free | Annual reports (supply chain, lending) |
