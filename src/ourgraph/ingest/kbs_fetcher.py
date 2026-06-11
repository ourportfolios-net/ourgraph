"""KBS Profile Fetcher — enriches the graph with richer KBS data.

Fetches the KBS `/profile/{symbol}` endpoint which provides single-call
company data that is richer than what vnstock's standard methods extract.

Endpoint: https://kbbuddywts.kbsec.com.vn/iis-server/investment/stockinfo/profile/{symbol}
Cost: Free, no auth, rate-limited to ~1 req/s.

Key enrichments over vnstock's VCI/KBS wrappers:
  - Subsidiaries: up to 96 entries (vs ~20 from vnstock) with ownership %
  - Leaders: English position titles (PO field) for better role classification
  - Shareholders: ownership % + share count (vs % only from vnstock)
  - Auditor: KT field (audit firm name)
  - Ownership structure breakdown: founder, domestic >5%, foreign, etc.
  - Charter capital history: date + value over time
  - Shares outstanding: KLCPNY field
"""

from __future__ import annotations

import logging

import httpx
import polars as pl

logger = logging.getLogger(__name__)

API_BASE = "https://kbbuddywts.kbsec.com.vn/iis-server/investment/stockinfo/profile"
REQUEST_TIMEOUT = 30.0


class KbsFetcher:
    """Fetches enriched company profile data from KBS.

    Designed to complement vnstock, not replace it. This fetcher focuses
    on the richer subsidiary, leader, shareholder, and auditor data that
    KBS provides beyond what vnstock's standard API wrappers extract.
    """

    def __init__(self, *, delay: float = 1.0) -> None:
        self._delay = delay
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Fetch raw profile
    # ------------------------------------------------------------------

    async def fetch_raw_profile(self, symbol: str) -> dict | None:
        """Fetch the raw KBS profile JSON for a symbol.

        Returns the full JSON dict on success, None on failure.
        """
        url = f"{API_BASE}/{symbol.upper()}"
        client = await self._ensure_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data: dict = resp.json()
            # Validate the response has the expected structure
            if not isinstance(data, dict) or "SB" not in data:
                logger.warning("KBS: unexpected response shape for %s", symbol)
                return None
            return data
        except httpx.HTTPStatusError as exc:
            logger.debug("KBS: HTTP %d for %s", exc.response.status_code, symbol)
            return None
        except (httpx.RequestError, ValueError) as exc:
            logger.debug("KBS: fetch failed for %s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Extract subsidiaries (enriched — up to 96 entries)
    # ------------------------------------------------------------------

    def extract_subsidiaries(
        self,
        profile: dict,
        parent_symbol: str,
    ) -> pl.DataFrame:
        """Extract subsidiary data from KBS profile.

        Returns DataFrame with columns:
            symbol (parent), name, organ_name, sub_organ_code,
            ownership_percent, as_of_date, source
        """
        subs = profile.get("Subsidiaries") or []
        if not subs:
            return pl.DataFrame()

        rows: list[dict] = []
        for s in subs:
            name = s.get("NM", "")
            if not name:
                continue
            rows.append(
                {
                    "symbol": parent_symbol,
                    "name": name,
                    "organ_name": name,
                    "sub_organ_code": "",
                    "ownership_percent": float(s.get("OR", 0)),
                    "as_of_date": str(s.get("D", ""))[:10],
                    "source": "kbs_profile",
                },
            )

        return pl.DataFrame(rows)

    # ------------------------------------------------------------------
    # Extract leaders (with English positions)
    # ------------------------------------------------------------------

    def extract_leaders(
        self,
        profile: dict,
        parent_symbol: str,
    ) -> pl.DataFrame:
        """Extract leader/officer data from KBS profile.

        The KBS profile provides English position (PO) and position code (PI)
        which are more reliable for role classification than Vietnamese titles.

        Returns DataFrame with columns:
            symbol, officer_name, position (English PO), position_en,
            since_year, source
        """
        leaders = profile.get("Leaders") or []
        if not leaders:
            return pl.DataFrame()

        rows: list[dict] = []
        for ldr in leaders:
            name = ldr.get("NM", "")
            if not name:
                continue
            position_en = ldr.get("PO", "")  # English position
            position_vn = ldr.get("PN", "")  # Vietnamese position name
            since = ldr.get("FD", "")  # Since date/year

            rows.append(
                {
                    "symbol": parent_symbol,
                    "officer_name": name,
                    "position": position_en or position_vn,
                    "position_en": position_en,
                    "position_vn": position_vn,
                    "since": since,
                    "source": "kbs_profile",
                },
            )

        return pl.DataFrame(rows)

    # ------------------------------------------------------------------
    # Extract shareholders (ownership % + share count)
    # ------------------------------------------------------------------

    def extract_shareholders(
        self,
        profile: dict,
        parent_symbol: str,
    ) -> pl.DataFrame:
        """Extract shareholder data from KBS profile.

        KBS provides ownership percentage (OR) and share count (V),
        which is richer than what vnstock's standard wrapper provides.

        Returns DataFrame with columns:
            symbol, share_holder, share_own_percent, share_count,
            as_of_date, source
        """
        holders = profile.get("Shareholders") or []
        if not holders:
            return pl.DataFrame()

        rows: list[dict] = []
        for h in holders:
            name = h.get("NM", "")
            if not name:
                continue
            rows.append(
                {
                    "symbol": parent_symbol,
                    "share_holder": name,
                    "share_own_percent": float(h.get("OR", 0)),
                    "share_count": int(h.get("V", 0)),
                    "as_of_date": str(h.get("D", ""))[:10],
                    "source": "kbs_profile",
                },
            )

        return pl.DataFrame(rows)

    # ------------------------------------------------------------------
    # Extract auditor
    # ------------------------------------------------------------------

    def extract_auditor(self, profile: dict) -> str | None:
        """Extract auditor name from the KT field."""
        auditor = profile.get("KT", "")
        if auditor and str(auditor).strip():
            return str(auditor).strip()
        return None

    # ------------------------------------------------------------------
    # Extract ownership structure breakdown
    # ------------------------------------------------------------------

    def extract_ownership_structure(self, profile: dict) -> list[dict]:
        """Extract ownership breakdown by owner type.

        Returns list of dicts with keys:
            owner_type, ownership_percent, share_count, as_of_date
        """
        ownership = profile.get("Ownership") or []
        results: list[dict] = []
        for o in ownership:
            name = o.get("NM", "")
            if not name:
                continue
            results.append(
                {
                    "owner_type": name,
                    "ownership_percent": float(o.get("OR", 0)),
                    "share_count": int(o.get("SH", 0)),
                    "as_of_date": str(o.get("D", ""))[:10],
                },
            )
        return results

    # ------------------------------------------------------------------
    # Extract company metadata not in vnstock
    # ------------------------------------------------------------------

    def extract_company_metadata(self, profile: dict) -> dict:
        """Extract company metadata fields not provided by vnstock."""
        return {
            "description": str(profile.get("SM", "")),
            "employees": int(profile.get("HM", 0)),
            "shares_outstanding": int(profile.get("KLCPNY", 0)),
            "listing_date": str(profile.get("LD", "")),
            "foundation_date": str(profile.get("FD", "")),
            "charter_capital": int(profile.get("CC", 0)),
            "face_value": int(profile.get("FV", 0)),
            "listing_price": int(profile.get("LP", 0)),
            "address": str(profile.get("ADD", "")),
            "website": str(profile.get("URL", "")),
            "phone": str(profile.get("PHONE", "")),
            "email": str(profile.get("EMAIL", "")),
        }

    # ------------------------------------------------------------------
    # Batch enrichment entry point
    # ------------------------------------------------------------------

    async def enrich_symbol(self, symbol: str) -> dict | None:
        """Fetch and parse KBS profile for a single symbol.

        Returns a dict with keys: subsidiaries, leaders, shareholders,
        auditor, ownership_structure, metadata.  Returns None on fetch
        failure so the caller can fall back to vnstock-only data.
        """
        from asyncio import sleep

        await sleep(self._delay)

        profile = await self.fetch_raw_profile(symbol)
        if profile is None:
            return None

        return {
            "symbol": symbol,
            "subsidiaries": self.extract_subsidiaries(profile, symbol),
            "leaders": self.extract_leaders(profile, symbol),
            "shareholders": self.extract_shareholders(profile, symbol),
            "auditor": self.extract_auditor(profile),
            "ownership_structure": self.extract_ownership_structure(profile),
            "metadata": self.extract_company_metadata(profile),
        }
