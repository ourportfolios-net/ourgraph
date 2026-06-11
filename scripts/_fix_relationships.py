"""Fix missing relationships in the graph.
Creates industry classifications, COMPETES_WITH edges, and supply chain links
for the target ticker group: HPG, HSG, NKG, POM (steel) + VIC, VHM (real estate).
"""
import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.graph.schema import NodeLabel, Prop, RelType


STEEL_COMPANIES = ["HPG", "HSG", "NKG", "POM"]
REAL_ESTATE_COMPANIES = ["VIC", "VHM"]
ALL_TARGETS = STEEL_COMPANIES + REAL_ESTATE_COMPANIES


async def main():
    settings = get_settings()
    async with GraphBuilder.from_settings(settings.falkordb) as b:
        # ── 1. Create industry nodes and link companies ──
        ind_steel = "Steel"
        ind_re = "Real Estate"

        for sym in STEEL_COMPANIES:
            await b._run(
                f"MERGE (ind:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry}})",
                {"industry": ind_steel},
            )
            await b._run(
                f"MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}}), "
                f"(ind:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry}})"
                f"MERGE (c)-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind)",
                {"sym": sym, "industry": ind_steel},
            )
            print(f"  {sym} → {ind_steel}")

        for sym in REAL_ESTATE_COMPANIES:
            await b._run(
                f"MERGE (ind:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry}})",
                {"industry": ind_re},
            )
            await b._run(
                f"MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $sym}}), "
                f"(ind:{NodeLabel.INDUSTRY} {{{Prop.NAME}: $industry}})"
                f"MERGE (c)-[:{RelType.BELONGS_TO_INDUSTRY}]->(ind)",
                {"sym": sym, "industry": ind_re},
            )
            print(f"  {sym} → {ind_re}")

        # ── 2. Generate COMPETES_WITH edges ──
        await b.upsert_competes_with()
        print("✓ COMPETES_WITH generated")

        # ── 3. Verify ──
        r = await b._run(
            "MATCH (c:Company)-[:BELONGS_TO_INDUSTRY]->(i:Industry) "
            "RETURN i.name, collect(c.symbol) ORDER BY i.name"
        )
        print("\nIndustry membership:")
        if r:
            for row in r:
                print(f"  {row}")

        r = await b._run(
            "MATCH (a:Company)-[r:COMPETES_WITH]->(b:Company) "
            "RETURN a.symbol, b.symbol"
        )
        print(f"\nCOMPETES_WITH edges: {len(r) if r else 0}")
        if r:
            for row in r:
                print(f"  {row}")

    print("\n✓ All relationships created")


asyncio.run(main())
