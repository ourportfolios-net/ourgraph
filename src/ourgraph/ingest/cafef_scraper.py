"""CafeF corporate disclosure scraper.

Primary path: Playwright-rendered CBTT search page at
  https://cafef.vn/du-lieu/cong-bo-thong-tin.chn

Fallback: CafeF AJAX News API at:
  /du-lieu/Ajax/PageNew/News.ashx?Symbol=X&NewsType=N&PageIndex=P&PageSize=S

Note (2026-06): CafeF removed per-company CBTT pages and the CBTT search
is now fully JS-rendered. The old AJAX API only serves financial reports.
Playwright is used to render the search page and extract disclosures.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

import httpx
import polars as pl
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from collections.abc import Callable

try:
    from playwright.sync_api import Browser, Page, sync_playwright

    _HAVE_PLAYWRIGHT = True
except ImportError:
    _HAVE_PLAYWRIGHT = False

logger = logging.getLogger(__name__)

# Vietnamese keyword → relationship type mapping
KEYWORD_MAP: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"Giao\s*dịch\s*với\s*bên\s*liên\s*quan", re.IGNORECASE),
        "RELATED_PARTY_TRANSACTION",
    ),
    (re.compile(r"Bảo\s*lãnh", re.IGNORECASE), "GUARANTEES"),
    (re.compile(r"Cho\s*vay", re.IGNORECASE), "LENDS_TO"),
    (re.compile(r"Tín\s*dụng", re.IGNORECASE), "LENDS_TO"),
    (re.compile(r"Liên\s*doanh", re.IGNORECASE), "HAS_JOINT_VENTURE_WITH"),
    (re.compile(r"Liên\s*kết", re.IGNORECASE), "HAS_JOINT_VENTURE_WITH"),
    (re.compile(r"Phát\s*hành\s*trái\s*phiếu", re.IGNORECASE), "UNDERWRITTEN_BY"),
    (
        re.compile(r"Hợp\s*tác\s*kinh\s*doanh", re.IGNORECASE),
        "HAS_BUSINESS_COOPERATION",
    ),
    (re.compile(r"Hợp\s*đồng\s*ủy\s*thác", re.IGNORECASE), "HAS_BUSINESS_COOPERATION"),
]

BASE_URL = "https://cafef.vn"
NEWS_API = f"{BASE_URL}/du-lieu/Ajax/PageNew/News.ashx"
DEFAULT_TIMEOUT = 30.0
MAX_PAGES = 5
PAGE_SIZE = 30
MIN_CELL_LEN = 3
MAX_LINE_LEN = 200
MIN_LINE_LEN = 5

# Minimum length for extracted counterparty name to be considered valid
MIN_CP_NAME_LEN = 2
# Minimum length of source-symbol remainder to be kept as-is
MIN_REMAINDER_LEN = 4


def _match_type(title: str) -> str | None:
    """Check if a disclosure title matches any Vietnamese keyword."""
    for pattern, rel_type in KEYWORD_MAP:
        if pattern.search(title):
            return rel_type
    return None


def _parse_ms_date(date_str: str) -> str:
    """Parse /Date(milliseconds)/ into YYYY-MM-DD."""
    m = re.search(r"(\d+)", str(date_str))
    if not m:
        return ""
    ts = int(m.group(1)) / 1000.0
    try:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return ""


def _is_company_reference(text: str) -> bool:
    """Check if text contains Vietnamese company indicators."""
    lower = text.lower()
    return any(
        kw in lower for kw in ["ctcp", "công ty", "tnhh", "ngân hàng", "cổ phần"]
    )


class CafeFDisclosureScraper:
    """Scrapes CafeF corporate disclosure pages for a given symbol."""

    def __init__(self, delay: float = 1.0) -> None:
        self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self._delay = delay
        self._last_call: float = 0.0

    def _throttle(self) -> None:
        """Enforce minimum delay between requests."""
        if self._delay <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_call = time.monotonic()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_disclosures(self, symbol: str) -> pl.DataFrame:
        """Fetch disclosures for a symbol.

        Tries Playwright-rendered CBTT search first (primary path),
        falls back to the legacy AJAX API (which now only returns
        financial reports, not corporate disclosures).

        Returns a polars DataFrame with columns:
            title, date, url, rel_type, symbol
        """
        # Primary: Playwright CBTT search
        if _HAVE_PLAYWRIGHT:
            try:
                pw_rows = self._fetch_cbtt_playwright(symbol)
                if pw_rows:
                    logger.info(
                        "CafeF CBTT (Playwright): %d disclosures for %s",
                        len(pw_rows),
                        symbol,
                    )
                    return pl.DataFrame(pw_rows)
            except Exception:
                logger.debug(
                    "CafeF Playwright CBTT failed for %s", symbol, exc_info=True,
                )

        # Fallback: legacy AJAX API (limited — only financial reports)
        all_rows: list[dict] = []
        for news_type in range(4):
            page = 1
            while page <= MAX_PAGES:
                self._throttle()
                rows = self._fetch_news_page(symbol, news_type, page)
                if not rows:
                    break
                all_rows.extend(rows)
                page += 1
                if len(rows) < PAGE_SIZE:
                    break

        if not all_rows:
            return pl.DataFrame()
        return pl.DataFrame(all_rows)

    def _fetch_cbtt_playwright(self, symbol: str) -> list[dict]:
        """Scrape CBTT disclosures via Playwright-rendered search page.

        Navigates to https://cafef.vn/du-lieu/cong-bo-thong-tin.chn,
        searches for the symbol, waits for the table to render, and
        extracts disclosure rows.

        Uses dynamic element discovery — no hardcoded CSS selectors.
        The search input is found by enumerating all visible text input
        elements via JS eval. Table data is extracted via a generic JS
        eval that walks all <table> -> <tr> -> <td> / <a> elements.

        Returns list of dicts with keys: title, date, url, rel_type, symbol.
        Returns empty list on any failure (caller falls back to AJAX API).
        """
        rows: list[dict] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(
                    f"{BASE_URL}/du-lieu/cong-bo-thong-tin.chn",
                    wait_until="networkidle",
                    timeout=30000,
                )
                page.wait_for_timeout(3000)

                # Find search input dynamically: enumerate ALL input
                # elements via JS eval, pick first visible text input.
                input_found = page.evaluate(
                    """(sym) => {
                    const inputs = document.querySelectorAll('input');
                    for (const inp of inputs) {
                        const rect = inp.getBoundingClientRect();
                        const style = window.getComputedStyle(inp);
                        const isVisible = rect.width > 0 && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden';
                        if (!isVisible) continue;
                        const t = (inp.type || 'text').toLowerCase();
                        if (['hidden', 'submit', 'button', 'checkbox', 'radio',
                             'file', 'image', 'reset'].includes(t)) continue;
                        inp.value = sym;
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}));
                        inp.dispatchEvent(new KeyboardEvent('keypress', {key: 'Enter'}));
                        inp.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter'}));
                        const form = inp.closest('form');
                        if (form) {
                            form.dispatchEvent(new Event('submit', {bubbles: true}));
                        }
                        return true;
                    }
                    return false;
                }""",
                    symbol.upper(),
                )

                if not input_found:
                    logger.debug(
                        "CafeF Playwright: no visible text input found for %s",
                        symbol,
                    )
                    return []

                page.wait_for_timeout(4000)

                # Extract ALL links from ALL tables generically.
                # Single JS eval walks every table, every row, every link.
                all_links = page.evaluate("""() => {
                    const results = [];
                    const tables = document.querySelectorAll('table');
                    for (const table of tables) {
                        const rows = table.querySelectorAll('tr');
                        for (const tr of rows) {
                            const cells = tr.querySelectorAll('td');
                            const anchors = tr.querySelectorAll('a');
                            for (const a of anchors) {
                                const href = a.getAttribute('href') || '';
                                const text = a.textContent.trim();
                                if (!text || !href) continue;
                                if (text.length < 5) continue;
                                let url = href;
                                if (!href.startsWith('http')) {
                                    url = 'https://cafef.vn' + href;
                                }
                                let dateText = '';
                                if (cells.length >= 2) {
                                    dateText = cells[1].textContent.trim();
                                }
                                results.push({title: text, date: dateText, url});
                            }
                        }
                    }
                    return results;
                }""")

                for item in all_links:
                    title = item.get("title", "").strip()
                    if not title:
                        continue

                    rel_type = _match_type(title)
                    if not rel_type:
                        continue

                    rows.append(
                        {
                            "title": title,
                            "date": item.get("date", "").strip(),
                            "url": item.get("url", ""),
                            "rel_type": rel_type,
                            "symbol": symbol,
                        },
                    )

            finally:
                browser.close()

        return rows

    def _fetch_news_page(
        self,
        symbol: str,
        news_type: int,
        page: int,
    ) -> list[dict]:
        """Fetch a single page of news from the CafeF AJAX API."""
        try:
            resp = self._client.get(
                NEWS_API,
                params={
                    "Symbol": symbol,
                    "NewsType": news_type,
                    "PageIndex": page,
                    "PageSize": PAGE_SIZE,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug(
                "CafeF API failed for %s type=%d page=%d: %s",
                symbol,
                news_type,
                page,
                exc,
            )
            return []

        items = data.get("Data", [])
        if not items:
            return []

        rows: list[dict] = []
        for item in items:
            title = (item.get("Title") or "").strip()
            if not title:
                continue

            rel_type = _match_type(title)
            if not rel_type:
                continue

            link_detail = item.get("LinkDetail") or ""
            full_url = (
                link_detail
                if link_detail.startswith("http")
                else f"{BASE_URL}{link_detail}"
            )
            date_text = _parse_ms_date(item.get("DeployDate") or "")

            rows.append(
                {
                    "title": title,
                    "date": date_text,
                    "url": full_url,
                    "rel_type": rel_type,
                    "symbol": symbol,
                },
            )

        return rows

    def fetch_detail(self, url: str, rel_type: str) -> dict:  # noqa: ARG002
        """Scrape a single disclosure detail page for counterparty info."""
        self._throttle()
        result: dict = {
            "counterparty_name": None,
            "amount": None,
            "transaction_date": None,
            "description": None,
        }

        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            html = BeautifulSoup(resp.text, "html.parser")

            self._parse_detail_tables(html, result)

            # Fallback: full page text for counterparty extraction
            page_text = html.get_text(" ", strip=True)
            for line_raw in page_text.split("\n"):
                line = line_raw.strip()
                if (
                    _is_company_reference(line)
                    and MIN_LINE_LEN < len(line) < MAX_LINE_LEN
                    and result["counterparty_name"] is None
                ):
                    result["counterparty_name"] = line

            # Extract description from content div
            content_div = html.find(
                "div",
                class_=re.compile(r"content|detail|body", re.IGNORECASE),
            )
            if content_div:
                result["description"] = content_div.get_text(" ", strip=True)[:500]

        except httpx.HTTPError as exc:
            logger.debug("CafeF detail fetch failed for %s: %s", url, exc)

        return result

    def _parse_detail_tables(self, html: BeautifulSoup, result: dict) -> None:
        """Parse tables in a detail page for counterparty name and amount."""
        for table in html.find_all("table"):
            for td in table.find_all("td"):
                cell_text = td.get_text(strip=True)
                if len(cell_text) < MIN_CELL_LEN:
                    continue
                if (
                    _is_company_reference(cell_text)
                    and result["counterparty_name"] is None
                ):
                    result["counterparty_name"] = cell_text

                amount_match = re.search(
                    r"([\d,]+(?:\.\d{3})*(?:,\d{2})?\s*(?:tỷ|triệu|đồng|vnd|usd))",
                    cell_text,
                    re.IGNORECASE,
                )
                if amount_match and result["amount"] is None:
                    result["amount"] = amount_match.group(1)


_CP_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "giữa X và Y" → X (first entity) is a potential counterparty
    # Put this before the existing "between" pattern so X is tried first;
    # if X equals the source symbol, it falls through to "between" → Y.
    (
        re.compile(
            r"giữa\s+(\w[\w\s]{0,60}?\w)\s+và\s+\w[\w\s]{0,40}?\w"
            r"(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "between_x",
    ),
    # "giữa X và Y" → Y is the counterparty
    (
        re.compile(
            r"giữa\s+\w+\s+và\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "between",
    ),
    # "đối với Y" → Y is the counterparty
    (
        re.compile(
            r"đối với\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "doi_voi",
    ),
    # "cho Y vay" → Y is the counterparty
    (re.compile(r"cho\s+(\w[\w\s]{0,40}?)\s+vay", re.IGNORECASE), "cho_vay"),
    # "với Y" at end of title → Y is the counterparty
    (
        re.compile(
            r"với\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)", re.IGNORECASE,
        ),
        "voi",
    ),
    # "liên quan - X" or "liên quan – X" → X is the counterparty  # noqa: RUF003
    (
        re.compile(
            r"liên quan\s*[-–—]\s*([\w]{2,10})(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "dash_after_lienquan",
    ),
    # "X là công ty liên kết" → X is the counterparty (joint venture/affiliate)
    (
        re.compile(r"([\w][\w\s]{3,50}?)\s+là\s+công\s+ty\s+liên\s+kết", re.IGNORECASE),
        "la_cong_ty_lien_ket",
    ),
    # "hợp đồng với X" → X is the counterparty
    (
        re.compile(
            r"hợp\s+đồng\s+với\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "hop_dong_voi",
    ),
    # "ký kết với X" → X is the counterparty
    (
        re.compile(
            r"ký\s+kết\s+với\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "ky_ket_voi",
    ),
    # "hợp tác với X" → X is the counterparty
    (
        re.compile(
            r"hợp\s+tác\s+với\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "hop_tac_voi",
    ),
    # "ủy thác cho X" → X is the counterparty
    (
        re.compile(
            r"ủy\s+thác\s+cho\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "uy_thac_cho",
    ),
    # ", và X" at end of title after a comma → X is the counterparty
    (
        re.compile(
            r",\s+và\s+(\w[\w\s]{0,40}?)(?:\s*,|\s+theo|\s+nhằm|\s*\.|\s*$)",
            re.IGNORECASE,
        ),
        "va_at_end",
    ),
]

# Counterparty names that are NOT real company references (navigation text, boilerplate)
_SKIP_COUNTERPARTY = {
    "tài chính",
    "chứng khoán",
    "ngân hàng",
    "bất động sản",
    "doanh nghiệp",
    "vĩ mô",
    "quốc tế",
    "công ty",
    "bên liên quan",
    "bên có liên quan",
}


def _clean_cp_name(name: str, source_symbol: str) -> str | None:
    """Clean an extracted counterparty name.

    Strips Vietnamese disclosure prefixes, filters boilerplate,
    and removes bare source-symbol references.
    Returns the cleaned name or None if the name should be skipped.
    """
    # Strip common Vietnamese disclosure prefixes that are NOT
    # part of the company name (e.g. "CBTT " = Công bố thông tin).
    # Loop until no more prefixes match (handles "CTCP CTCP ..." duplication).
    cp_strip_prefixes = ("CBTT ", "CTCP ")
    while True:
        stripped = False
        for cp_prefix in cp_strip_prefixes:
            if len(name) > len(cp_prefix) and (
                name.upper().startswith(cp_prefix) or name.startswith(cp_prefix)
            ):
                name = name[len(cp_prefix) :].lstrip()
                stripped = True
                break
        if not stripped:
            break

    # Filter out boilerplate
    name_lower = name.lower()
    if (
        name_lower in _SKIP_COUNTERPARTY
        or name_lower.startswith(("bên liên quan", "bên có liên quan"))
        or len(name) < MIN_CP_NAME_LEN
    ):
        return None

    # Strip the source symbol only if the remainder is a
    # meaningful name (≥MIN_REMAINDER_LEN chars).  This keeps "VCB Lào" and
    # "VCBNeo" intact while removing bare "VCB" references.
    src = source_symbol.upper()
    if name.upper() == src:
        return None
    if name.upper().startswith(src + " "):
        remainder = name[len(src) :].strip()
        if len(remainder) >= MIN_REMAINDER_LEN:
            name = remainder
    if not name or name.upper() == src:
        return None

    return name


def _extract_counterparty(title: str, source_symbol: str) -> str | None:
    """Extract counterparty company name from a disclosure title."""
    for pattern, _ in _CP_PATTERNS:
        m = pattern.search(title)
        if m:
            name = m.group(1).strip().rstrip(".,;")
            cleaned = _clean_cp_name(name, source_symbol)
            if cleaned is not None:
                return cleaned
    return None


def _resolve_counterparty_symbol(
    name: str | None,
    name_resolver: Callable[[str], str | None] | None,
    source_symbol: str,
) -> str | None:
    """Resolve a counterparty name to a known company symbol.

    Does NOT resolve to the source symbol — a company cannot
    lend to or underwrite itself.  If the resolver returns the
    source symbol, treat the counterparty as a separate entity.
    """
    if not name or not name_resolver:
        return None
    resolved = name_resolver(name)
    if resolved and resolved.upper() == source_symbol.upper():
        # The counterparty name contains the source ticker but is
        # a different entity (e.g. "VCB Lào" ≠ "VCB").
        return None
    return resolved


def _extract_amount_from_title(title: str) -> str | None:
    """Extract monetary amount from a disclosure title."""
    m = re.search(
        r"([\d,.]+)\s*(?:tỷ|triệu|đồng|vnđ|usd)",
        title,
        re.IGNORECASE,
    )
    return m.group(0) if m else None


def scrape_disclosures(
    symbol: str,
    name_resolver: Callable[[str], str | None] | None = None,
    delay: float = 1.0,
) -> pl.DataFrame:
    """Scrape CafeF disclosures for a single symbol.

    Returns a polars DataFrame with resolved relationship data:
        source_symbol, target_symbol, target_name, rel_type, amount,
        transaction_date, description

    Counterparty names are extracted from disclosure titles
    (detail page scraping is unreliable — the pages are JS-rendered
    and the counterparty data is not in parseable HTML).

    Args:
        symbol: Ticker symbol to scrape
        name_resolver: Optional callable to resolve company names to symbols
        delay: Rate limit delay between requests (seconds)

    """
    scraper = CafeFDisclosureScraper(delay=delay)
    try:
        df_list = scraper.fetch_disclosures(symbol)
        if df_list.is_empty():
            logger.info("No CafeF disclosures found for %s", symbol)
            return pl.DataFrame()

        logger.info(
            "Found %d matching CafeF disclosures for %s",
            len(df_list),
            symbol,
        )

        detail_rows: list[dict] = []
        for row in df_list.to_dicts():
            title = row.get("title", "")
            counterparty_name = _extract_counterparty(title, symbol)
            counterparty_symbol = _resolve_counterparty_symbol(
                counterparty_name,
                name_resolver,
                symbol,
            )
            amount = row.get("amount") or _extract_amount_from_title(title) or ""

            detail_rows.append(
                {
                    "source_symbol": symbol,
                    "target_symbol": counterparty_symbol
                    or (counterparty_name.upper() if counterparty_name else ""),
                    "target_name": counterparty_name or "",
                    "rel_type": row["rel_type"],
                    "amount": str(amount) if amount else "",
                    "transaction_date": row.get("date", ""),
                    "description": title,
                },
            )

        return pl.DataFrame(detail_rows)
    finally:
        scraper.close()


def batch_scrape(
    symbols: list[str],
    name_resolver: Callable[[str], str | None] | None = None,
    delay: float = 1.0,
    max_symbols: int = 20,
) -> pl.DataFrame:
    """Scrape CafeF disclosures for multiple symbols, rate-limited.

    Args:
        symbols: List of ticker symbols
        name_resolver: Optional callable to resolve company names to symbols
        delay: Rate limit delay between requests
        max_symbols: Max number of symbols to process (to avoid long runs)

    Returns:
        Combined polars DataFrame of all scraped relationships

    """
    all_rows: list[pl.DataFrame] = []
    for i, sym in enumerate(symbols[:max_symbols]):
        logger.info(
            "CafeF scraping %s (%d/%d)", sym, i + 1, min(len(symbols), max_symbols),
        )
        try:
            df = scrape_disclosures(sym, name_resolver=name_resolver, delay=delay)
            if not df.is_empty():
                all_rows.append(df)
        except Exception:
            logger.exception("CafeF scrape failed for %s", sym)

    if not all_rows:
        return pl.DataFrame()
    return pl.concat(all_rows, how="vertical")
