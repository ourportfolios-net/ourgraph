"""Systematic re-ingest of 5 companies via async path."""
import sys, logging
sys.path.insert(0, 'src')
logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')

from falkordb.asyncio import FalkorDB
from ourgraph.graph.builder import GraphBuilder, NodeLabel, Prop, RelType
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher
from ourgraph.config import VnstockSettings

SYMBOLS = ['VIC', 'VCB', 'HPG', 'FPT', 'VNM']

async def main():
    # Use explicit async client
    client = FalkorDB(host='localhost', port=6379)
    builder = GraphBuilder(client, 'ourgraph')
    await builder.ensure_indices()
    fetcher = VnstockFetcher(VnstockSettings())
    
    # Clear graph
    await builder.query_raw("MATCH (n) DETACH DELETE n")
    print("Graph cleared")
    
    # Step 1: Company overviews
    print("\n=== Company Overviews ===")
    name_to_symbol = {}
    for sym in SYMBOLS:
        df = fetcher.get_company_overview(sym)
        if not df.is_empty():
            await builder.upsert_companies(df)
            for row in df.to_dicts():
                n = (row.get('short_name') or row.get('company_name') or '').lower()
                if n:
                    name_to_symbol[n] = sym
            name_to_symbol[sym.lower()] = sym
            print(f"  {sym}: OK")
    
    # Step 2: Per-symbol data
    print("\n=== Per-Symbol ===")
    for sym in SYMBOLS:
        try:
            # Officers
            df = fetcher.get_officers(sym)
            if not df.is_empty():
                await builder.upsert_officers(df, sym)
                print(f"  {sym}: {len(df)} officers")
            
            # Subsidiaries
            df = fetcher.get_subsidiaries(sym)
            if not df.is_empty():
                await builder.upsert_subsidiaries(df, sym, name_to_symbol)
                print(f"  {sym}: {len(df)} subsidiaries")
            
            # Shareholders
            df = fetcher.get_shareholders(sym)
            if not df.is_empty():
                await builder.upsert_shareholders(df, sym, name_to_symbol)
                print(f"  {sym}: {len(df)} shareholders")
            
            # Financial statements
            df = fetcher.get_financial_statements(sym, 'quarterly', 4)
            if not df.is_empty():
                await builder.upsert_financial_statements(df)
                print(f"  {sym}: {len(df)} financials")
            
        except Exception as e:
            print(f"  {sym}: ERROR - {e}")
            logging.exception(sym)
    
    # Step 3: Post-processing
    print("\n=== Post-processing ===")
    stats = await builder.deduplicate_nodes()
    print(f"  Dedup: {stats}")
    await builder.upsert_competes_with()
    print(f"  COMPETES_WITH done")
    
    # Step 4: Verify
    print("\n=== Verification ===")
    for sym in SYMBOLS:
        r = await builder.query_raw(f"MATCH (c:Company {{symbol:'{sym}'}}) RETURN c.name")
        off = await builder.query_raw(f"MATCH (p:Person)-[r:IS_OFFICER]->(c:Company {{symbol:'{sym}'}}) RETURN count(r)")
        sub = await builder.query_raw(f"MATCH (sub:Company)-[r:SUBSIDIARY_OF]->(c:Company {{symbol:'{sym}'}}) RETURN count(r)")
        shr = await builder.query_raw(f"MATCH (h)-[r:HOLDS_STAKE_IN]->(c:Company {{symbol:'{sym}'}}) RETURN count(r)")
        print(f"  {sym}: {off[0][0] if off else 0} off, {sub[0][0] if sub else 0} sub, {shr[0][0] if shr else 0} shr")
    
    # Role edges + Sector/Industry
    bm = await builder.query_raw("MATCH ()-[r:IS_BOARD_MEMBER]->() RETURN count(r)")
    ex = await builder.query_raw("MATCH ()-[r:IS_EXECUTIVE]->() RETURN count(r)")
    comp = await builder.query_raw("MATCH ()-[r:COMPETES_WITH]->() RETURN count(r)")
    sec = await builder.query_raw("MATCH (n:Sector) RETURN count(n)")
    ind = await builder.query_raw("MATCH (n:Industry) RETURN count(n)")
    print(f"\n  Board: {bm[0][0]}, Exec: {ex[0][0]}, Competes: {comp[0][0]}")
    print(f"  Sector: {sec[0][0]}, Industry: {ind[0][0]}")

import asyncio
asyncio.run(main())
