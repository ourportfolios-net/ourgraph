"""Diagnose the POM-VNM relationship in the graph."""
import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.queries import GraphQueries

async def main():
    s = get_settings()
    async with GraphQueries.from_settings(s.falkordb) as q:
        # Check all edges between POM and VNM
        r = await q._ro(
            "MATCH (a:Company {symbol: 'POM'})-[r]-(b:Company {symbol: 'VNM'}) "
            "RETURN type(r), properties(r), a.symbol, b.symbol"
        )
        print('POM ↔ VNM relationships:')
        for row in r:
            print(f'  {row}')

        # Check if VNM exists
        r = await q._ro("MATCH (c:Company {symbol: 'VNM'}) RETURN c.symbol, c.name")
        print(f'\nVNM: {r}')

        # Check HOLDS_STAKE_IN edges involving POM
        r = await q._ro(
            "MATCH (a:Company {symbol: 'POM'})-[r:HOLDS_STAKE_IN]->(b:Company) "
            "RETURN b.symbol, b.name, r.stake_percent"
        )
        print(f'\nPOM holds stake in:')
        for row in r:
            print(f'  {row}')

        # Check HOLDS_STAKE_IN edges going into POM
        r = await q._ro(
            "MATCH (a)-[r:HOLDS_STAKE_IN]->(b:Company {symbol: 'POM'}) "
            "RETURN labels(a), a.symbol, r.stake_percent"
        )
        print(f'\nWho holds stake in POM:')
        for row in r:
            print(f'  {row}')

asyncio.run(main())