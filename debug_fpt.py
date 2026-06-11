"""Debug FPT subsidiary ingestion."""
import asyncio, sys, logging
sys.path.insert(0, 'src')
logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')

from ourgraph.config import AppSettings
from ourgraph.ingest.pipeline import Pipeline
from falkordb import FalkorDB
from ourgraph.graph.builder import GraphBuilder

async def main():
    settings = AppSettings()
    pipeline = Pipeline(settings)

    # Use localhost connection
    client = FalkorDB(host='localhost', port=6379)
    builder = GraphBuilder(client, 'ourgraph')

    # Build name_to_symbol
    all_symbols = await pipeline.resolve_symbols_for_progress()
    name_to_symbol = await pipeline._build_name_to_symbol_map(builder)
    
    # Try just FPT subsidiaries
    print("\n=== INGESTING FPT SUBSIDIARIES ===")
    count = await pipeline._ingest_symbol_subsidiaries(builder, 'FPT', name_to_symbol)
    print(f"Result: {count} subsidiaries ingested")

    # Check graph
    r = builder.query("MATCH (sub:Company)-[r:SUBSIDIARY_OF]->(c:Company {symbol:'FPT'}) RETURN sub.name, sub.symbol, r.ownership_percent").result_set
    print(f"\nFPT subsidiaries in graph: {len(r)}")
    for name, sym, pct in r:
        print(f"  {sym} ({name[:40]}) — {pct}%")

asyncio.run(main())
