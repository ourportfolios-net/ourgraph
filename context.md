# Code Context: CafeF Scraper Investigation

## Files Retrieved
1. `src/ourgraph/ingest/cafef_scraper.py` (full file, 382 lines) - Primary scraper with Playwright + AJAX fallback
2. `pyproject.toml` - Dependencies (playwright>=1.60, polars>=1.40, httpx)

## Key Findings

### 1. Playwright CBTT Path is BROKEN
- **File**: `cafef_scraper.py` lines 136-193 (`_fetch_cbtt_playwright`)
- **Root cause**: CafeF removed the old CBTT corporate disclosure search page. The page at `https://cafef.vn/du-lieu/cong-bo-thong-tin.chn` now only shows **BCTC** (financial reports: Báo cáo tài chính), not **CBTT** (corporate disclosures about related-party transactions, guarantees, etc.)
- The AJAX endpoint `ajaxcongbothongtin.ashx` also ONLY returns financial reports (columns: Mã, Tên công ty, Loại báo cáo, Giá trị quý, Thời gian gửi)
- The Playwright scraper tries to interact with a hidden input (`.ac_input`) instead of the visible `#acp-inp-disclosure`
- Even with the correct input, form submission doesn't filter by symbol — the ASP.NET WebForms POST happens but results aren't filtered

### 2. AJAX News API IS the Correct Data Source
- **Endpoint**: `https://cafef.vn/du-lieu/Ajax/PageNew/News.ashx?Symbol=X&NewsType=N&PageIndex=P&PageSize=S`
- Returns 400-512 items per symbol across 4 NewsTypes and 5 pages
- **NewsType breakdown**:
  - 0: General news mentioning the symbol
  - 1: Corporate announcements/disclosures (board resolutions, business registration changes)
  - 2: Dividend/rights announcements
  - 3: Board/personnel changes (appointments, resignations)
- This API IS already used by `_fetch_news_page()` (lines 196-236) as the fallback path

### 3. Keyword Matching is Very Sparse (1-4%)
| Symbol | Total Rows | Matched | Rate |
|--------|-----------|---------|------|
| VNM    | 512       | 5       | 1.0% |
| ACB    | 438       | 16      | 3.7% |
| VIC    | 410       | 17      | 4.1% |

Match breakdown by relationship type:
- **UNDERWRITTEN_BY** (trái phiếu): ACB=8, VIC=9 — bond issuance resolutions
- **RELATED_PARTY_TRANSACTION**: VNM=1, VIC=3 — board approvals for related-party transactions
- **HAS_JOINT_VENTURE_WITH** (liên doanh/liên kết): VNM=4, VIC=1
- **LENDS_TO** (tín dụng): ACB=2 — general credit growth news, not specific counterparties
- **GUARANTEES** (bảo lãnh): VIC=2 — bond guarantees for VinFast

### 4. Counterparty Extraction Has False Positives
The `_extract_counterparty()` function (lines 264-335) extracts many false positives:
- "cùng kỳ năm trước" (same period last year) — from "so với cùng kỳ năm trước"
- "người có liên quan" (related person) — not a company name
- "Các bên liên quan" — generic, not specific
- "4 lần tăng vốn", "6 tháng đầu năm 2023" — time references

Valid counterparties extracted:
- ACB: "ACBC", "ACBA", "ACBS", "ACBL" (subsidiaries: ACB Capital, ACB Securities, ACB Leasing)
- VIC: "Công ty Vinpearl", "VinEnergo", "VinBrain", "Vinhomes", "VHM"
- VNM: None valid (no real counterparties in matched titles)

## Data Flow
```
scrape_disclosures(symbol)
  └─ CafeFDisclosureScraper.fetch_disclosures(symbol)
       ├─ _fetch_cbtt_playwright(symbol)  [BROKEN — returns empty or times out]
       └─ _fetch_news_page(symbol, news_type, page) × 4 types × 5 pages  [WORKS]
            └─ GET News.ashx?Symbol=X&NewsType=N&PageIndex=P&PageSize=30
                 └─ _match_type(title) → rel_type  [sparse: 1-4%]
       └─ scrape_disclosures() also does:
            └─ _extract_counterparty(title, symbol) → counterparty_name  [noisy]
            └─ _extract_amount_from_title(title) → amount
```

## Title Categories Available (untapped)
The AJAX API returns rich disclosure titles that fall outside current keywords:
- **Board resolutions** (Nghị quyết HĐQT): 63-98 per symbol
- **Dividend announcements** (cổ tức): 35-159 per symbol
- **Personnel changes** (bổ nhiệm/từ nhiệm): 12-45 per symbol
- **Shareholder meetings** (ĐHĐCĐ): 38-44 per symbol
- **Transaction notices** (giao dịch cổ phiếu): 11-16 per symbol

## Architecture Issues
1. **Playwright path adds 60s+ latency** with no benefit — always fails, falls back to AJAX
2. **KEYWORD_MAP patterns** (lines 38-48) are too narrow — only 5 patterns covering specific legal terms
3. **Counterparty regex patterns** (`_CP_PATTERNS`, lines 238-262) are regex-greedy and extract non-company text like "cùng kỳ năm trước"
4. **`_is_company_reference()`** (lines 81-85) only checks for "ctcp", "công ty", "tnhh", "ngân hàng", "cổ phần" — misses many valid company references
5. **No distinction between NewsTypes** — all 4 types are scraped identically, but only types 1 and 3 contain disclosures; types 0 and 2 are general news/dividends

## Start Here
1. Open `src/ourgraph/ingest/cafef_scraper.py`
2. Key areas to fix:
   - **Remove the Playwright CBTT path** (lines 136-193) or reduce its timeout to avoid 60s waits
   - **Fix `_CP_PATTERNS`** (lines 238-262) to filter false positives like "cùng kỳ năm", "người có liên quan", time references
   - **Expand KEYWORD_MAP** (lines 38-48) to match more disclosure types (board resolutions about subsidiaries, officer appointments, charter capital changes, M&A announcements)
   - **Consider only scraping NewsType=1 and NewsType=3** (skip general news NewsType=0 and dividend NewsType=2 for relationship extraction)
   - **Fix counterparty extraction** to handle "giữa X và Y" patterns better (currently extracts "cùng kỳ" from "so với cùng kỳ")

## Test Script
Temporary test file created at `test_cafef_scraper.py` — AJAX-only fast test that skips Playwright. Run with:
```bash
uv run python test_cafef_scraper.py
```
