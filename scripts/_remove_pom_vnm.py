"""Remove POM-VNM relationship (factually incorrect) and verify."""
import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder


async def main():
    settings = get_settings()
    async with GraphBuilder.from_settings(settings.falkordb) as b:
        # Delete any relationship between POM and VNM
        await b._run(
            "MATCH (a:Company {symbol: 'POM'})-[r]-(b:Company {symbol: 'VNM'}) "
            "DELETE r"
        )
        print("Removed POM ↔ VNM relationships")

        # Verify
        r = await b._run(
            "MATCH (a:Company {symbol: 'POM'})-[r]-(b:Company {symbol: 'VNM'}) "
            "RETURN count(r)"
        )
        print(f"Remaining POM-VNM edges: {r[0][0] if r else 0}")

    print("Done.")


asyncio.run(main())