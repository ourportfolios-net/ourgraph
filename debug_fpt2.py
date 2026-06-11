"""Debug FPT subsidiaries - sync version."""
import sys, logging
sys.path.insert(0, 'src')
logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')

from falkordb import FalkorDB
from ourgraph.graph.builder import GraphBuilder
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher
from ourgraph.config import VnstockSettings

# Use sync builder (same as verification queries)
client = FalkorDB(host='localhost', port=6379)
builder = GraphBuilder(client, 'ourgraph')

# Get data
fetcher = VnstockFetcher(VnstockSettings())
df = fetcher.get_subsidiaries('FPT')

print(f"\nData: {len(df)} rows, cols={df.columns}")

# Now call upsert using a simple event loop
import asyncio

async def do_upsert():
    # Check parent
    r = await builder.query_raw("MATCH (c:Company {symbol:'FPT'}) RETURN count(c)")
    print(f"Parent check: {r}")
    
    # Manual upsert
    await builder.upsert_subsidiaries(df, 'FPT', {})
    
    # Verify
    r = await builder.query_raw("MATCH (sub:Company)-[r:SUBSIDIARY_OF]->(c:Company {symbol:'FPT'}) RETURN count(r)")
    print(f"After upsert: {r[0][0] if r else 'NO RESULT'} subsidiaries")

# The builder methods are async, need to use asyncio
# But builder was created with sync client...
# Let me just use raw sync queries instead
import hashlib
g = client.select_graph('ourgraph')

count = 0
for row in df.to_dicts():
    sub_name = row.get("name", "")
    if not sub_name:
        continue
    
    name_hash = hashlib.sha256(sub_name.encode()).hexdigest()[:8].upper()
    sub_code = f"SUB_{name_hash}"
    ownership_pct = float(row.get("ownership_percent") or 0)
    
    safe_name = sub_name.replace("'", "''")
    
    if ownership_pct >= 50:
        g.query(f"""
            MATCH (parent:Company {{symbol: 'FPT'}})
            MERGE (child:Company {{symbol: '{sub_code}'}})
            ON CREATE SET child.name = '{safe_name}',
                          child.company_type = 'subsidiary'
            MERGE (child)-[r:SUBSIDIARY_OF]->(parent)
            SET r.ownership_percent = {ownership_pct}
        """)
        count += 1

print(f"\nWritten {count} subsidiaries")
r = g.query("MATCH (sub:Company)-[r:SUBSIDIARY_OF]->(c:Company {symbol:'FPT'}) RETURN sub.name, sub.symbol, r.ownership_percent").result_set
print(f"Graph now has {len(r)} FPT subsidiaries:")
for name, sym, pct in r:
    print(f"  {sym}: {name} ({pct}%)")
