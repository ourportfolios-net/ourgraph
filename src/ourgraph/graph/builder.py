"""Core knowledge graph builder — aligned with the paper's schema.

Node hierarchy:
  Company → HAS_INDICATOR   → Indicator  → MEASURED_ON → Quarter
  Company → HAS_FINANCIAL_STATEMENTS → FinancialStatement → FOR_QUARTER → Quarter
                                                           → FOR_YEAR   → Year
  Company → BELONGS_TO → Sector
  Company → BELONGS_TO_INDUSTRY → Industry
  Company → COMPETES_WITH → Company
  Company → SUBSIDIARY_OF → Company
  (Company|Person) → HOLDS_STAKE_IN → Company
  Person → IS_OFFICER → Company
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    import polars as pl

from ourgraph.graph.relationship_manager import RelationshipManager
from ourgraph.graph.schema import NodeLabel, Prop, RelType

if TYPE_CHECKING:
    from falkordb.asyncio import FalkorDB

    from ourgraph.config import FalkorDBSettings

logger = logging.getLogger(__name__)

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


def _is_company_name(name: str) -> bool:
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


def _normalize_person_name(name: str) -> str:
    """Normalize a person name by removing honorifics, diacritics, and lowercasing."""
    import re

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


def _first_nonempty(row: dict, *keys: str) -> str:
    """Return the first non-empty value from row for the given keys."""
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _quarter_of(month: int) -> int:
    return (month - 1) // 3 + 1


def _calc_return(closes: list[float], periods: int) -> float | None:
    """Calculate return over the last N trading days."""
    if len(closes) > periods and closes[-(periods + 1)] != 0:
        return (closes[-1] - closes[-(periods + 1)]) / closes[-(periods + 1)] * 100
    return None


def _serialize_for_json(obj: dict) -> dict:
    return {
        k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
        for k, v in obj.items()
    }


class GraphBuilder:
    """Async graph builder backed by FalkorDB."""

    def __init__(self, client: FalkorDB, graph_name: str) -> None:
        self._client = client
        self._graph_name = graph_name
        self._rel_manager = RelationshipManager(self)

    @classmethod
    def from_settings(cls, settings: FalkorDBSettings) -> GraphBuilder:
        from ourgraph.db.falkordb import build_falkordb_client

        return cls(
            client=build_falkordb_client(settings),
            graph_name=settings.graph_name,
        )

    async def _graph(self) -> object:
        return self._client.select_graph(self._graph_name)  # type: ignore[return-value]

    async def _run(self, query: str, params: dict | None = None) -> list:
        g = await self._graph()
        query_method = getattr(g, "query")  # noqa: B009
        result = await query_method(query, params or {})
        return result.result_set

    async def query_raw(self, query: str, params: dict | None = None) -> list:
        """Public wrapper for running raw Cypher queries."""
        return await self._run(query, params)

    # ------------------------------------------------------------------
    # Index setup
    # ------------------------------------------------------------------

    async def ensure_indices(self) -> None:
        indices = [
            f"CREATE INDEX ON :{NodeLabel.COMPANY}({Prop.SYMBOL})",
            f"CREATE INDEX ON :{NodeLabel.COMPANY}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.PERSON}({Prop.PERSON_NAME})",
            f"CREATE INDEX ON :{NodeLabel.SECTOR}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.INDUSTRY}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.FINANCIAL_STATEMENT}({Prop.SYMBOL}, {Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.INDICATOR}({Prop.SYMBOL}, {Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.DATE}({Prop.DATE})",
            f"CREATE INDEX ON :{NodeLabel.QUARTER}({Prop.YEAR}, {Prop.QUARTER})",
            f"CREATE INDEX ON :{NodeLabel.YEAR}({Prop.YEAR})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.NAME})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.DATE})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.COUNTRY})",
            f"CREATE INDEX ON :{NodeLabel.MACRO_INDICATOR}({Prop.CATEGORY})",
            f"CREATE INDEX ON :{NodeLabel.COUNTRY}({Prop.CODE})",
            f"CREATE INDEX ON :{NodeLabel.COUNTRY}({Prop.NAME})",
        ]
        for idx in indices:
            try:
                await self._run(idx)
            except Exception as exc:
                exc_str = str(exc).lower()
                if "already exists" not in exc_str and "already indexed" not in exc_str:
                    logger.warning("Index warning: %s — %s", idx, exc)

    # ------------------------------------------------------------------
    # Company nodes
    # ------------------------------------------------------------------

    async def upsert_companies(self, df: pl.DataFrame) -> None:
        for row in df.to_dicts():
            params = {
                "symbol": row.get(Prop.SYMBOL, ""),
                "name": _first_nonempty(
                    row, "short_name", "company_name", "name", Prop.SYMBOL,
                )
                or row.get(Prop.SYMBOL, ""),
                "exchange": row.get(Prop.EXCHANGE) or "",
                "market_cap": row.get(Prop.MARKET_CAP) or 0,
                "no_employees": row.get(Prop.NO_EMPLOYEES) or 0,
                "established_year": str(row.get(Prop.ESTABLISHED_YEAR) or ""),
                "website": row.get(Prop.WEBSITE) or "",
                "outstanding_share": float(row.get(Prop.OUTSTANDING_SHARE) or 0),
                "foreign_percent": float(row.get(Prop.FOREIGN_PERCENT) or 0),
            }
            await self._run(
                f"""
                MERGE (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                SET c.{Prop.NAME}             = $name,
                    c.{Prop.EXCHANGE}         = $exchange,
                    c.{Prop.MARKET_CAP}       = $market_cap,
                    c.{Prop.NO_EMPLOYEES}     = $no_employees,
                    c.{Prop.ESTABLISHED_YEAR} = $established_year,
                    c.{Prop.WEBSITE}          = $website,
                    c.{Prop.OUTSTANDING_SHARE}= $outstanding_share,
                    c.{Prop.FOREIGN_PERCENT}  = $foreign_percent,
                    c.company_type            = 'listed'
                """,
                params,
            )

    # ------------------------------------------------------------------
    # Sector / Industry + COMPETES_WITH
    # ------------------------------------------------------------------

    async def upsert_sector_industry(self, df: pl.DataFrame) -> None:
        for row in df.to_dicts():
            symbol = row.get(Prop.SYMBOL, "")
            industry = _first_nonempty(
                row, "industry", "industryName", "industry_name", "sector", "nganh",
            )
            if not industry:
                logger.debug(
                    "No industry for %s — columns: %s", symbol, list(row.keys()),
                )
                continue
            await self._run(
                f"""
                MERGE (ind:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry}})
                WITH ind
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (c)-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind)
                """,
                {"symbol": symbol, "industry": industry},
            )

        for row in df.to_dicts():
            symbol = row.get(Prop.SYMBOL, "")
            industry = _first_nonempty(
                row, "industry", "industryName", "industry_name", "sector", "nganh",
            )
            if not industry:
                continue
            sector = _first_nonempty(row, "sector", "sectorName", "sector_name") or (
                industry.split(" - ")[0] if " - " in industry else industry
            )
            await self._run(
                f"""
                MERGE (s:{NodeLabel.SECTOR} {{{Prop.NAME}: $sector}})
                WITH s
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (c)-[:{RelType.BELONGS_TO}]->(s)
                """,
                {"symbol": symbol, "sector": sector},
            )

    async def upsert_competes_with(self) -> None:
        """Create single COMPETES_WITH edge per pair (symmetric relationship)."""
        # First, delete all existing COMPETES_WITH edges to avoid duplicates
        await self._run(f"MATCH ()-[r:{RelType.COMPETES_WITH}]->() DELETE r")
        # Create single edge per pair (a->b where a.symbol < b.symbol)
        await self._run(
            f"""
            MATCH (a:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
                  <-[:{RelType.BELONGS_TO_INDUSTRY}]-(b:{NodeLabel.COMPANY})
            WHERE a.{Prop.SYMBOL} < b.{Prop.SYMBOL}
            MERGE (a)-[:{RelType.COMPETES_WITH}]->(b)
            """,
        )

    # ------------------------------------------------------------------
    # Stock price nodes
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    async def upsert_financial_statement(
        self,
        df: pl.DataFrame,
        symbol: str,
        statement_type: str,
        period: str,
    ) -> None:
        """Upsert financial statement nodes using batch UNWIND."""
        if df is None or df.is_empty():
            return

        is_quarter = period == "quarter"
        rows: list[dict] = []
        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0))
            quarter = int(row.get(Prop.QUARTER, 0)) if is_quarter else 0

            payload_dict = {
                k: v
                for k, v in row.items()
                if k not in (Prop.YEAR, Prop.QUARTER, Prop.SYMBOL) and v is not None
            }

            rows.append(
                {
                    "symbol": symbol,
                    "statement_type": statement_type,
                    "period": period,
                    "year": year,
                    "quarter": quarter,
                    "payload": json.dumps(
                        _serialize_for_json(payload_dict), ensure_ascii=False,
                    ),
                },
            )

        if not rows:
            return

        if is_quarter and rows[0]["quarter"] > 0:
            await self._run(
                f"""
                UNWIND $rows AS r
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: r.symbol}})
                MERGE (fs:{NodeLabel.FINANCIAL_STATEMENT} {{
                    {Prop.SYMBOL}: r.symbol,
                    {Prop.STATEMENT_TYPE}: r.statement_type,
                    {Prop.PERIOD}: r.period,
                    {Prop.YEAR}: r.year,
                    {Prop.QUARTER}: r.quarter
                }})
                SET fs.{Prop.PAYLOAD} = r.payload
                MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs)
                MERGE (q:{NodeLabel.QUARTER} {{{Prop.YEAR}: r.year, {Prop.QUARTER}: r.quarter}})
                MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: r.year}})
                MERGE (q)-[:{RelType.IN_YEAR}]->(y)
                MERGE (fs)-[:{RelType.FOR_QUARTER}]->(q)
                MERGE (fs)-[:{RelType.FOR_YEAR}]->(y)
                """,
                {"rows": rows},
            )
        else:
            await self._run(
                f"""
                UNWIND $rows AS r
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: r.symbol}})
                MERGE (fs:{NodeLabel.FINANCIAL_STATEMENT} {{
                    {Prop.SYMBOL}: r.symbol,
                    {Prop.STATEMENT_TYPE}: r.statement_type,
                    {Prop.PERIOD}: r.period,
                    {Prop.YEAR}: r.year,
                    {Prop.QUARTER}: r.quarter
                }})
                SET fs.{Prop.PAYLOAD} = r.payload
                MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(fs)
                MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: r.year}})
                MERGE (fs)-[:{RelType.FOR_YEAR}]->(y)
                """,
                {"rows": rows},
            )

    # ------------------------------------------------------------------
    # Financial indicators
    # ------------------------------------------------------------------

    async def upsert_financial_indicators(self, df: pl.DataFrame, symbol: str) -> None:
        """Upsert financial indicator nodes using batch UNWIND."""
        if df is None or df.is_empty():
            return

        # Map normalized column names → Prop constants
        metric_map: dict[str, str] = {
            "pb": Prop.PBR,
            "pbr": Prop.PBR,
            "pe": Prop.PER,
            "per": Prop.PER,
            "eps": Prop.EPS,
            "roe": Prop.ROE,
            "roa": Prop.ROA,
            "debt_to_equity": Prop.DEBT_TO_EQUITY,
            "current_ratio": Prop.CURRENT_RATIO,
            "quick_ratio": Prop.QUICK_RATIO,
            "gross_margin": Prop.GROSS_MARGIN,
            "net_margin": Prop.NET_MARGIN,
            "revenue_growth": Prop.REVENUE_GROWTH,
            "dividend_yield": Prop.DIVIDEND_YIELD,
        }

        # Known indicator columns (exclude from payload)
        indicator_cols = set(metric_map.keys()) | {
            Prop.YEAR,
            Prop.QUARTER,
            Prop.SYMBOL,
            "year",
            "quarter",
            "symbol",
        }

        rows: list[dict] = []
        for row in df.to_dicts():
            year = int(row.get(Prop.YEAR, 0) or row.get("year", 0))
            quarter = int(row.get(Prop.QUARTER, 0) or row.get("quarter", 0))

            # Extract each known metric
            metrics: dict[str, float | None] = {}
            for col_key, prop_name in metric_map.items():
                val = row.get(col_key)
                if val is not None:
                    try:
                        metrics[prop_name] = float(val)
                    except (ValueError, TypeError):
                        metrics[prop_name] = None

            # Everything else goes into payload
            payload_dict = {
                k: (v.isoformat() if isinstance(v, date) else v)
                for k, v in row.items()
                if k not in indicator_cols and v is not None
            }

            rows.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "quarter": quarter,
                    "pbr": metrics.get(Prop.PBR),
                    "per": metrics.get(Prop.PER),
                    "eps": metrics.get(Prop.EPS),
                    "roe": metrics.get(Prop.ROE),
                    "roa": metrics.get(Prop.ROA),
                    "debt_to_equity": metrics.get(Prop.DEBT_TO_EQUITY),
                    "current_ratio": metrics.get(Prop.CURRENT_RATIO),
                    "quick_ratio": metrics.get(Prop.QUICK_RATIO),
                    "gross_margin": metrics.get(Prop.GROSS_MARGIN),
                    "net_margin": metrics.get(Prop.NET_MARGIN),
                    "revenue_growth": metrics.get(Prop.REVENUE_GROWTH),
                    "dividend_yield": metrics.get(Prop.DIVIDEND_YIELD),
                    "payload": json.dumps(
                        _serialize_for_json(payload_dict), ensure_ascii=False,
                    )
                    if payload_dict
                    else "",
                },
            )

        if not rows:
            return

        await self._run(
            f"""
            UNWIND $rows AS r
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: r.symbol}})
            MERGE (i:{NodeLabel.INDICATOR} {{
                {Prop.SYMBOL}: r.symbol,
                {Prop.YEAR}: r.year,
                {Prop.QUARTER}: r.quarter
            }})
            SET i.{Prop.PBR}              = r.pbr,
                i.{Prop.PER}              = r.per,
                i.{Prop.EPS}              = r.eps,
                i.{Prop.ROE}              = r.roe,
                i.{Prop.ROA}              = r.roa,
                i.{Prop.DEBT_TO_EQUITY}   = r.debt_to_equity,
                i.{Prop.CURRENT_RATIO}    = r.current_ratio,
                i.{Prop.QUICK_RATIO}      = r.quick_ratio,
                i.{Prop.GROSS_MARGIN}     = r.gross_margin,
                i.{Prop.NET_MARGIN}       = r.net_margin,
                i.{Prop.REVENUE_GROWTH}   = r.revenue_growth,
                i.{Prop.DIVIDEND_YIELD}   = r.dividend_yield,
                i.{Prop.PAYLOAD}          = r.payload
            MERGE (c)-[:{RelType.HAS_INDICATOR}]->(i)
            MERGE (q:{NodeLabel.QUARTER} {{{Prop.YEAR}: r.year, {Prop.QUARTER}: r.quarter}})
            MERGE (y:{NodeLabel.YEAR} {{{Prop.YEAR}: r.year}})
            MERGE (q)-[:{RelType.IN_YEAR}]->(y)
            MERGE (i)-[:{RelType.MEASURED_ON}]->(q)
            """,
            {"rows": rows},
        )

    # ------------------------------------------------------------------
    # Officers → Person nodes with IS_OFFICER relationship
    # ------------------------------------------------------------------

    async def upsert_officers(self, df: pl.DataFrame, symbol: str) -> None:
        """Upsert officers as Person nodes with IS_OFFICER → Company edges.

        A person who is also a shareholder will be the same Person node,
        since both are keyed by person_name.
        """
        if df is None or df.is_empty():
            return
        for row in df.to_dicts():
            # Handle different column name formats from vnstock
            name = row.get("name") or row.get("officer_name") or ""
            if not name:
                continue
            # Normalize the name to prevent duplicates
            name = _normalize_person_name(name)
            # Map position from various possible column names
            position = (
                row.get("position_en")
                or row.get("position")
                or row.get("officer_position")
                or ""
            )
            # Map own_percent from various possible column names
            own_percent = float(
                row.get("officer_own_percent") or row.get("own_percent") or 0,
            )
            params = {
                "symbol": symbol,
                "person_name": name,
                "position": position,
                "own_percent": own_percent,
            }
            await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                MERGE (p:{NodeLabel.PERSON} {{{Prop.PERSON_NAME}: $person_name}})
                MERGE (p)-[r:{RelType.IS_OFFICER}]->(c)
                SET r.{Prop.POSITION}    = $position,
                    r.{Prop.OWN_PERCENT} = $own_percent
                """,
                params,
            )

    # ------------------------------------------------------------------
    # Derived officer role relationships
    # ------------------------------------------------------------------

    async def upsert_officer_roles(self, df: pl.DataFrame, symbol: str) -> None:
        """Create derived role relationships (IS_BOARD_MEMBER, IS_FOUNDER, IS_EXECUTIVE).

        Examines officer position titles and creates more specific relationship
        types alongside the generic IS_OFFICER edge for richer querying.
        """
        if df is None or df.is_empty():
            return

        # Position keywords for classification
        board_keywords = frozenset(
            {
                "chairman",
                "vice chairman",
                "vice chair",
                "chair",
                "board",
                "independent director",
                "non-executive",
                "member of the board",
                "board member",
                "director",
                # Vietnamese — abbreviations AND full forms
                "thanh vien hdqt",
                "thanh vien hoi dong quan tri",
                "chu tich hdqt",
                "chu tich hoi dong quan tri",
                "pho chu tich hdqt",
                "pho chu tich hoi dong quan tri",
                "chu tich",  # generic "chairman" in Vietnamese
            },
        )
        founder_keywords = frozenset(
            {
                "founder",
                "sang lap",
                "dong sang lap",
                "co-founder",
                "nguoi sang lap",
            },
        )
        executive_keywords = frozenset(
            {
                "ceo",
                "cfo",
                "coo",
                "cto",
                "cio",
                "cmo",
                "chro",
                "chief executive",
                "chief financial",
                "chief operating",
                "chief technology",
                "president",
                "general director",
                "managing director",
                "executive director",
                "tong giam doc",
                "giam doc",
                "pho tong giam doc",
                "giam doc dieu hanh",
                "giam doc tai chinh",
                "giam doc cong nghe",
                "giam doc kinh doanh",
            },
        )

        for row in df.to_dicts():
            name = row.get("name") or row.get("officer_name") or ""
            if not name:
                continue
            name = _normalize_person_name(name)

            position = (
                row.get("position_en")
                or row.get("position")
                or row.get("officer_position")
                or ""
            ).lower()
            # Strip diacritics for keyword matching (same as _is_company_name)
            position_ascii = position.translate(_DIACRITICS_TABLE)

            role_types = [RelType.IS_OFFICER]

            if any(kw in position_ascii for kw in board_keywords):
                role_types.append(RelType.IS_BOARD_MEMBER)
            if any(kw in position_ascii for kw in founder_keywords):
                role_types.append(RelType.IS_FOUNDER)
            if any(kw in position_ascii for kw in executive_keywords):
                role_types.append(RelType.IS_EXECUTIVE)

            for role_type in role_types:
                params = {
                    "symbol": symbol,
                    "person_name": name,
                    "position": row.get("position_en")
                    or row.get("position")
                    or row.get("officer_position")
                    or "",
                }
                await self._run(
                    f"""
                    MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                    MATCH (p:{NodeLabel.PERSON} {{{Prop.PERSON_NAME}: $person_name}})
                    MERGE (p)-[r:{role_type}]->(c)
                    SET r.{Prop.POSITION} = $position
                    """,
                    params,
                )

    # ------------------------------------------------------------------
    # Subsidiaries
    # ------------------------------------------------------------------

    async def upsert_subsidiaries(
        self,
        df: pl.DataFrame,
        parent_symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        if df is None or df.is_empty():
            return

        # Validate parent company exists
        parent_exists = await self._run(
            f"MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent}}) RETURN COUNT(c)",
            {"parent": parent_symbol},
        )
        if not parent_exists or int(parent_exists[0][0]) == 0:
            logger.warning(
                "Parent company %s not found in graph, skipping subsidiaries",
                parent_symbol,
            )
            return

        for row in df.to_dicts():
            # Handle different column name formats from vnstock
            sub_name = row.get("name") or row.get("organ_name") or ""
            if not sub_name:
                continue

            # Resolve subsidiary name to real ticker symbol
            sub_code = self._resolve_subsidiary_symbol(
                sub_name,
                row.get("sub_organ_code"),
                name_to_symbol,
            )

            # Skip if symbol resolves to the parent itself (self-reference)
            if sub_code.upper() == parent_symbol.upper():
                logger.debug("Skipping self-reference subsidiary: %s", sub_name)
                continue

            ownership_pct = float(
                row.get("ownership_percent") or row.get("ownership_perce") or 0,
            )

            params = {
                "parent_symbol": parent_symbol,
                "sub_code": sub_code,
                "sub_name": sub_name,
                "ownership_percent": ownership_pct,
                "relation_type": row.get("type") or row.get("relation_type") or "",
            }

            # Majority ownership → SUBSIDIARY_OF, minority stake → HOLDS_STAKE_IN
            if ownership_pct >= 50:
                await self._run(
                    f"""
                    MATCH (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent_symbol}})
                    MERGE (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sub_code}})
                    ON CREATE SET child.{Prop.NAME} = $sub_name,
                                  child.company_type = 'subsidiary'
                    MERGE (child)-[r:{RelType.SUBSIDIARY_OF}]->(parent)
                    SET r.{Prop.OWNERSHIP_PERCENT} = $ownership_percent,
                        r.{Prop.RELATION_TYPE}     = $relation_type
                    """,
                    params,
                )
            else:
                await self._run(
                    f"""
                    MATCH (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent_symbol}})
                    MERGE (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sub_code}})
                    ON CREATE SET child.{Prop.NAME} = $sub_name,
                                  child.company_type = 'subsidiary'
                    MERGE (parent)-[r:{RelType.HOLDS_STAKE_IN}]->(child)
                    SET r.{Prop.STAKE_PERCENT} = $ownership_percent,
                        r.{Prop.RELATION_TYPE} = $relation_type
                    """,
                    params,
                )

    def _resolve_subsidiary_symbol(
        self,
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
            # Shorter tickers (e.g. FPT, VIC, VNM) are too likely to
            # match parent-company references inside subsidiary names
            # like "Công ty TNHH Phần mềm FPT", causing self-reference
            # detection to skip ALL subsidiaries of that parent.
            import re as _re

            for name_key, sym in name_to_symbol.items():
                if len(name_key) < 4:
                    continue
                if _re.search(rf"\b{_re.escape(name_key)}\b", sub_lower):
                    return sym

        # Strategy 3: Fallback - deterministic hash for stability across re-runs
        name_hash = hashlib.sha256(sub_name.encode()).hexdigest()[:8].upper()
        return f"SUB_{name_hash}"

    # ------------------------------------------------------------------
    # Shareholders — Person or Company depending on name heuristic
    # ------------------------------------------------------------------

    async def upsert_shareholders(
        self,
        df: pl.DataFrame,
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        """Upsert shareholders as either Company or Person nodes.

        Uses _is_company_name() heuristic to classify. A person who is
        also an officer of the same or another company will share the same
        Person node (keyed by person_name), so their dual role is visible
        in the graph via IS_OFFICER + HOLDS_STAKE_IN edges.

        If name_to_symbol is provided, corporate shareholders whose name
        matches a known company will be keyed by SYMBOL instead of NAME,
        preventing duplicate Company nodes and enabling cross-shareholding queries.
        name_to_symbol maps lowercase company names/symbols to their symbols.
        """
        if df is None or df.is_empty():
            return

        for row in df.to_dicts():
            await self._upsert_single_shareholder(row, symbol, name_to_symbol)

    async def _upsert_single_shareholder(
        self,
        row: dict,
        symbol: str,
        name_to_symbol: dict[str, str] | None = None,
    ) -> None:
        """Process a single shareholder row."""
        holder_name = row.get("share_holder") or ""
        stake = float(row.get("share_own_percent") or 0)
        if not holder_name:
            return

        # Normalize person names to prevent duplicates
        is_company = _is_company_name(holder_name)
        if not is_company:
            holder_name = _normalize_person_name(holder_name)

        # For corporate shareholders, try to resolve name to a known symbol
        holder_symbol = None
        if is_company:
            holder_symbol = self._resolve_holder_symbol(
                holder_name,
                name_to_symbol,
            )

        if is_company and holder_symbol:
            await self._upsert_corporate_shareholder(symbol, holder_symbol, stake)
        elif is_company:
            await self._upsert_unknown_corporate_shareholder(symbol, holder_name, stake)
        else:
            await self._upsert_individual_shareholder(symbol, holder_name, stake)

    def _resolve_holder_symbol(
        self,
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

    async def _upsert_corporate_shareholder(
        self,
        target_symbol: str,
        holder_symbol: str,
        stake: float,
    ) -> None:
        """Upsert a known corporate shareholder (Company→Company edge)."""
        params = {
            "target_symbol": target_symbol,
            "holder_symbol": holder_symbol,
            "stake_percent": stake,
        }
        await self._run(
            f"""
            MATCH (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $target_symbol}})
            MERGE (holder:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $holder_symbol}})
            ON CREATE SET holder.{Prop.NAME} = $holder_symbol,
                          holder.company_type = 'subsidiary'
            MERGE (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target)
            SET r.{Prop.STAKE_PERCENT} = $stake_percent
            """,
            params,
        )

    async def _upsert_unknown_corporate_shareholder(
        self,
        target_symbol: str,
        holder_name: str,
        stake: float,
    ) -> None:
        """Upsert an unknown corporate shareholder (keyed by NAME)."""
        # Normalize name to prevent duplicates from spacing/casing variations
        normalized_name = " ".join(holder_name.split())
        params = {
            "target_symbol": target_symbol,
            "holder_name": normalized_name,
            "stake_percent": stake,
        }
        await self._run(
            f"""
            MATCH (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $target_symbol}})
            MERGE (holder:{NodeLabel.COMPANY} {{{Prop.NAME}: $holder_name}})
            ON CREATE SET holder.{Prop.SYMBOL} = $holder_name,
                          holder.company_type = 'subsidiary'
            MERGE (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target)
            SET r.{Prop.STAKE_PERCENT} = $stake_percent
            """,
            params,
        )

    async def _upsert_individual_shareholder(
        self,
        target_symbol: str,
        holder_name: str,
        stake: float,
    ) -> None:
        """Upsert an individual shareholder (Person node)."""
        params = {
            "target_symbol": target_symbol,
            "holder_name": holder_name,
            "stake_percent": stake,
        }
        await self._run(
            f"""
            MATCH (target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $target_symbol}})
            MERGE (holder:{NodeLabel.PERSON} {{{Prop.PERSON_NAME}: $holder_name}})
            MERGE (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target)
            SET r.{Prop.STAKE_PERCENT} = $stake_percent
            """,
            params,
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    async def deduplicate_nodes(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        stats["company"] = await self._dedupe_company_by_symbol()
        stats["person"] = await self._dedupe_person_by_name()
        stats["indicator"] = await self._dedupe_indicator_by_symbol_period()
        stats["financial_statement"] = await self._dedupe_fin_stmt_by_identity()
        stats["date"] = await self._dedupe_date_by_date()
        stats["quarter"] = await self._dedupe_quarter_by_year_quarter()
        stats["year"] = await self._dedupe_year_by_year()
        stats["sector"] = await self._dedupe_sector_by_name()
        stats["industry"] = await self._dedupe_industry_by_name()
        logger.info("Deduplication finished: %s", stats)
        return stats

    async def _dedupe_person_by_name(self) -> int:
        rows = await self._run(
            f"""
            MATCH (p:{NodeLabel.PERSON})
            WITH p.{Prop.PERSON_NAME} AS name, collect(p) AS nodes
            WHERE name IS NOT NULL AND name <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (dup)-[r_off:{RelType.IS_OFFICER}]->(c:{NodeLabel.COMPANY})
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[r2:{RelType.IS_OFFICER}]->(c)
                SET r2.{Prop.POSITION} = coalesce(r2.{Prop.POSITION}, r_off.{Prop.POSITION}),
                    r2.{Prop.OWN_PERCENT} = coalesce(r2.{Prop.OWN_PERCENT}, r_off.{Prop.OWN_PERCENT})
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[r_hold:{RelType.HOLDS_STAKE_IN}]->(target:{NodeLabel.COMPANY})
            FOREACH (_ IN CASE WHEN target IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[r2:{RelType.HOLDS_STAKE_IN}]->(target)
                SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r_hold.{Prop.STAKE_PERCENT})
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_company_by_symbol(self) -> int:
        """Deduplicate Company nodes by symbol using small per-type queries.

        The original single-query approach with 12 chained OPTIONAL MATCH clauses
        caused OOM because FalkorDB had to hold the full cross-product of all
        relationships in memory. This version processes one duplicate pair at a
        time, one relationship type per query.
        """
        total_removed = 0

        # Find all (keep, dup) pairs where keep and dup share the same symbol.
        # Process in batches via LIMIT to avoid loading all pairs at once.
        while True:
            rows = await self._run(
                f"""
                MATCH (c:{NodeLabel.COMPANY})
                WITH c.{Prop.SYMBOL} AS sym, collect(c) AS nodes
                WHERE sym IS NOT NULL AND sym <> '' AND size(nodes) > 1
                UNWIND nodes[1..] AS dup
                RETURN sym, nodes[0] AS keep, dup
                LIMIT 10
                """,
            )
            if not rows:
                break

            for row in rows:
                sym = row[0]

                # --- Outgoing relationships from dup -> keep ---
                # For each rel type, match dup by symbol+properties, rewire to keep

                # HAS_INDICATOR, HAS_FINANCIAL_STATEMENTS,
                # BELONGS_TO, BELONGS_TO_INDUSTRY (no properties to preserve)
                for rel_type, target_label in [
                    (RelType.HAS_INDICATOR, NodeLabel.INDICATOR),
                    (RelType.HAS_FINANCIAL_STATEMENTS, NodeLabel.FINANCIAL_STATEMENT),
                    (RelType.BELONGS_TO, NodeLabel.SECTOR),
                    (RelType.BELONGS_TO_INDUSTRY, NodeLabel.INDUSTRY),
                ]:
                    await self._run(
                        f"""
                        MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[:{rel_type}]->(t:{target_label})
                        WITH t
                        LIMIT 100
                        MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                        WITH t, keep
                        LIMIT 100
                        MERGE (keep)-[:{rel_type}]->(t)
                        """,
                        {"sym": sym},
                    )

                # COMPETES_WITH (outgoing)
                await self._run(
                    f"""
                    MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[:{RelType.COMPETES_WITH}]->(other:{NodeLabel.COMPANY})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(other) <> id(keep)
                    MERGE (keep)-[:{RelType.COMPETES_WITH}]->(other)
                    """,
                    {"sym": sym},
                )

                # SUBSIDIARY_OF (outgoing, preserve properties)
                await self._run(
                    f"""
                    MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(parent) <> id(keep)
                    MERGE (keep)-[r2:{RelType.SUBSIDIARY_OF}]->(parent)
                    SET r2.{Prop.OWNERSHIP_PERCENT} = coalesce(r2.{Prop.OWNERSHIP_PERCENT}, r.{Prop.OWNERSHIP_PERCENT}),
                        r2.{Prop.RELATION_TYPE} = coalesce(r2.{Prop.RELATION_TYPE}, r.{Prop.RELATION_TYPE})
                    """,
                    {"sym": sym},
                )

                # HOLDS_STAKE_IN (outgoing, preserve properties)
                await self._run(
                    f"""
                    MATCH (dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})-[r:{RelType.HOLDS_STAKE_IN}]->(target:{NodeLabel.COMPANY})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(target) <> id(keep)
                    MERGE (keep)-[r2:{RelType.HOLDS_STAKE_IN}]->(target)
                    SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r.{Prop.STAKE_PERCENT})
                    """,
                    {"sym": sym},
                )

                # --- Incoming relationships -> dup ---

                # Incoming COMPETES_WITH
                await self._run(
                    f"""
                    MATCH (other:{NodeLabel.COMPANY})-[:{RelType.COMPETES_WITH}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(other) <> id(keep)
                    MERGE (other)-[:{RelType.COMPETES_WITH}]->(keep)
                    """,
                    {"sym": sym},
                )

                # Incoming SUBSIDIARY_OF (preserve properties)
                await self._run(
                    f"""
                    MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(child) <> id(keep)
                    MERGE (child)-[r2:{RelType.SUBSIDIARY_OF}]->(keep)
                    SET r2.{Prop.OWNERSHIP_PERCENT} = coalesce(r2.{Prop.OWNERSHIP_PERCENT}, r.{Prop.OWNERSHIP_PERCENT}),
                        r2.{Prop.RELATION_TYPE} = coalesce(r2.{Prop.RELATION_TYPE}, r.{Prop.RELATION_TYPE})
                    """,
                    {"sym": sym},
                )

                # Incoming HOLDS_STAKE_IN from Company (preserve properties)
                await self._run(
                    f"""
                    MATCH (holder:{NodeLabel.COMPANY})-[r:{RelType.HOLDS_STAKE_IN}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WHERE id(holder) <> id(keep)
                    MERGE (holder)-[r2:{RelType.HOLDS_STAKE_IN}]->(keep)
                    SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r.{Prop.STAKE_PERCENT})
                    """,
                    {"sym": sym},
                )

                # Incoming IS_OFFICER from Person (preserve properties)
                await self._run(
                    f"""
                    MATCH (person:{NodeLabel.PERSON})-[r:{RelType.IS_OFFICER}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MERGE (person)-[r2:{RelType.IS_OFFICER}]->(keep)
                    SET r2.{Prop.POSITION} = coalesce(r2.{Prop.POSITION}, r.{Prop.POSITION}),
                        r2.{Prop.OWN_PERCENT} = coalesce(r2.{Prop.OWN_PERCENT}, r.{Prop.OWN_PERCENT})
                    """,
                    {"sym": sym},
                )

                # Incoming HOLDS_STAKE_IN from Person (preserve properties)
                await self._run(
                    f"""
                    MATCH (person:{NodeLabel.PERSON})-[r:{RelType.HOLDS_STAKE_IN}]->(dup:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MATCH (keep:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    MERGE (person)-[r2:{RelType.HOLDS_STAKE_IN}]->(keep)
                    SET r2.{Prop.STAKE_PERCENT} = coalesce(r2.{Prop.STAKE_PERCENT}, r.{Prop.STAKE_PERCENT})
                    """,
                    {"sym": sym},
                )

                # Merge properties from dup into keep, then delete dup.
                # Keep the node with the most properties (most data).
                await self._run(
                    f"""
                    MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}})
                    WITH c
                    ORDER BY size(keys(c)) DESC
                    WITH collect(c) AS nodes
                    WITH nodes[0] AS keep, nodes[1..] AS dups
                    UNWIND dups AS dup
                    SET keep += properties(dup)
                    WITH dup
                    DETACH DELETE dup
                    RETURN COUNT(*)
                    """,
                    {"sym": sym},
                )
                total_removed += 1

        return total_removed

    async def _dedupe_indicator_by_symbol_period(self) -> int:
        rows = await self._run(
            f"""
            MATCH (i:{NodeLabel.INDICATOR})
            WITH i.{Prop.SYMBOL} AS symbol, i.{Prop.YEAR} AS y, i.{Prop.QUARTER} AS q, collect(i) AS nodes
            WHERE symbol IS NOT NULL AND symbol <> ''
              AND y IS NOT NULL AND q IS NOT NULL
              AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.HAS_INDICATOR}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.HAS_INDICATOR}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.MEASURED_ON}]->(q:{NodeLabel.QUARTER})
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.MEASURED_ON}]->(q)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_fin_stmt_by_identity(self) -> int:
        rows = await self._run(
            f"""
            MATCH (fs:{NodeLabel.FINANCIAL_STATEMENT})
            WITH fs.{Prop.SYMBOL} AS symbol,
                 fs.{Prop.STATEMENT_TYPE} AS st,
                 fs.{Prop.PERIOD} AS p,
                 fs.{Prop.YEAR} AS y,
                 fs.{Prop.QUARTER} AS q,
                 collect(fs) AS nodes
            WHERE symbol IS NOT NULL AND symbol <> ''
              AND st IS NOT NULL AND p IS NOT NULL AND y IS NOT NULL AND q IS NOT NULL
              AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.HAS_FINANCIAL_STATEMENTS}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.FOR_QUARTER}]->(q:{NodeLabel.QUARTER})
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.FOR_QUARTER}]->(q)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.FOR_YEAR}]->(y:{NodeLabel.YEAR})
            FOREACH (_ IN CASE WHEN y IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.FOR_YEAR}]->(y)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_date_by_date(self) -> int:
        rows = await self._run(
            f"""
            MATCH (d:{NodeLabel.DATE})
            WITH d.{Prop.DATE} AS dt, collect(d) AS nodes
            WHERE dt IS NOT NULL AND dt <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (dup)-[:{RelType.IN_QUARTER}]->(q:{NodeLabel.QUARTER})
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.IN_QUARTER}]->(q)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_quarter_by_year_quarter(self) -> int:
        rows = await self._run(
            f"""
            MATCH (q:{NodeLabel.QUARTER})
            WITH q.{Prop.YEAR} AS y, q.{Prop.QUARTER} AS qq, collect(q) AS nodes
            WHERE y IS NOT NULL AND qq IS NOT NULL AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (d:{NodeLabel.DATE})-[:{RelType.IN_QUARTER}]->(dup)
            FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
                MERGE (d)-[:{RelType.IN_QUARTER}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (i:{NodeLabel.INDICATOR})-[:{RelType.MEASURED_ON}]->(dup)
            FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END |
                MERGE (i)-[:{RelType.MEASURED_ON}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (fs:{NodeLabel.FINANCIAL_STATEMENT})-[:{RelType.FOR_QUARTER}]->(dup)
            FOREACH (_ IN CASE WHEN fs IS NULL THEN [] ELSE [1] END |
                MERGE (fs)-[:{RelType.FOR_QUARTER}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (dup)-[:{RelType.IN_YEAR}]->(y:{NodeLabel.YEAR})
            FOREACH (_ IN CASE WHEN y IS NULL THEN [] ELSE [1] END |
                MERGE (keep)-[:{RelType.IN_YEAR}]->(y)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_year_by_year(self) -> int:
        rows = await self._run(
            f"""
            MATCH (y:{NodeLabel.YEAR})
            WITH y.{Prop.YEAR} AS yy, collect(y) AS nodes
            WHERE yy IS NOT NULL AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (q:{NodeLabel.QUARTER})-[:{RelType.IN_YEAR}]->(dup)
            FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                MERGE (q)-[:{RelType.IN_YEAR}]->(keep)
            )
            WITH keep, dup

            OPTIONAL MATCH (fs:{NodeLabel.FINANCIAL_STATEMENT})-[:{RelType.FOR_YEAR}]->(dup)
            FOREACH (_ IN CASE WHEN fs IS NULL THEN [] ELSE [1] END |
                MERGE (fs)-[:{RelType.FOR_YEAR}]->(keep)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_sector_by_name(self) -> int:
        rows = await self._run(
            f"""
            MATCH (s:{NodeLabel.SECTOR})
            WITH s.{Prop.NAME} AS name, collect(s) AS nodes
            WHERE name IS NOT NULL AND name <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.BELONGS_TO}]->(keep)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    async def _dedupe_industry_by_name(self) -> int:
        rows = await self._run(
            f"""
            MATCH (ind:{NodeLabel.INDUSTRY})
            WITH ind.{Prop.NAME} AS name, collect(ind) AS nodes
            WHERE name IS NOT NULL AND name <> '' AND size(nodes) > 1
            WITH nodes[0] AS keep, nodes[1..] AS dups
            UNWIND dups AS dup

            OPTIONAL MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO_INDUSTRY}]->(dup)
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (c)-[:{RelType.BELONGS_TO_INDUSTRY}]->(keep)
            )
            WITH keep, dup

            SET keep += properties(dup)
            WITH dup
            DETACH DELETE dup
            RETURN COUNT(*)
            """,
        )
        return int(rows[0][0]) if rows else 0

    # ------------------------------------------------------------------
    # Country nodes
    # ------------------------------------------------------------------

    async def upsert_country(self, code: str, name: str) -> None:
        """Upsert a Country reference node."""
        cypher = """
            MERGE (c:{country_label} {{ {code_prop}: $code }})
            SET c.{name_prop} = $name
        """.format(  # noqa: UP032
            country_label=NodeLabel.COUNTRY,
            code_prop=Prop.CODE,
            name_prop=Prop.NAME,
        )
        await self._run(cypher, {"code": code, "name": name})

    # ------------------------------------------------------------------
    # MacroIndicator nodes
    # ------------------------------------------------------------------

    async def upsert_macro_indicator(self, df: pl.DataFrame) -> None:
        """Upsert macro indicators from a DataFrame.

        Expected columns: name, value, unit, date, country, category, frequency, source
        Composite key: (name, date, country, source)
        """
        cypher_template = """
                MERGE (m:{macro_label} {{
                    {name_prop}: $name,
                    {date_prop}: $date_val,
                    {country_prop}: $country,
                    {source_prop}: $source
                }})
                SET m.{value_prop}    = $value,
                    m.{unit_prop}     = $unit,
                    m.{category_prop} = $category,
                    m.{frequency_prop} = $frequency

                WITH m
                MERGE (c:{country_label} {{ {code_prop}: $country }})
                ON CREATE SET c.{name_prop} = $country_name
                MERGE (c)-[:{has_macro_rel}]->(m)

                WITH m
                MERGE (d:{date_label} {{ {date_prop}: $date_val }})
                SET d.{year_prop}  = $year,
                    d.{month_prop} = $month,
                    d.{day_prop}   = $day
                MERGE (q:{quarter_label} {{
                    {year_prop}: $year, {quarter_prop}: $quarter
                }})
                MERGE (y:{year_label} {{ {year_prop}: $year }})
                MERGE (d)-[:{in_quarter_rel}]->(q)
                MERGE (q)-[:{in_year_rel}]->(y)
                MERGE (m)-[:{measured_on_rel}]->(d)
        """

        for row in df.to_dicts():
            name = row.get(Prop.NAME, "")
            date_val = row.get(Prop.DATE, "")
            country = row.get(Prop.COUNTRY, "")
            source = row.get(Prop.SOURCE, "")
            value = row.get(Prop.VALUE)
            unit = row.get(Prop.UNIT, "")
            category = row.get(Prop.CATEGORY, "")
            frequency = row.get(Prop.FREQUENCY, "annual")

            if not name or not date_val or not country:
                continue

            # Parse date for time hierarchy
            try:
                d = date.fromisoformat(str(date_val)[:10])
                year = d.year
                month = d.month
                day = d.day
                quarter = (month - 1) // 3 + 1
            except (ValueError, TypeError):
                logger.debug("Skipping invalid date: %s", date_val)
                continue

            cypher = cypher_template.format(
                macro_label=NodeLabel.MACRO_INDICATOR,
                name_prop=Prop.NAME,
                date_prop=Prop.DATE,
                country_prop=Prop.COUNTRY,
                source_prop=Prop.SOURCE,
                value_prop=Prop.VALUE,
                unit_prop=Prop.UNIT,
                category_prop=Prop.CATEGORY,
                frequency_prop=Prop.FREQUENCY,
                country_label=NodeLabel.COUNTRY,
                code_prop=Prop.CODE,
                has_macro_rel=RelType.HAS_MACRO_INDICATOR,
                date_label=NodeLabel.DATE,
                year_prop=Prop.YEAR,
                month_prop=Prop.MONTH,
                day_prop=Prop.DAY,
                quarter_label=NodeLabel.QUARTER,
                quarter_prop=Prop.QUARTER,
                year_label=NodeLabel.YEAR,
                in_quarter_rel=RelType.IN_QUARTER,
                in_year_rel=RelType.IN_YEAR,
                measured_on_rel=RelType.MEASURED_ON,
            )

            await self._run(
                cypher,
                {
                    "name": name,
                    "date_val": str(date_val)[:10],
                    "country": country,
                    "country_name": row.get("country_name", country),
                    "source": source,
                    "value": float(value) if value is not None else None,
                    "unit": unit,
                    "category": category,
                    "frequency": frequency,
                    "year": year,
                    "month": month,
                    "day": day,
                    "quarter": quarter,
                },
            )

    async def upsert_macro_sector_link(
        self,
        macro_name: str,
        sector_name: str,
        reason: str = "",
    ) -> None:
        """Link a macro indicator to a sector it affects."""
        cypher = """
            MATCH (m:{macro_label} {{ {name_prop}: $macro_name }})
            MATCH (s:{sector_label} {{ {name_prop}: $sector_name }})
            MERGE (m)-[r:{affects_rel}]->(s)
            SET r.{reason_prop} = $reason
        """.format(  # noqa: UP032
            macro_label=NodeLabel.MACRO_INDICATOR,
            name_prop=Prop.NAME,
            sector_label=NodeLabel.SECTOR,
            affects_rel=RelType.AFFECTS_SECTOR,
            reason_prop=Prop.REASON,
        )
        await self._run(
            cypher,
            {"macro_name": macro_name, "sector_name": sector_name, "reason": reason},
        )

    async def upsert_macro_industry_link(
        self,
        macro_name: str,
        industry_name: str,
        reason: str = "",
    ) -> None:
        """Link a macro indicator to an industry it affects."""
        cypher = """
            MATCH (m:{macro_label} {{ {name_prop}: $macro_name }})
            MATCH (i:{industry_label} {{ {name_prop}: $industry_name }})
            MERGE (m)-[r:{affects_rel}]->(i)
            SET r.{reason_prop} = $reason
        """.format(  # noqa: UP032
            macro_label=NodeLabel.MACRO_INDICATOR,
            name_prop=Prop.NAME,
            industry_label=NodeLabel.INDUSTRY,
            affects_rel=RelType.AFFECTS_INDUSTRY,
            reason_prop=Prop.REASON,
        )
        await self._run(
            cypher,
            {
                "macro_name": macro_name,
                "industry_name": industry_name,
                "reason": reason,
            },
        )

    async def upsert_auditor(
        self,
        symbol: str,
        auditor_name: str,
    ) -> None:
        """Create AUDITED_BY edge from company to its audit firm."""
        if not auditor_name:
            return

        # Create a stable identifier for the audit firm from its name
        import re

        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", auditor_name.lower()).strip("_")
        safe_name = re.sub(r"_+", "_", safe_name)[:50]
        if not safe_name:
            return
        auditor_id = f"AUD_{safe_name}"

        cypher = f"""
            MATCH (c:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $symbol }})
            MERGE (a:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $auditor_id }})
            ON CREATE SET a.{Prop.NAME} = $auditor_name,
                          a.company_type = 'audit_firm'
            MERGE (c)-[r:{RelType.AUDITED_BY}]->(a)
            SET r.{Prop.AUDITOR_NAME} = $auditor_name
        """
        await self._run(
            cypher,
            {
                "symbol": symbol,
                "auditor_id": auditor_id,
                "auditor_name": auditor_name,
            },
        )

    # ------------------------------------------------------------------
    # Corporate events metadata (Phase 1b)
    # ------------------------------------------------------------------

    async def upsert_company_events(
        self,
        symbol: str,
        events_df: pl.DataFrame,
    ) -> None:
        """Store latest corporate action dates as properties on the Company node.

        Extracts the most recent event dates for dividend, issuance, and
        meeting event types and sets them as node properties so they can
        be used as signals to trigger deeper data collection.
        """
        if events_df.is_empty():
            return

        # Normalize column names (case-insensitive)
        df = events_df
        rename: dict[str, str] = {}
        for col in df.columns:
            lower = col.lower()
            if lower == "event_code":
                rename[col] = "event_code"
            elif lower == "exright_date":
                rename[col] = "exright_date"
            elif lower == "public_date":
                rename[col] = "public_date"
            elif lower == "record_date":
                rename[col] = "record_date"
        if rename:
            df = df.rename(rename)

        if "event_code" not in df.columns:
            return

        # Find the latest date for each event type
        # Standardize date column to use
        date_col = None
        for col in ("exright_date", "public_date", "record_date"):
            if col in df.columns:
                date_col = col
                break

        if date_col is None:
            return

        # Parse dates and find latest per event type
        latest: dict[str, str | None] = {
            "DIV": None,
            "ISS": None,
            "AGME": None,
        }
        for row in df.to_dicts():
            code = str(row.get("event_code", "")).strip().upper()
            if code not in latest:
                continue
            raw_date = row.get(date_col)
            if raw_date is None:
                continue
            raw_str = str(raw_date)[:10]  # Take only YYYY-MM-DD
            current = latest[code]
            if current is None or raw_str > current:
                latest[code] = raw_str

        # Build SET clause
        sets: list[str] = []
        params: dict[str, str] = {"symbol": symbol}
        for event_type, prop_name in [
            ("DIV", Prop.LAST_DIVIDEND_DATE),
            ("ISS", Prop.LAST_ISSUANCE_DATE),
            ("AGME", Prop.LAST_MEETING_DATE),
        ]:
            date_val = latest.get(event_type)
            if date_val:
                param_key = f"{event_type.lower()}_date"
                sets.append(f"SET c.{prop_name} = ${param_key}")
                params[param_key] = date_val

        if not sets:
            return

        sets_str = "\n".join(sets)
        cypher = f"""
            MATCH (c:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $symbol }})
            {sets_str}
        """
        await self._run(cypher, params)

    # ------------------------------------------------------------------
    # Scraper relationship methods (Phase 2)
    # ------------------------------------------------------------------

    async def upsert_company_relationship(
        self,
        source_symbol: str,
        target_symbol: str,
        target_name: str,
        rel_type: str,
        *,
        stake_percent: float | None = None,
        amount: float | None = None,
        interest_rate: float | None = None,
        maturity_date: str | None = None,
        issue_date: str | None = None,
        issue_amount: float | None = None,
        transaction_date: str | None = None,
        description: str | None = None,
    ) -> None:
        """Create a generic Company → Company relationship.

        Used by scrapers to create edges like GUARANTEES, LENDS_TO,
        UNDERWRITTEN_BY, STATE_OWNS, etc.
        """
        if not source_symbol or not target_symbol:
            return

        # Build params
        params: dict[str, object] = {
            "source_symbol": source_symbol,
            "target_symbol": target_symbol,
            "target_name": target_name,
        }

        # Only add non-None properties
        optional_props: dict[str, object] = {}
        if stake_percent is not None:
            optional_props[Prop.STAKE_PERCENT] = stake_percent
        if amount is not None:
            optional_props["amount"] = amount
        if interest_rate is not None:
            optional_props["interest_rate"] = interest_rate
        if maturity_date is not None:
            optional_props["maturity_date"] = maturity_date
        if issue_date is not None:
            optional_props["issue_date"] = issue_date
        if issue_amount is not None:
            optional_props["issue_amount"] = issue_amount
        if transaction_date is not None:
            optional_props["transaction_date"] = transaction_date
        if description is not None:
            optional_props["description"] = description

        if optional_props:
            set_clauses = ", ".join(f"r.{k} = ${k}" for k in optional_props)
            params.update(optional_props)
            set_str = f"SET {set_clauses}"
        else:
            set_str = ""

        cypher = f"""
            MATCH (source:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $source_symbol }})
            MERGE (target:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: $target_symbol }})
            ON CREATE SET target.{Prop.NAME} = $target_name
            MERGE (source)-[r:{rel_type}]->(target)
            {set_str}
        """
        await self._run(cypher, params)

    async def upsert_bonds(self, df: pl.DataFrame) -> int:
        """Upsert bond issuance data as Bond nodes linked to issuing companies.

        Expected columns: issuer_symbol, bond_code, issuer_name, interest_rate,
                         maturity_date, issue_date, issue_amount, currency, status

        Each bond is uniquely identified by its bond_code combined with the
        issuer symbol (stable across re-runs via MERGE).

        Returns:
            Number of Bond nodes upserted.

        """
        if df is None or df.is_empty():
            return 0

        rows: list[dict] = []
        for row in df.to_dicts():
            issuer_symbol = row.get("issuer_symbol", "")
            bond_code = row.get("bond_code", "")
            if not issuer_symbol or not bond_code:
                continue

            # Stable unique ID: issuer_symbol + bond_code
            bond_id = f"{issuer_symbol}_{bond_code}"
            rows.append(
                {
                    "bond_id": bond_id,
                    "issuer_symbol": issuer_symbol,
                    "bond_code": bond_code,
                    "issuer_name": row.get("issuer_name", ""),
                    "interest_rate": row.get("interest_rate"),
                    "maturity_date": row.get("maturity_date", ""),
                    "issue_date": row.get("issue_date", ""),
                    "issue_amount": row.get("issue_amount"),
                    "currency": row.get("currency", ""),
                    "status": row.get("status", ""),
                },
            )

        if not rows:
            return 0

        try:
            await self._run(
                f"""
                UNWIND $rows AS r
                MATCH (c:{NodeLabel.COMPANY} {{ {Prop.SYMBOL}: r.issuer_symbol }})
                MERGE (b:{NodeLabel.BOND} {{ id: r.bond_id }})
                SET b.bond_code    = r.bond_code,
                    b.issuer_symbol = r.issuer_symbol,
                    b.issuer_name   = r.issuer_name,
                    b.interest_rate  = r.interest_rate,
                    b.maturity_date  = r.maturity_date,
                    b.issue_date    = r.issue_date,
                    b.issue_amount  = r.issue_amount,
                    b.currency      = r.currency,
                    b.status       = r.status
                MERGE (c)-[:{RelType.HAS_BOND}]->(b)
                """,
                {"rows": rows},
            )
        except Exception:
            logger.exception("Failed to upsert bonds — skipping batch")
            return 0

        return len(rows)

    async def clear_graph(self) -> dict[str, int]:
        node_rows = await self._run("MATCH (n) RETURN COUNT(n)")
        rel_rows = await self._run("MATCH ()-[r]->() RETURN COUNT(r)")
        nodes_before = int(node_rows[0][0]) if node_rows else 0
        rels_before = int(rel_rows[0][0]) if rel_rows else 0
        await self._run("MATCH (n) DETACH DELETE n")
        logger.warning(
            "Cleared graph '%s' (deleted nodes=%d, relationships=%d)",
            self._graph_name,
            nodes_before,
            rels_before,
        )
        return {"deleted_nodes": nodes_before, "deleted_relationships": rels_before}

    async def __aenter__(self) -> Self:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit async context manager."""
        await self.close()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            close = getattr(self._client, "close", None)
            if callable(close):
                maybe_awaitable = close()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
