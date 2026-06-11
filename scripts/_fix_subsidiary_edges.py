"""Fix existing wrong SUBSIDIARY_OF edges (minority stakes)."""
import asyncio
from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.graph.schema import NodeLabel, Prop, RelType


async def main():
    settings = get_settings()
    async with GraphBuilder.from_settings(settings.falkordb) as b:
        # 1. Find all SUBSIDIARY_OF edges with ownership < 50%
        r = await b._run(
            f"MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY}) "
            f"WHERE r.{Prop.OWNERSHIP_PERCENT} < 50 "
            f"RETURN child.{Prop.SYMBOL}, parent.{Prop.SYMBOL}, r.{Prop.OWNERSHIP_PERCENT}, r.{Prop.RELATION_TYPE}"
        )
        wrong_edges = list(r) if r else []
        print(f"Minority SUBSIDIARY_OF edges to fix: {len(wrong_edges)}")
        for row in wrong_edges:
            print(f"  {row}")

        # 2. Convert each: delete SUBSIDIARY_OF, create HOLDS_STAKE_IN
        for row in wrong_edges:
            child_sym = row[0]
            parent_sym = row[1]
            pct = float(row[2]) if row[2] else 0
            rel_type = str(row[3]) if row[3] else ""

            # Delete wrong SUBSIDIARY_OF
            await b._run(
                f"MATCH (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $child}})-"
                f"[r:{RelType.SUBSIDIARY_OF}]->"
                f"(parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent}})"
                f"DELETE r",
                {"child": child_sym, "parent": parent_sym},
            )

            # Create HOLDS_STAKE_IN with correct direction (parent holds stake in child)
            await b._run(
                f"MATCH (parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $parent}}), "
                f"(child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $child}})"
                f"MERGE (parent)-[r:{RelType.HOLDS_STAKE_IN}]->(child) "
                f"SET r.{Prop.STAKE_PERCENT} = $pct, "
                f"r.{Prop.RELATION_TYPE} = $rel_type",
                {"parent": parent_sym, "child": child_sym, "pct": pct, "rel_type": rel_type},
            )
            print(f"  Fixed: {parent_sym} -[HOLDS_STAKE_IN]-> {child_sym} ({pct}%)")

        # 3. Verify
        r = await b._run(
            f"MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY}) "
            f"WHERE r.{Prop.OWNERSHIP_PERCENT} < 50 "
            f"RETURN count(r)"
        )
        remaining = int(r[0][0]) if r else 0
        print(f"\nRemaining wrong SUBSIDIARY_OF edges: {remaining}")
        print("Done.")


asyncio.run(main())