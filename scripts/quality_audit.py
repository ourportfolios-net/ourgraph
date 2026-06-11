"""Graph quality audit script."""
import asyncio

from ourgraph.graph.builder import GraphBuilder
from ourgraph.config import get_settings


async def audit():
    settings = get_settings()
    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        # Check for duplicate companies by symbol
        print("=== Duplicate Companies by Symbol ===")
        rows = await builder.query_raw(
            "MATCH (c:Company) "
            "WITH c.symbol AS sym, collect(c) AS nodes "
            "WHERE sym IS NOT NULL AND size(nodes) > 1 "
            "RETURN sym, size(nodes) "
            "ORDER BY size(nodes) DESC LIMIT 10"
        )
        for row in rows:
            print(f"  {row[0]}: {row[1]} nodes")

        # Check for duplicate persons by name
        print("\n=== Duplicate Persons by Name ===")
        rows = await builder.query_raw(
            "MATCH (p:Person) "
            "WITH p.person_name AS name, collect(p) AS nodes "
            "WHERE name IS NOT NULL AND name <> '' AND size(nodes) > 1 "
            "RETURN name, size(nodes) "
            "ORDER BY size(nodes) DESC LIMIT 10"
        )
        for row in rows:
            print(f"  {row[0]}: {row[1]} nodes")

        # Check subsidiaries - how many have ownership_percent?
        print("\n=== Subsidiary Edges ===")
        rows = await builder.query_raw(
            "MATCH (c1:Company)-[r:SUBSIDIARY_OF]->(c2:Company) "
            "RETURN count(r) AS total, "
            "count(r.ownership_percent) AS with_pct, "
            "count(CASE WHEN r.ownership_percent > 0 THEN 1 END) AS with_valid_pct"
        )
        if rows:
            print(f"  Total: {rows[0][0]}, with ownership_pct: {rows[0][1]}, with valid pct: {rows[0][2]}")

        # Check shareholders - corporate vs individual
        print("\n=== Shareholder Types ===")
        rows = await builder.query_raw(
            "MATCH (holder)-[r:HOLDS_STAKE_IN]->(c:Company) "
            "WITH holder, count(r) AS cnt "
            "RETURN labels(holder)[0] AS holder_type, count(cnt) AS num "
            "ORDER BY num DESC"
        )
        for row in rows:
            print(f"  {row[0]}: {row[1]}")

        # Check COMPETES_WITH edges
        print("\n=== Competition Edges ===")
        rows = await builder.query_raw(
            "MATCH (a:Company)-[r:COMPETES_WITH]->(b:Company) "
            "RETURN count(r)"
        )
        print(f"  Total COMPETES_WITH edges: {rows[0][0] if rows else 0}")

        # Check for missing sector/industry links
        print("\n=== Missing Sector/Industry Links ===")
        rows = await builder.query_raw(
            "MATCH (c:Company) "
            "OPTIONAL MATCH (c)-[:BELONGS_TO]->(s:Sector) "
            "OPTIONAL MATCH (c)-[:BELONGS_TO_INDUSTRY]->(i:Industry) "
            "WITH c, s, i "
            "WHERE s IS NULL OR i IS NULL "
            "RETURN count(c) AS missing_links"
        )
        print(f"  Companies missing sector or industry: {rows[0][0] if rows else 'unknown'}")

        # Check for companies with no relationships at all
        print("\n=== Isolated Companies (no relationships) ===")
        rows = await builder.query_raw(
            "MATCH (c:Company) "
            "WHERE NOT (c)--() "
            "RETURN count(c)"
        )
        print(f"  Isolated companies: {rows[0][0] if rows else 0}")

        # Sample of subsidiaries with issues
        print("\n=== Sample Subsidiary Issues ===")
        rows = await builder.query_raw(
            "MATCH (child:Company)-[r:SUBSIDIARY_OF]->(parent:Company) "
            "WHERE r.ownership_percent IS NULL OR r.ownership_percent = 0 "
            "RETURN child.symbol, parent.symbol, r.ownership_percent "
            "LIMIT 10"
        )
        print(f"  Subsidiaries with missing/zero ownership_percent:")
        for row in rows:
            print(f"    {row[0]} -> {row[1]}: {row[2]}")

        # Companies with most subsidiaries
        print("\n=== Top 10 Companies by Subsidiary Count ===")
        rows = await builder.query_raw(
            "MATCH (child:Company)-[:SUBSIDIARY_OF]->(parent:Company) "
            "RETURN parent.symbol, count(child) AS num_subs "
            "ORDER BY num_subs DESC LIMIT 10"
        )
        for row in rows:
            print(f"  {row[0]}: {row[1]} subsidiaries")


if __name__ == "__main__":
    asyncio.run(audit())
