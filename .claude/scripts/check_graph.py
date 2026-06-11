"""Quick script to check graph state."""
import asyncio

from ourgraph.config import get_settings
from ourgraph.db.falkordb import build_falkordb_client


async def main():
    settings = get_settings()
    c = build_falkordb_client(settings.falkordb)
    g = c.select_graph(settings.falkordb.graph_name)

    # Check total nodes
    result = await g.ro_query("MATCH (n) RETURN count(n)")
    print("Total nodes:", result.result_set[0][0] if result.result_set else 0)

    # Check Company nodes
    result = await g.ro_query("MATCH (c:Company) RETURN count(c)")
    print("Company nodes:", result.result_set[0][0] if result.result_set else 0)

    # Check HOLDS_STAKE_IN edges
    result = await g.ro_query(
        "MATCH ()-[r:HOLDS_STAKE_IN]->() RETURN count(r)",
    )
    print("HOLDS_STAKE_IN edges:", result.result_set[0][0] if result.result_set else 0)

    # Check Company→Company HOLDS_STAKE_IN edges
    result = await g.ro_query(
        """
        MATCH (holder:Company)-[r:HOLDS_STAKE_IN]->(target:Company)
        RETURN holder.symbol, target.symbol, r.stake_percent
        LIMIT 10
        """,
    )
    print("Company→Company HOLDS_STAKE_IN edges:", result.result_set[:5] if result.result_set else "None")

    # Check cross-shareholding (cycles)
    result = await g.ro_query(
        """
        MATCH (a:Company)-[r1:HOLDS_STAKE_IN]->(b:Company)
              -[r2:HOLDS_STAKE_IN]->(a)
        RETURN a.symbol, b.symbol, r1.stake_percent, r2.stake_percent
        LIMIT 10
        """,
    )
    print("Cross-shareholding pairs:", result.result_set or "None")

    # Check Person nodes
    result = await g.ro_query("MATCH (p:Person) RETURN count(p)")
    print("Person nodes:", result.result_set[0][0] if result.result_set else 0)

    await c.aclose()


if __name__ == "__main__":
    asyncio.run(main())
