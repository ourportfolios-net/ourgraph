"""HNX Bond Market scraper.

Scrapes https://cbonds.hnx.vn/to-chuc-phat-hanh/thong-tin-phat-hanh
for corporate bond issuance data via Playwright (JS-rendered, self-signed cert).

Extracts:
- Issuer company name, bond code, interest rate, maturity date, issue date, amount
- Note: underwriter data is not available in the cbonds table

Rate limit: 1 req/s. Daily snapshot is enough.

Column mapping is header-based — no hardcoded indices.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

BOND_URL = "https://cbonds.hnx.vn/to-chuc-phat-hanh/thong-tin-phat-hanh"
MAX_ROWS = 500


def _parse_date_vi(date_str: str) -> str:
    """Parse a Vietnamese date string (dd/mm/yyyy) to YYYY-MM-DD."""
    for pattern in [
        r"(\d{2})/(\d{2})/(\d{4})",
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
    ]:
        m = re.search(pattern, str(date_str))
        if m:
            return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return str(date_str).strip()


def _parse_rate(rate_str: str) -> float | None:
    """Parse a percentage rate string like '12.5' or '8,5'."""
    if not rate_str:
        return None
    try:
        return float(str(rate_str).replace(",", ".").strip())
    except ValueError:
        return None


def _parse_volume_amount(volume_str: str, face_value_str: str) -> float | None:
    """Calculate total issuance value = volume * face_value."""
    try:
        volume = float(str(volume_str).replace(",", "").strip())
        face = float(str(face_value_str).replace(",", "").strip())
        return volume * face
    except (ValueError, TypeError):
        # Try parsing volume alone
        try:
            return float(str(volume_str).replace(",", "").strip())
        except (ValueError, TypeError):
            return None


def _build_column_map(headers: list[str]) -> dict[str, int] | None:
    """Build a column-index map from header cell text (case-insensitive keyword matching).

    Returns a dict like {"stt": 0, "issuer_name": 2, ...} mapping logical
    field names to their column positions, or None if essential columns
    (stt, issue_date, maturity_date, bond_code) cannot be identified.
    """
    if not headers:
        return None

    col_map: dict[str, int] = {}

    for i, raw in enumerate(headers):
        h = raw.strip().lower()

        # --- STT (sequence number) ---
        if any(kw in h for kw in ["stt", "số tt", "stt ", " stt"]):
            col_map["stt"] = i

        # --- Issuer name ---
        if any(
            kw in h
            for kw in [
                "tổ chức phát hành",
                "tên tổ chức",
                "tổ chức",
                "ty phát hành",
                "tên dn",
                "tên doanh nghiệp",
            ]
        ):
            col_map["issuer_name"] = i

        # --- Bond code ---
        if any(
            kw in h
            for kw in [
                "mã trái phiếu",
                "mã tp",
                "mã trái",
                "ma trai phieu",
                "trai phieu",
            ]
        ):
            col_map["bond_code"] = i

        # --- Currency ---
        if any(kw in h for kw in ["loại tiền", "tiền tệ", "loai tien"]):
            col_map["currency"] = i

        # --- Term / kỳ hạn ---
        if any(kw in h for kw in ["kỳ hạn", "ky han", "thời hạn", "thoi han"]):
            col_map["term"] = i

        # --- Issue date (match before generic "ngày") ---
        if any(kw in h for kw in ["ngày phát hành", "ngay phat hanh", "ngày phát"]):
            col_map["issue_date"] = i

        # --- Maturity date ---
        if any(
            kw in h for kw in ["ngày đáo hạn", "ngay dao han", "ngày đáo", "ngay dao"]
        ):
            col_map["maturity_date"] = i

        # --- Remaining days ---
        if any(
            kw in h for kw in ["số ngày còn lại", "so ngay con lai", "ngày còn lại"]
        ):
            col_map["remaining_days"] = i

        # --- Volume (khối lượng) ---
        if any(kw in h for kw in ["khối lượng", "khoi luong", "khối lượng phát"]):
            col_map["volume"] = i

        # --- Face value (mệnh giá) — prefer first match to avoid
        # overwriting by "giá trị phát hành (theo mệnh giá)" which
        # also contains "mệnh giá" as a substring.
        if "face_value" not in col_map and any(
            kw in h for kw in ["mệnh giá", "menh gia", "mệnh giá phát"]
        ):
            col_map["face_value"] = i

        # --- Total issuance value (giá trị phát hành) — separate field
        # from per-bond face value.
        if any(
            kw in h for kw in ["giá trị phát hành", "gia tri phat hanh", "tổng giá trị"]
        ):
            col_map["total_value"] = i

        # --- Interest type / method (loại hình trả lãi) ---
        if any(
            kw in h
            for kw in ["loại hình trả lãi", "loai hinh tra lai", "hình thức trả lãi"]
        ):
            col_map["interest_type"] = i

        # --- Rate type (loại lãi suất: cố định/thả nổi) ---
        if any(kw in h for kw in ["loại lãi suất", "loai lai suat", "loại lãi"]):
            col_map["rate_type"] = i

        # --- Payment method (phương thức thanh toán) ---
        if any(
            kw in h
            for kw in [
                "phương thức thanh toán",
                "phuong thuc thanh toan",
                "thanh toán lãi",
            ]
        ):
            col_map["payment_method"] = i

        # --- Buyback (mua lại) ---
        if any(kw in h for kw in ["mua lại", "mua lai"]):
            col_map["buyback"] = i

        # --- Issue rate (lãi suất phát hành) — match before generic "lãi suất" ---
        if any(
            kw in h
            for kw in ["lãi suất phát hành", "lai suat phat hanh", "ls phát hành"]
        ):
            col_map["issue_rate"] = i

        # --- Generic interest rate fallback ---
        if any(kw in h for kw in ["lãi suất", "lai suat", "lãi suất %"]):
            if "issue_rate" not in col_map:
                col_map["rate"] = i

        # --- Status ---
        if any(
            kw in h for kw in ["trạng thái", "trang thai", "tình trạng", "tinh trang"]
        ):
            col_map["status"] = i

        # --- Publish date ---
        if any(
            kw in h
            for kw in [
                "ngày công bố",
                "ngay cong bo",
                "ngày đăng",
                "ngay dang",
                "ngày công",
                "ngày đăng tin",
            ]
        ):
            col_map["publish_date"] = i

        # --- Attachments (tệp đính kèm) ---
        if any(
            kw in h
            for kw in ["tệp đính kèm", "tep dinh kem", "đính kèm", "file đính kèm"]
        ):
            col_map["attachments"] = i

    # Verify essential columns exist
    essential = ["stt", "issue_date", "maturity_date", "bond_code"]
    if not all(k in col_map for k in essential):
        logger.debug(
            "Missing essential columns in header map: %s (headers=%s)",
            [k for k in essential if k not in col_map],
            headers,
        )
        return None

    return col_map


def _cell_safe(cells: list[str], col_map: dict[str, int], field: str) -> str:
    """Safely access a cell value by field name using the column map."""
    idx = col_map.get(field)
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx].strip()


def _is_data_row(cells: list[str], col_map: dict[str, int]) -> bool:
    """Check if a row is a valid data row from the bond issuance table.

    Uses the header-derived column map (not hardcoded indices).
    """
    if not cells or not col_map:
        return False

    # STT must be a plain integer
    stt = _cell_safe(cells, col_map, "stt")
    if not re.match(r"^\d+$", stt):
        return False

    # Issue date and maturity date must be parseable dates
    issue = _parse_date_vi(_cell_safe(cells, col_map, "issue_date"))
    maturity = _parse_date_vi(_cell_safe(cells, col_map, "maturity_date"))
    if not issue or not maturity:
        return False

    # Both must match a real date pattern (YYYY-MM-DD after parsing)
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not date_pattern.match(issue) or not date_pattern.match(maturity):
        return False

    # Must have a bond code that looks like a proper code
    bond = _cell_safe(cells, col_map, "bond_code")
    if not bond or bond.startswith("CERTIFICATE") or len(bond) < 4:
        return False

    return True


def scrape_bonds(
    name_resolver: Callable[[str], str | None] | None = None,
    delay: float = 1.0,
) -> pl.DataFrame:
    """Scrape HNX bond issuance data from cbonds.hnx.vn.

    Returns a polars DataFrame with bond records:
        issuer_name, issuer_symbol, bond_code, interest_rate,
        maturity_date, issue_date, issue_amount, currency, status

    Note: underwriter data is not available on cbonds.hnx.vn —
    the table only lists issuing organizations.

    Column mapping is header-based — if the HNX site changes its
    column layout, the scraper adapts by matching header keywords.

    Args:
        name_resolver: Optional callable to resolve company names to symbols
        delay: Rate limit delay between requests (seconds)

    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "Playwright not installed. Install with: uv pip install playwright && playwright install chromium",
        )
        return pl.DataFrame()

    rows: list[dict] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()

            logger.info("Navigating to %s", BOND_URL)
            page.goto(BOND_URL, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(5000)

            # Extract ALL tables with their headers and data rows.
            # Returns a list of {headers: [...str...], rows: [[...str...], ...]}
            tables = page.evaluate("""() => {
                const result = [];
                const tables = document.querySelectorAll('table');
                for (const table of tables) {
                    // Extract headers from thead th, or first row's td if no thead
                    const thead = table.querySelector('thead');
                    let headers = [];
                    if (thead) {
                        const headerRow = thead.querySelector('tr');
                        if (headerRow) {
                            headers = Array.from(headerRow.querySelectorAll('th, td'))
                                .map(cell => cell.textContent.trim());
                        }
                    }
                    // If no thead, try the first tr and check if it looks like a header
                    // (all cells are th or text looks like column names)
                    if (headers.length === 0) {
                        const firstRow = table.querySelector('tr');
                        if (firstRow) {
                            const firstCells = firstRow.querySelectorAll('th, td');
                            const texts = Array.from(firstCells)
                                .map(cell => cell.textContent.trim());
                            // Heuristic: if any cell contains a keyword like "stt"
                            // or "mã", treat as header row
                            const headerKeywords = ['stt', 'mã', 'ngày', 'tổ chức', 'lãi'];
                            if (texts.some(t => headerKeywords.some(k => t.toLowerCase().includes(k)))) {
                                headers = texts;
                            }
                        }
                    }
                    if (headers.length === 0) continue;

                    // Extract data rows (skip header row if it was the first tr)
                    const body = table.querySelector('tbody') || table;
                    const rowElements = body.querySelectorAll('tr');
                    const rows_data = [];
                    for (const tr of rowElements) {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(cell => cell.textContent.trim());
                        if (cells.length > 0) {
                            rows_data.push(cells);
                        }
                    }

                    result.push({ headers: headers, rows: rows_data });
                }
                return result;
            }""")

            browser.close()

            # Process each table
            seen_bonds: set[str] = set()
            for table_data in tables:
                col_map = _build_column_map(table_data["headers"])
                if col_map is None:
                    logger.debug(
                        "Skipping table — could not build column map from headers: %s",
                        table_data["headers"],
                    )
                    continue

                for cells in table_data["rows"]:
                    if not _is_data_row(cells, col_map):
                        continue

                    issuer_name = _cell_safe(cells, col_map, "issuer_name")
                    bond_code = _cell_safe(cells, col_map, "bond_code")
                    issue_date = _parse_date_vi(
                        _cell_safe(cells, col_map, "issue_date"),
                    )
                    maturity_date = _parse_date_vi(
                        _cell_safe(cells, col_map, "maturity_date"),
                    )
                    publish_date = _parse_date_vi(
                        _cell_safe(cells, col_map, "publish_date"),
                    )

                    # Issue rate: try specific 'issue_rate' first, fall back to generic 'rate'
                    rate_str = _cell_safe(cells, col_map, "issue_rate") or _cell_safe(
                        cells, col_map, "rate",
                    )
                    volume_str = _cell_safe(cells, col_map, "volume")
                    face_value_str = _cell_safe(cells, col_map, "face_value")
                    currency = _cell_safe(cells, col_map, "currency")
                    status = _cell_safe(cells, col_map, "status")

                    if not issuer_name:
                        continue

                    # Deduplicate by bond code (some bonds appear in multiple sub-tables)
                    dedup_key = f"{bond_code}_{issue_date}"
                    if dedup_key in seen_bonds:
                        continue
                    seen_bonds.add(dedup_key)

                    interest_rate = _parse_rate(rate_str)
                    issue_amount = _parse_volume_amount(volume_str, face_value_str)
                    # Fall back to direct total_value if volume*face_value failed
                    if issue_amount is None:
                        total_str = _cell_safe(cells, col_map, "total_value")
                        if total_str:
                            try:
                                issue_amount = float(total_str.replace(",", "").strip())
                            except ValueError:
                                issue_amount = None

                    # Resolve issuer name to symbol.
                    # First try extracting ticker from "TICKER - Name" prefix.
                    issuer_symbol = None
                    issuer_name_clean = issuer_name
                    ticker_match = re.match(r"^([A-Z]{2,5})\s*[-–—]", issuer_name)
                    if ticker_match:
                        candidate_ticker = ticker_match.group(1)
                        # Remove ticker prefix from name for cleaner display
                        issuer_name_clean = issuer_name[ticker_match.end() :].strip()
                        issuer_symbol = candidate_ticker
                    # Fall back to name_resolver if ticker extraction didn't work.
                    if not issuer_symbol and name_resolver and issuer_name:
                        issuer_symbol = name_resolver(issuer_name)
                    if not issuer_symbol and name_resolver and issuer_name_clean:
                        issuer_symbol = name_resolver(issuer_name_clean)

                    rows.append(
                        {
                            "issuer_name": issuer_name,
                            "issuer_symbol": issuer_symbol or "",
                            "bond_code": bond_code,
                            "interest_rate": interest_rate,
                            "maturity_date": maturity_date,
                            "issue_date": issue_date,
                            "publish_date": publish_date,
                            "issue_amount": issue_amount,
                            "currency": currency,
                            "status": status,
                            "source": "cbonds.hnx.vn",
                        },
                    )

                    if len(rows) >= MAX_ROWS:
                        break

    except Exception:
        logger.exception("HNX cbonds scrape failed")
        return pl.DataFrame()

    logger.info("Extracted %d bond records from HNX cbonds", len(rows))
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows)
