"""Quick ingestion of 5 companies for verification, skipping macro."""
import asyncio, sys
sys.path.insert(0, 'src')

from ourgraph.config import AppSettings
from ourgraph.db.falkordb import build_falkordb_client
from ourgraph.graph.builder import GraphBuilder
from ourgraph.ingest.pipeline import Pipeline

SYMBOLS = ['VIC', 'VCB', 'HPG', 'FPT', 'VNM']

async def main():
    settings = AppSettings()
    pipeline = Pipeline(settings)

    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        await builder.ensure_indices()
        
        # Step 1: Ingest company overviews (creates Company nodes with sector/industry)
        print("Step 1: Ingesting company overviews...")
        await pipeline._ingest_companies(builder, SYMBOLS)
        
        # Step 2: Build name-to-symbol map from graph
        name_to_symbol = await pipeline._build_name_to_symbol_map(builder)
        print(f"Name-to-symbol map: {len(name_to_symbol)} entries")
        
        # Step 3: Full per-symbol ingestion (financials, officers, subs, shareholders, KBS)
        for i, sym in enumerate(SYMBOLS, 1):
            print(f"\n[{i}/5] Ingesting {sym}...")
            try:
                await pipeline._ingest_symbol(builder, sym, name_to_symbol)
                print(f"  {sym}: DONE")
            except Exception as e:
                print(f"  {sym}: ERROR - {e}")
        
        # Step 4: Deduplicate + COMPETES_WITH
        print("\nStep 4: Deduplication + competition edges...")
        dedupe_stats = await builder.deduplicate_nodes()
        print(f"  Dedup: {dedupe_stats}")
        await builder.upsert_competes_with()
        
    print("\n=== All done ===")

asyncio.run(main())
