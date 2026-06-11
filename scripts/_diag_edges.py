import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.queries import GraphQueries

async def main():
    s = get_settings()
    async with GraphQueries.from_settings(s.falkordb) as q:
        # All inter-company edge types
        r = await q._ro(
            'MATCH (a:Company)-[r]->(b:Company) '
            'RETURN DISTINCT type(r), count(*) ORDER BY count(*) DESC'
        )
        print('Company->Company edges:')
        for row in r:
            print(f'  {row[0]}: {row[1]}')

        # Check target symbols exist
        for sym in ['HSG', 'NKG', 'POM', 'VIC', 'VHM']:
            r = await q._ro(
                f"MATCH (c:Company {{symbol: '{sym}'}}) RETURN c.symbol, c.name"
            )
            print(f'{sym}: {r[0] if r else "MISSING"}')

        # HPG's neighborhood summary
        r = await q._ro(
            "MATCH (c:Company {symbol: 'HPG'})-[r]-(n) "
            "RETURN DISTINCT labels(n), type(r), count(*) "
            "ORDER BY count(*) DESC"
        )
        print('\nHPG neighborhood:')
        for row in r:
            print(f'  {row[0]} -[{row[1]}]- count={row[2]}')

asyncio.run(main())
