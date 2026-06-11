"""Re-ingest company profiles for target tickers to create industry/sector links."""
import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher

TARGETS = ["HPG", "HSG", "NKG", "POM", "VIC", "VHM"]


async def main():
    settings = get_settings()
    vnstock = VnstockFetcher(settings.vnstock)

    for sym in TARGETS:
        try:
            df = vnstock.get_company_overview(sym)
            if df.is_empty():
                print(f"{sym}: EMPTY overview")
                continue

            cols = list(df.columns)
            row = df.to_dicts()[0]
            print(f"{sym}: cols={cols}")
            print(f"  industry={row.get('industry', 'N/A')}")
            print(f"  sector={row.get('sector', 'N/A')}")

            async with GraphBuilder.from_settings(settings.falkordb) as b:
                await b.upsert_companies(df)
                await b.upsert_sector_industry(df)
                print(f"  → upserted sector/industry")

        except Exception as exc:
            print(f"{sym}: ERROR: {exc}")

    # Now generate competitors
    async with GraphBuilder.from_settings(settings.falkordb) as b:
        await b.upsert_competes_with()
        print("→ COMPETES_WITH generated")


asyncio.run(main())
