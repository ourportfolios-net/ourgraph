#!/usr/bin/env python3
"""
vnstock API Diagnostic Script
==============================
Tests each vnstock endpoint with rate-limit-aware delays.
Usage: uv run scripts/vnstock_diagnostic.py

Key findings from first run:
- VCI source: ALL calls fail with ConnectionError (API unreachable from this network)
- KBS source: Works for symbol listing, company overview
- TCBS: Not a valid Listing source (only KBS, VCI, MSN)
- Rate limit: 20 requests/min for Guest tier
- Our fetcher tries VCI first → wastes rate-limit calls on broken source
"""

import time
import sys

RESULTS: dict[str, list[tuple[str, str, str]]] = {}
"""section -> [(label, source, result)]"""


def record(section: str, label: str, src: str, result: str) -> None:
    RESULTS.setdefault(section, []).append((label, src, result))


def throttle(delay: float = 3.5) -> None:
    """Sleep between API calls to stay under 20 req/min rate limit."""
    if delay > 0:
        time.sleep(delay)


def print_results() -> None:
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for section, rows in RESULTS.items():
        print(f"\n--- {section} ---")
        for label, src, result in rows:
            print(f"  {label} via {src}: {result}")


# ─────────────────────────────────────────────
# 0. Imports
# ─────────────────────────────────────────────
print("=" * 60)
print("IMPORT CHECK")
print("=" * 60)

import vnstock
print(f"vnstock version: {getattr(vnstock, '__version__', 'unknown')}")

import polars as pl
print(f"polars version: {pl.__version__}")
print(f"Python: {sys.version}")

# ─────────────────────────────────────────────
# 1. Symbol listing (KBS only — VCI is broken)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 1: Symbol Listing")
print("=" * 60)

from vnstock import Listing

for src in ["KBS", "VCI", "MSN"]:
    try:
        listing = Listing(source=src)
        print(f"\n--- Source: {src} ---")

        if hasattr(listing, "symbols_by_exchange"):
            try:
                df = listing.symbols_by_exchange()
                print(f"  symbols_by_exchange(): {len(df)} rows")
                if len(df) > 0:
                    cols = list(df.columns)
                    print(f"  Columns: {cols}")
                    exchange_col = next(
                        (c for c in cols if "exchange" in c.lower()), None
                    )
                    ticker_col = next(
                        (c for c in cols if c.lower() in ("ticker", "symbol")), None
                    )
                    if exchange_col and ticker_col:
                        hose = df[df[exchange_col].str.upper() == "HOSE"]
                        hnx = df[df[exchange_col].str.upper() == "HNX"]
                        upcom = df[df[exchange_col].str.upper() == "UPCOM"]
                        print(f"  HOSE={len(hose)}, HNX={len(hnx)}, UPCOM={len(upcom)}")
                        record(
                            "Symbol Listing",
                            f"symbols_by_exchange ({len(df)} total)",
                            src,
                            f"OK — HOSE={len(hose)}, HNX={len(hnx)}",
                        )
                    else:
                        record(
                            "Symbol Listing",
                            "symbols_by_exchange",
                            src,
                            f"OK but no exchange/ticker col — cols={cols}",
                        )
                else:
                    record("Symbol Listing", "symbols_by_exchange", src, "EMPTY")
            except Exception as e:
                print(f"  symbols_by_exchange() FAILED: {e}")
                record("Symbol Listing", "symbols_by_exchange", src, f"FAIL: {e}")
        else:
            print("  No symbols_by_exchange method")
            record("Symbol Listing", "symbols_by_exchange", src, "N/A (no method)")

        throttle(4.0)

        try:
            df = listing.all_symbols()
            print(f"  all_symbols(): {len(df)} rows")
            if len(df) > 0:
                print(f"  Columns: {list(df.columns)}")
                record("Symbol Listing", "all_symbols", src, f"OK — {len(df)} rows")
            else:
                record("Symbol Listing", "all_symbols", src, "EMPTY")
        except Exception as e:
            print(f"  all_symbols() FAILED: {e}")
            record("Symbol Listing", "all_symbols", src, f"FAIL: {e}")

        throttle(4.0)

    except Exception as e:
        print(f"  Source {src} init FAILED: {e}")
        record("Symbol Listing", "init", src, f"FAIL: {e}")

# ─────────────────────────────────────────────
# 2. Company overview (single symbol, all sources)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 2: Company Overview (HPG)")
print("=" * 60)

from vnstock import Company

test_sym = "HPG"
for src in ["KBS", "VCI", "TCBS", "MSN"]:
    try:
        co = Company(symbol=test_sym, source=src)
        df = co.overview()
        if df is not None and len(df) > 0:
            print(f"  {src}: OK — {len(df)} rows, cols={list(df.columns)[:5]}...")
            record("Company Overview", test_sym, src, f"OK — {len(df)} rows")
        else:
            print(f"  {src}: EMPTY/None")
            record("Company Overview", test_sym, src, "EMPTY")
    except Exception as e:
        print(f"  {src}: FAIL — {e}")
        record("Company Overview", test_sym, src, f"FAIL: {e}")
    throttle(4.0)

# ─────────────────────────────────────────────
# 3. Officers (single symbol, all sources)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 3: Officers (HPG)")
print("=" * 60)

for src in ["KBS", "VCI", "TCBS", "MSN"]:
    try:
        co = Company(symbol=test_sym, source=src)
        df = co.officers(filter_by="working")
        if df is not None and len(df) > 0:
            print(f"  {src}: OK — {len(df)} rows, cols={list(df.columns)}")
            record("Officers", test_sym, src, f"OK — {len(df)} rows")
        else:
            print(f"  {src}: EMPTY/None")
            record("Officers", test_sym, src, "EMPTY")
    except Exception as e:
        print(f"  {src}: FAIL — {e}")
        record("Officers", test_sym, src, f"FAIL: {e}")
    throttle(4.0)

# ─────────────────────────────────────────────
# 4. Shareholders (single symbol, all sources)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 4: Shareholders (HPG)")
print("=" * 60)

for src in ["KBS", "VCI", "TCBS", "MSN"]:
    try:
        co = Company(symbol=test_sym, source=src)
        df = co.shareholders()
        if df is not None and len(df) > 0:
            print(f"  {src}: OK — {len(df)} rows, cols={list(df.columns)}")
            record("Shareholders", test_sym, src, f"OK — {len(df)} rows")
        else:
            print(f"  {src}: EMPTY/None")
            record("Shareholders", test_sym, src, "EMPTY")
    except Exception as e:
        print(f"  {src}: FAIL — {e}")
        record("Shareholders", test_sym, src, f"FAIL: {e}")
    throttle(4.0)

# ─────────────────────────────────────────────
# 5. Subsidiaries (single symbol, all sources)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 5: Subsidiaries (HPG)")
print("=" * 60)

for src in ["KBS", "VCI", "TCBS", "MSN"]:
    try:
        co = Company(symbol=test_sym, source=src)
        df = co.subsidiaries()
        if df is not None and len(df) > 0:
            print(f"  {src}: OK — {len(df)} rows, cols={list(df.columns)}")
            record("Subsidiaries", test_sym, src, f"OK — {len(df)} rows")
        else:
            print(f"  {src}: EMPTY/None")
            record("Subsidiaries", test_sym, src, "EMPTY")
    except Exception as e:
        print(f"  {src}: FAIL — {e}")
        record("Subsidiaries", test_sym, src, f"FAIL: {e}")
    throttle(4.0)

# ─────────────────────────────────────────────
# 6. Price history (single symbol, all sources)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 6: Price History (HPG)")
print("=" * 60)

from vnstock import Quote

for src in ["KBS", "VCI", "TCBS", "MSN"]:
    try:
        quote = Quote(symbol=test_sym, source=src)
        df = quote.history(start="2024-01-01", end="2024-01-31", interval="1D")
        if df is not None and len(df) > 0:
            print(f"  {src}: OK — {len(df)} rows, cols={list(df.columns)}")
            record("Price History", test_sym, src, f"OK — {len(df)} rows")
        else:
            print(f"  {src}: EMPTY/None")
            record("Price History", test_sym, src, "EMPTY")
    except Exception as e:
        print(f"  {src}: FAIL — {e}")
        record("Price History", test_sym, src, f"FAIL: {e}")
    throttle(4.0)

# ─────────────────────────────────────────────
# 7. Financial statements (single symbol, all sources)
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 7: Financial Statements (HPG)")
print("=" * 60)

from vnstock import Finance

statements = ["balance_sheet", "income_statement", "cash_flow", "ratio"]

for stmt in statements:
    print(f"\n  --- {stmt} ---")
    for src in ["KBS", "VCI", "TCBS", "MSN"]:
        try:
            fin = Finance(symbol=test_sym, source=src)
            method = getattr(fin, stmt)
            df = method(period="quarter")
            if df is not None and len(df) > 0:
                print(f"    {src}: OK — {len(df)} rows")
                record(f"Finance/{stmt}", test_sym, src, f"OK — {len(df)} rows")
            else:
                print(f"    {src}: EMPTY/None")
                record(f"Finance/{stmt}", test_sym, src, "EMPTY")
        except Exception as e:
            print(f"    {src}: FAIL — {e}")
            record(f"Finance/{stmt}", test_sym, src, f"FAIL: {e}")
        throttle(4.0)

# ─────────────────────────────────────────────
# 8. Our VnstockFetcher class
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 8: Our VnstockFetcher class")
print("=" * 60)

try:
    from ourgraph.config import get_settings

    settings = get_settings()
    print(f"  Config source: {settings.vnstock.source}")
    print(f"  Config api_delay: {settings.vnstock.api_delay}")
except Exception as e:
    print(f"  Config load FAILED: {e}")
    settings = None

if settings:
    from ourgraph.ingest.vnstock_fetcher import VnstockFetcher

    fetcher = VnstockFetcher(settings.vnstock)

    for sym in ["HPG", "VCB", "FPT"]:
        overview = fetcher.get_company_overview(sym)
        shareholders = fetcher.get_shareholders(sym)
        subs = fetcher.get_subsidiaries(sym)
        officers = fetcher.get_officers(sym)

        has_data = any(
            not df.is_empty() for df in [overview, shareholders, subs, officers]
        )
        status = "OK" if has_data else "ALL EMPTY"
        print(
            f"  {sym}: overview={len(overview)}, shareholders={len(shareholders)}, subs={len(subs)}, officers={len(officers)} → {status}"
        )
        record("OurFetcher", sym, settings.vnstock.source, status)

# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
print_results()
print("\nDone.")