"""Verify POM-VNM fix and check export."""
import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.queries import GraphQueries

async def main():
    s = get_settings()
    async with GraphQueries.from_settings(s.falkordb) as q:
        # Verify POM-VNM no longer has SUBSIDIARY_OF
        r = await q._ro(
            "MATCH (a:Company {symbol: 'POM'})-[r:SUBSIDIARY_OF]->(b:Company {symbol: 'VNM'}) "
            "RETURN count(r)"
        )
        print(f'POM -[SUBSIDIARY_OF]-> VNM: {r[0][0] if r else 0}')

        # Check HOLDS_STAKE_IN from POM
        r = await q._ro(
            "MATCH (a:Company {symbol: 'POM'})-[r:HOLDS_STAKE_IN]->(b:Company) "
            "RETURN b.symbol, r.stake_percent"
        )
        print(f'POM holds stake in:')
        for row in (r or []):
            print(f'  {row}')

        # Check HOLDS_STAKE_IN from parent companies to VNM
        r = await q._ro(
            "MATCH (a:Company)-[r:HOLDS_STAKE_IN]->(b:Company {symbol: 'VNM'}) "
            "RETURN a.symbol, r.stake_percent"
        )
        print(f'\nCompanies holding VNM:')
        for row in (r or []):
            print(f'  {row}')

        # Export POM ego-net
        data = await q.export_graph_json(symbol="POM")
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        comp_syms = [
            n.get("properties", {}).get("symbol", "?")
            for n in nodes if n.get("labels", [""])[0] == "Company"
        ]
        print(f'\nPOM ego-net: {len(nodes)} nodes, {len(edges)} edges')
        print(f'Companies: {comp_syms}')
        for e in edges:
            rel = e.get("relationship", "?")
            src = e.get("source", "?")
            tgt = e.get("target", "?")
            print(f'  {src} -[{rel}]-> {tgt}')

asyncio.run(main())