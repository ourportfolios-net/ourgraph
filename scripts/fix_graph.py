"""Fix graph issues and re-ingest missing data."""

import asyncio
from rich.console import Console

from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher
from ourgraph.config import VnstockSettings

console = Console()


async def fix_graph():
    """Fix graph quality issues."""
    settings = get_settings()
    fetcher = VnstockFetcher(settings.vnstock)

    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        # === Fix 1: Find and fix isolated companies ===
        console.print("[bold]Fix 1: Isolated Companies[/bold]")
        rows = await builder.query_raw(
            "MATCH (c:Company) WHERE NOT (c)--() RETURN c.symbol, c.name"
        )
        isolated = [(r[0], r[1]) for r in rows if r[0]]
        console.print(f"  Found {len(isolated)} isolated companies")

        for sym, name in isolated:
            console.print(f"  Fixing {sym} ({name})...")
            try:
                df = fetcher.get_company_overview(sym)
                if not df.is_empty():
                    await builder.upsert_companies(df)
                    await builder.upsert_sector_industry(df)
                    console.print(f"    ✓ Fixed {sym}")
                else:
                    console.print(f"    ✗ No data for {sym}")
            except Exception as e:
                console.print(f"    ✗ Error: {e}")

        # === Fix 2: Find and fix missing sector/industry links ===
        console.print("\n[bold]Fix 2: Missing Sector/Industry Links[/bold]")
        rows = await builder.query_raw(
            "MATCH (c:Company) "
            "OPTIONAL MATCH (c)-[:BELONGS_TO]->(s:Sector) "
            "OPTIONAL MATCH (c)-[:BELONGS_TO_INDUSTRY]->(i:Industry) "
            "WITH c, s, i "
            "WHERE s IS NULL OR i IS NULL "
            "RETURN c.symbol, c.name"
        )
        missing = [(r[0], r[1]) for r in rows if r[0]]
        console.print(f"  Found {len(missing)} companies with missing links")

        for sym, name in missing:
            if sym in [m[0] for m in isolated]:
                continue  # Already processed
            console.print(f"  Fixing {sym} ({name})...")
            try:
                df = fetcher.get_company_overview(sym)
                if not df.is_empty():
                    await builder.upsert_sector_industry(df)
                    console.print(f"    ✓ Fixed {sym}")
                else:
                    console.print(f"    ✗ No data for {sym}")
            except Exception as e:
                console.print(f"    ✗ Error: {e}")

        # === Fix 3: Re-ingest subsidiaries with fixed code ===
        console.print("\n[bold]Fix 3: Re-ingest Subsidiaries[/bold]")
        # Get all symbols
        rows = await builder.query_raw(
            "MATCH (c:Company) WHERE c.symbol IS NOT NULL RETURN c.symbol"
        )
        all_symbols = [r[0] for r in rows if r[0]]
        console.print(f"  Processing {len(all_symbols)} companies...")

        # Build name_to_symbol map
        rows = await builder.query_raw(
            "MATCH (c:Company) RETURN c.symbol, c.name"
        )
        name_to_symbol = {}
        for r in rows:
            if r[0]:
                name_to_symbol[r[0].lower()] = r[0]
            if r[1]:
                name_to_symbol[r[1].lower()] = r[0]

        # Re-ingest subsidiaries for each company
        fixed = 0
        for i, sym in enumerate(all_symbols):
            try:
                df = fetcher.get_subsidiaries(sym)
                if not df.is_empty():
                    await builder.upsert_subsidiaries(df, sym, name_to_symbol)
                    fixed += 1
                    if fixed % 10 == 0:
                        console.print(f"    Progress: {i+1}/{len(all_symbols)} companies...")
            except Exception as e:
                console.print(f"    ✗ Error for {sym}: {e}")

        console.print(f"  ✓ Re-ingested subsidiaries for {fixed} companies")

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
    asyncio.run(fix_graph())
