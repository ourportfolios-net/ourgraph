"""Shared helpers for the builder package — name classification, diacritics, formatting."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

# Company name keywords — if a shareholder name contains any of these it's a Company node.
# Otherwise it's classified as a Person.
_COMPANY_KEYWORDS: frozenset[str] = frozenset(
    {
        # English / International
        "jsc",
        "corp",
        "corporation",
        "ltd",
        "llc",
        "inc",
        "fund",
        "bank",
        "group",
        "ctcp",
        "tnhh",
        "company",
        "co.",
        "plc",
        "trust",
        "capital",
        "investment",
        "securities",
        "asset",
        "management",
        "holdings",
        "ventures",
        "partners",
        "enterprise",
        "technology",
        "insurance",
        "finance",
        "joint",
        "stock",
        "limited",
        "public",
        "viet",
        "vietnam",
        # Vietnamese corporate terms (diacritic-free for matching
        # against stripped names; multi-word phrases allowed)
        "quy",  # fund (Quỹ ETF, Quỹ Đầu tư)
        "chinh phu",  # government (Chính phủ)
        "dau tu",  # investment (Đầu tư)
        "cong ty",  # company (Công ty)
        "tap doan",  # conglomerate (Tập đoàn)
        "ngan hang",  # bank (Ngân hàng)
        "tong cong ty",  # state corporation (Tổng Công ty)
        "chung khoan",  # securities (Chứng khoán)
        "bao hiem",  # insurance (Bảo hiểm)
        "bat dong san",  # real estate (Bất động sản)
        "dau khi",  # oil & gas (Dầu khí)
        "xay dung",  # construction (Xây dựng)
        "thuong mai",  # trade/commerce (Thương mại)
        "dien luc",  # electricity (Điện lực)
        "vien thong",  # telecommunications (Viễn thông)
        "cong nghe",  # technology (Công nghệ)
        "hang khong",  # aviation (Hàng không)
        "nuoi trong",  # aquaculture (Nuôi trồng)
        "che bien",  # processing (Chế biến)
        "san xuat",  # manufacturing (Sản xuất)
        "kinh doanh",  # business (Kinh doanh)
        "phat trien",  # development (Phát triển)
    },
)

# Diacritic stripping table for ASCII-folding Vietnamese text.
# Shared between _is_company_name and _normalize_person_name.
_DIACRITICS_TABLE = str.maketrans(
    {
        "à": "a",
        "á": "a",
        "ạ": "a",
        "ả": "a",
        "ã": "a",
        "â": "a",
        "ầ": "a",
        "ấ": "a",
        "ậ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ă": "a",
        "ằ": "a",
        "ắ": "a",
        "ặ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "è": "e",
        "é": "e",
        "ẹ": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ê": "e",
        "ề": "e",
        "ế": "e",
        "ệ": "e",
        "ể": "e",
        "ễ": "e",
        "ì": "i",
        "í": "i",
        "ị": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ò": "o",
        "ó": "o",
        "ọ": "o",
        "ỏ": "o",
        "õ": "o",
        "ô": "o",
        "ồ": "o",
        "ố": "o",
        "ộ": "o",
        "ổ": "o",
        "ỗ": "o",
        "ơ": "o",
        "ờ": "o",
        "ớ": "o",
        "ợ": "o",
        "ở": "o",
        "ỡ": "o",
        "ù": "u",
        "ú": "u",
        "ụ": "u",
        "ủ": "u",
        "ũ": "u",
        "ư": "u",
        "ừ": "u",
        "ứ": "u",
        "ự": "u",
        "ử": "u",
        "ữ": "u",
        "ỳ": "y",
        "ý": "y",
        "ỵ": "y",
        "ỷ": "y",
        "ỹ": "y",
        "đ": "d",
        "À": "A",
        "Á": "A",
        "Ạ": "A",
        "Ả": "A",
        "Ã": "A",
        "Â": "A",
        "Ầ": "A",
        "Ấ": "A",
        "Ậ": "A",
        "Ẩ": "A",
        "Ẫ": "A",
        "Ă": "A",
        "Ằ": "A",
        "Ắ": "A",
        "Ặ": "A",
        "Ẳ": "A",
        "Ẵ": "A",
        "È": "E",
        "É": "E",
        "Ẹ": "E",
        "Ẻ": "E",
        "Ẽ": "E",
        "Ê": "E",
        "Ề": "E",
        "Ế": "E",
        "Ệ": "E",
        "Ể": "E",
        "Ễ": "E",
        "Ì": "I",
        "Í": "I",
        "Ị": "I",
        "Ỉ": "I",
        "Ĩ": "I",
        "Ò": "O",
        "Ó": "O",
        "Ọ": "O",
        "Ỏ": "O",
        "Õ": "O",
        "Ô": "O",
        "Ồ": "O",
        "Ố": "O",
        "Ộ": "O",
        "Ổ": "O",
        "Ỗ": "O",
        "Ơ": "O",
        "Ờ": "O",
        "Ớ": "O",
        "Ợ": "O",
        "Ở": "O",
        "Ỡ": "O",
        "Ù": "U",
        "Ú": "U",
        "Ụ": "U",
        "Ủ": "U",
        "Ũ": "U",
        "Ư": "U",
        "Ừ": "U",
        "Ứ": "U",
        "Ự": "U",
        "Ử": "U",
        "Ữ": "U",
        "Ỳ": "Y",
        "Ý": "Y",
        "Ỵ": "Y",
        "Ỷ": "Y",
        "Ỹ": "Y",
        "Đ": "D",
    },
)

MIN_TICKER_CODE_LEN = 3


def is_company_name(name: str) -> bool:
    """Heuristic: does this name look like a company rather than a person.

    Strips Vietnamese diacritics before matching, so 'Việt Nam' matches
    the keyword 'vietnam' and 'Ngân hàng' matches 'ngan hang'.

    Returns False for short names (≤4 words) that only match the 'viet'
    or 'vietnam' keywords — Vietnamese person names commonly contain
    'Việt' (e.g. Nguyễn Việt Quang).
    """
    stripped = name.translate(_DIACRITICS_TABLE).lower()
    words = stripped.split()

    matched = [kw for kw in _COMPANY_KEYWORDS if kw in stripped]
    if not matched:
        return False

    # If the ONLY matches are 'viet'/'vietnam' and the name is short,
    # it's likely a person, not a company.
    non_viet_matches = [kw for kw in matched if kw not in ("viet", "vietnam")]
    if not non_viet_matches and len(words) <= 4:
        return False

    return True


def normalize_person_name(name: str) -> str:
    """Normalize a person name by removing honorifics, diacritics, and lowercasing."""
    # Remove honorifics (Vietnamese)
    honorifics = re.compile(
        r"^(Ông\s+|Bà\s+|TS\.\s*|ThS\.\s*|KS\.\s*|GS\.\s*|PGS\.\s*)",
        re.IGNORECASE,
    )
    name = honorifics.sub("", name).strip()

    # Strip diacritics using shared table
    name = name.translate(_DIACRITICS_TABLE)

    # Lowercase and normalize whitespace
    return " ".join(name.lower().split())


def first_nonempty(row: dict, *keys: str) -> str:
    """Return the first non-empty value from row for the given keys."""
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def quarter_of(month: int) -> int:
    return (month - 1) // 3 + 1


def calc_return(closes: list[float], periods: int) -> float | None:
    """Calculate return over the last N trading days."""
    if len(closes) > periods and closes[-(periods + 1)] != 0:
        return (closes[-1] - closes[-(periods + 1)]) / closes[-(periods + 1)] * 100
    return None


def serialize_for_json(obj: dict) -> dict:
    return {
        k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
        for k, v in obj.items()
    }


def resolve_subsidiary_symbol(
    sub_name: str,
    sub_organ_code: str | None,
    name_to_symbol: dict[str, str] | None,
) -> str:
    """Resolve subsidiary name to real ticker symbol.

    Strategy:
    1. Use sub_organ_code if it looks like a valid ticker (2-10 chars, alphanumeric)
    2. Try to match sub_name against name_to_symbol mapping
    3. Try fuzzy match against known company names
    4. Fallback: generate from name (original behavior)
    """
    # Strategy 1: Use sub_organ_code if it looks like a ticker
    if (
        sub_organ_code
        and len(sub_organ_code) >= MIN_TICKER_CODE_LEN
        and sub_organ_code.isalnum()
    ):
        return sub_organ_code.upper()

    # Strategy 2: Match against name_to_symbol mapping
    if name_to_symbol:
        sub_lower = sub_name.lower()
        # Try exact match
        if sub_lower in name_to_symbol:
            return name_to_symbol[sub_lower]
        # Try contains match — but only for keys ≥4 chars to
        # avoid matching short tickers like "VIC" inside "GIAVICO".
        for name_key, sym in name_to_symbol.items():
            if len(name_key) < 4:
                continue
            if name_key in sub_lower or sub_lower in name_key:
                return sym
        # Try word-boundary match — but only for keys ≥4 chars.
        for name_key, sym in name_to_symbol.items():
            if len(name_key) < 4:
                continue
            if re.search(rf"\b{re.escape(name_key)}\b", sub_lower):
                return sym

    # Strategy 3: Fallback - deterministic hash for stability across re-runs
    name_hash = hashlib.sha256(sub_name.encode()).hexdigest()[:8].upper()
    return f"SUB_{name_hash}"


def resolve_holder_symbol(
    holder_name: str,
    name_to_symbol: dict[str, str] | None,
) -> str | None:
    """Resolve a corporate shareholder name to a known ticker symbol."""
    if not name_to_symbol:
        return None
    lookup = holder_name.lower()
    holder_symbol = name_to_symbol.get(lookup)
    if holder_symbol is None:
        for sym in name_to_symbol.values():
            if sym.lower() in lookup or lookup in sym.lower():
                return sym
    return holder_symbol
