"""Comprehensive 5-company ingestion with all pipeline steps."""
import sys
sys.path.insert(0, 'src')

from falkordb.asyncio import FalkorDB
from ourgraph.graph.builder import GraphBuilder
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher
from ourgraph.config import VnstockSettings

SYMBOLS = ['VIC', 'VCB', 'HPG', 'FPT', 'VNM']

async def main():
    client = FalkorDB(host='localhost', port=6379)
    builder = GraphBuilder(client, 'ourgraph')
    await builder.ensure_indices()
    fetcher = VnstockFetcher(VnstockSettings())
    
    # Clear
    await builder.query_raw("MATCH (n) DETACH DELETE n")
    print("Cleared")
    
    # Step 1: Company overviews + sector/industry
    name_to_symbol = {}
    for sym in SYMBOLS:
        df = fetcher.get_company_overview(sym)
        if not df.is_empty():
            await builder.upsert_companies(df)
            await builder.upsert_sector_industry(df)
            for row in df.to_dicts():
                n = (row.get('short_name') or row.get('company_name') or '').lower()
                if n: name_to_symbol[n] = sym
                name_to_symbol[sym.lower()] = sym
            print(f"  {sym}: company OK")
    
    # Step 2: Per-symbol (officers + roles, subsidiaries, shareholders, financials)
    total = {sym: {'off': 0, 'sub': 0, 'shr': 0, 'fin': 0, 'roles': 0} for sym in SYMBOLS}
    
    for sym in SYMBOLS:
        try:
            # Officers + roles
            df_off = fetcher.get_officers(sym)
            if not df_off.is_empty():
                await builder.upsert_officers(df_off, sym)
                await builder.upsert_officer_roles(df_off, sym)
                total[sym]['off'] = len(df_off)
            
            # Subsidiaries
            df_sub = fetcher.get_subsidiaries(sym)
            if not df_sub.is_empty():
                await builder.upsert_subsidiaries(df_sub, sym, name_to_symbol)
                total[sym]['sub'] = len(df_sub)
            
            # Shareholders
            df_shr = fetcher.get_shareholders(sym)
            if not df_shr.is_empty():
                await builder.upsert_shareholders(df_shr, sym, name_to_symbol)
                total[sym]['shr'] = len(df_shr)
            
            # Financials (income statement)
            try:
                df_is = fetcher.get_income_statement(sym, 'quarter')
                if not df_is.is_empty():
                    await builder.upsert_financial_statement(df_is)
                    total[sym]['fin'] = len(df_is)
            except Exception as e:
                print(f"    fin ERROR: {e}")
            
            print(f"  {sym}: {total[sym]['off']} off, {total[sym]['sub']} sub, {total[sym]['shr']} shr, {total[sym]['fin']} fin")
        except Exception as e:
            print(f"  {sym}: OUTER ERROR - {e}")
    
    # Step 3: Post-processing
    await builder.deduplicate_nodes()
    await builder.upsert_competes_with()
    print("\nPost-processing done")
    
    return total

import asyncio
asyncio.run(main())
