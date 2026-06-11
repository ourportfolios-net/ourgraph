"""Add cross-ticker relationships and verify export."""
import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.graph.queries import GraphQueries
from ourgraph.graph.schema import NodeLabel, Prop, RelType


async def main():
    settings = get_settings()

    # Add VHM → VIC subsidiary relationship
    async with GraphBuilder.from_settings(settings.falkordb) as b:
        await b._run(
            f"MATCH (a:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: 'VHM'}}), "
            f"(b:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: 'VIC'}})"
            f"MERGE (a)-[:{RelType.SUBSIDIARY_OF}]->(b)",
        )
        print("VHM → VIC subsidiary link created")

    # Verify export for HPG
    async with GraphQueries.from_settings(settings.falkordb) as q:
        data = await q.export_graph_json(symbol="HPG")
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        company_nodes = [
            n for n in nodes
            if n.get("labels", [""])[0] == "Company"
        ]
        comp_syms = [
            n.get("properties", {}).get("symbol", "?")
            for n in company_nodes
        ]
        print(f"\nHPG ego-net: {len(nodes)} nodes, {len(edges)} edges")
        print(f"Companies: {comp_syms}")

        for e in edges:
            rel = e.get("relationship", "?")
            src = e.get("source", "?")
            tgt = e.get("target", "?")
            print(f"  {src} -[{rel}]-> {tgt}")


asyncio.run(main())
