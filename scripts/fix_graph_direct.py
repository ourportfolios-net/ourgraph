"""Directly fix graph issues without slow API calls."""

import asyncio
from rich.console import Console

from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder

console = Console()


async def fix_graph_direct():
    """Fix graph issues directly."""
    settings = get_settings()

    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        # === Fix 1: Find and fix subsidiaries with wrong symbols ===
        console.print("[bold]Fix 1: Fix subsidiaries with wrong symbols[/bold]")

        # Get all subsidiaries (nodes that have SUBSIDIARY_OF edge)
        rows = await builder.query_raw(
            "MATCH (child:Company)-[r:SUBSIDIARY_OF]->(parent:Company) "
            "RETURN child.symbol, child.name, parent.symbol "
            "ORDER BY parent.symbol"
        )
        console.print(f"  Found {len(rows)} subsidiaries in graph")

        # Build name_to_symbol mapping from actual companies
        comp_rows = await builder.query_raw(
            "MATCH (c:Company) WHERE c.symbol IS NOT NULL RETURN c.symbol, c.name"
        )
        name_to_symbol = {}
        for r in comp_rows:
            if r[0]:
                name_to_symbol[r[0].lower()] = r[0]
            if r[1]:
                name_to_symbol[r[1].lower()] = r[0]

        # Fix subsidiaries with wrong symbols
        fixed = 0
        for row in rows:
            child_sym, child_name, parent_sym = row[0], row[1], row[2]
            if not child_name:
                continue

            # Try to resolve child_name to real ticker
            child_name_lower = child_name.lower()
            real_sym = None

            # Check if child_name contains a known ticker
            for key, sym in name_to_symbol.items():
                if key in child_name_lower or child_name_lower in key:
                    real_sym = sym
                    break

            if real_sym and real_sym != child_sym:
                console.print(
                    f"  Fixing {child_sym} ({child_name}) -> {real_sym}"
                )
                # Update the subsidiary node's symbol
                await builder.query_raw(
                    "MATCH (c:Company {symbol: $old_sym}) "
                    "SET c.symbol = $new_sym",
                    {"old_sym": child_sym, "new_sym": real_sym},
                )
                fixed += 1

        console.print(f"  ✓ Fixed {fixed} subsidiaries")

        # === Fix 2: Create missing sector/industry links ===
        console.print("\n[bold]Fix 2: Create missing sector/industry links[/bold]")

        # Get companies missing links
        rows = await builder.query_raw(
            "MATCH (c:Company) "
            "OPTIONAL MATCH (c)-[:BELONGS_TO]->(s:Sector) "
            "OPTIONAL MATCH (c)-[:BELONGS_TO_INDUSTRY]->(i:Industry) "
            "WHERE s IS NULL OR i IS NULL "
            "RETURN c.symbol, c.name"
        )
        console.print(f"  Found {len(rows)} companies with missing links")

        # We can't fix without API calls. Instead, show what's missing.
        console.print("  ⚠️ Cannot fix without vnstock API (sector/industry data)")

        # === Fix 3: Create missing SUBSIDIARY_OF edges ===
        console.print("\n[bold]Fix 3: Re-ingest subsidiaries (with rate limiting)[/bold]")

        from ourgraph.ingest.vnstock_fetcher import VnstockFetcher
        from ourgraph.config import VnstockSettings

        fetcher = VnstockFetcher(VnstockSettings())

        # Get all symbols
        comp_rows = await builder.query_raw(
            "MATCH (c:Company) WHERE c.symbol IS NOT NULL RETURN c.symbol"
        )
        all_symbols = [r[0] for r in comp_rows if r[0]]

        # Re-ingest subsidiaries with DELAY to avoid rate limit
        import time

        total = len(all_symbols)
        success = 0
        failed = 0

        for i, sym in enumerate(all_symbols):
            try:
                df = fetcher.get_subsidiaries(sym)
                if not df.is_empty():
                    await builder.upsert_subsidiaries(df, sym, name_to_symbol)
                    success += 1
                    if (i + 1) % 5 == 0:
                        console.print(f"  Progress: {i+1}/{total} (found subs for {success})")
                else:
                    if (i + 1) % 20 == 0:
                        console.print(f"  Progress: {i+1}/{total}")
            except Exception as e:
                failed += 1
                console.print(f"  ✗ Error for {sym}: {e}")

            # Rate limit: 20 requests/minute = 3 seconds delay
            if (i + 1) % 20 == 0:
                console.print("  Waiting 60s for rate limit...")
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(3)  # 3s delay = ~20 requests/minute

        console.print(f"\n  ✓ Done: {success} with subsidiaries, {failed} failed")

        # === Summary ===
        console.print("\n" + "=" * 60)
        console.print("[bold]Running quality check after fixes...[/bold]")
        from ourgraph.quality import run_quality_check

        issues = await run_quality_check(settings)
        if issues:
            console.print(f"\n[red]Still {len(issues)} issues remaining[/red]")
        else:
            console.print("\n[green]✓ All quality issues fixed![/green]")
        console.print("=" * 60)


if __name__ == "__main__":
    asyncio.run(fix_graph_direct())
