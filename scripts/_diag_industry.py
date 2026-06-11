import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.queries import GraphQueries

async def main():
    s = get_settings()
    async with GraphQueries.from_settings(s.falkordb) as q:
        # Check industry data for steel companies
        for sym in ['HPG', 'HSG', 'NKG', 'POM']:
            r = await q._ro(
                f"MATCH (c:Company {{symbol: '{sym}'}})-[:BELONGS_TO_INDUSTRY]->(i:Industry) RETURN i.name"
            )
            print(f'{sym} industry: {r[0][0] if r else "NONE"}')

        # Count companies with industry links
        r = await q._ro(
            'MATCH (c:Company)-[:BELONGS_TO_INDUSTRY]->(i:Industry) RETURN count(DISTINCT c)'
        )
        print(f'Companies with industry links: {r[0][0]}')

        # All industries
        r = await q._ro('MATCH (i:Industry) RETURN i.name ORDER BY i.name')
        print('Industries:', [row[0] for row in r])

asyncio.run(main())
