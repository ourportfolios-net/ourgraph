"""Hidden relationship discovery engine.

Discovers implicit relationships in the knowledge graph:
  - Cross-shareholdings (mutual stake ownership)
  - Multi-level subsidiary chains
  - Shared insider networks
  - Supply chain inference (industry-based)
  - Influence networks (conglomerates, indirect control)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ourgraph.constants import SUPPLY_CHAIN_MAP

if TYPE_CHECKING:
    from ourgraph.graph.queries import GraphQueries

logger = logging.getLogger(__name__)

# Minimum thresholds for discovery
_MIN_INDIRECT_OWNERSHIP_PCT = 5.0
_MIN_CROSS_INFLUENCE_DELTA = 5.0


class GraphDiscovery:
    """Discover hidden relationships in the knowledge graph.

    All methods are async and return lists of dicts with discovery metadata
    (relationship type, entities, confidence, explanation).
    """

    def __init__(self, queries: GraphQueries) -> None:
        self._queries = queries

    # ------------------------------------------------------------------
    # 1. Cross-shareholdings
    # ------------------------------------------------------------------

    async def discover_cross_shareholdings(
        self,
        min_stake_pct: float = 1.0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find pairs of companies that hold stakes in each other."""
        rows = await self._queries.query_raw(
            """
            MATCH (a:Company)-[r1:HOLDS_STAKE_IN]->(b:Company)
                  -[r2:HOLDS_STAKE_IN]->(a)
            WHERE r1.stake_percent >= $min_pct
              AND r2.stake_percent >= $min_pct
            RETURN a.symbol AS a_sym,
                   a.name AS a_name,
                   b.symbol AS b_sym,
                   b.name AS b_name,
                   r1.stake_percent AS a_holds_b,
                   r2.stake_percent AS b_holds_a
            ORDER BY a_holds_b + b_holds_a DESC
            LIMIT $limit
            """,
            {"min_pct": min_stake_pct, "limit": limit},
        )
        results = []
        for row in rows:
            explanation = (
                f"{row[0]} holds {row[4]:.1f}% of {row[2]}, "
                f"{row[2]} holds {row[5]:.1f}% of {row[0]}"
            )
            results.append(
                {
                    "type": "cross_shareholding",
                    "source_symbol": row[0],
                    "source_name": row[1],
                    "target_symbol": row[2],
                    "target_name": row[3],
                    "a_holds_b_pct": row[4],
                    "b_holds_a_pct": row[5],
                    "explanation": explanation,
                },
            )
        return results

    # ------------------------------------------------------------------
    # 2. Multi-level subsidiary chains
    # ------------------------------------------------------------------

    async def discover_subsidiary_chains(
        self,
        max_depth: int = 5,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find ownership chains (A owns B owns C owns ...)."""
        depth = max(2, min(max_depth, 10))
        rows = await self._queries.query_raw(
            f"""
            MATCH path = (top:Company)<-[:SUBSIDIARY_OF*1..{depth}]-(leaf:Company)
            OPTIONAL MATCH (leaf)<-[:SUBSIDIARY_OF]-(child:Company)
            WITH path, leaf, child, length(path) AS chain_len
            WHERE child IS NULL
            ORDER BY chain_len DESC
            LIMIT $limit
            RETURN [n IN nodes(path) | n.symbol] AS chain,
                   [r IN relationships(path) | r.ownership_percent] AS ownership_pcts,
                   chain_len
            """,
            {"limit": limit},
        )
        results = []
        for row in rows:
            chain = list(row[0])
            pcts = list(row[1])
            chain_len = int(row[2])
            top = chain[0]
            bottom = chain[-1]
            effective_pct = self._calc_effective_ownership(pcts)
            explanation = (
                f"Ownership chain ({chain_len} levels): "
                f"{' → '.join(chain)} "
                f"[effective ownership: {effective_pct:.1f}%]"
            )
            results.append(
                {
                    "type": "subsidiary_chain",
                    "top_symbol": top,
                    "bottom_symbol": bottom,
                    "chain": chain,
                    "ownership_pcts": pcts,
                    "effective_ownership_pct": effective_pct,
                    "chain_length": chain_len,
                    "explanation": explanation,
                },
            )
        return results

    @staticmethod
    def _calc_effective_ownership(pcts: list) -> float:
        """Calculate effective ownership through a chain (product of percentages)."""
        effective = 100.0
        for p in pcts:
            if p is not None:
                effective *= float(p) / 100.0
        return effective

    # ------------------------------------------------------------------
    # 3. Shared insider networks
    # ------------------------------------------------------------------

    async def discover_shared_insiders(
        self,
        min_companies: int = 2,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find people connected to multiple companies via officer or stake roles.

        Includes influence scoring based on position seniority and stake size.
        """
        # Use two separate queries instead of OPTIONAL MATCH + collect(map)
        # to avoid FalkorDB alias-resolution errors with composite map aggregations.
        rows_officers = await self._queries.query_raw(
            """
            MATCH (p:Person)-[:IS_OFFICER]->(c:Company)
            RETURN p.person_name AS person, c.symbol AS company, 'officer' AS role
            """,
        )
        rows_holders = await self._queries.query_raw(
            """
            MATCH (p:Person)-[:HOLDS_STAKE_IN]->(c:Company)
            RETURN p.person_name AS person, c.symbol AS company, 'shareholder' AS role
            """,
        )

        # Aggregate: person → set of (company, role)
        person_roles: dict[str, dict[str, set[str]]] = {}
        for row in rows_officers:
            name = row[0]
            company = row[1]
            person_roles.setdefault(name, {}).setdefault(company, set()).add("officer")
        for row in rows_holders:
            name = row[0]
            company = row[1]
            person_roles.setdefault(name, {}).setdefault(company, set()).add(
                "shareholder",
            )

        # Filter to people at 2+ companies, compute influence score
        results: list[dict[str, Any]] = []
        for person, company_map in person_roles.items():
            companies = list(company_map.keys())
            n_companies = len(companies)
            if n_companies < min_companies:
                continue
            # Flatten roles per company; one entry per (company, role_type)
            flat_roles: list[str] = []
            for comp in companies:
                for role in company_map[comp]:
                    flat_roles.append(role)
            influence_score = self._score_influence(flat_roles, n_companies)
            explanation = (
                f"{person} is connected to {n_companies} companies: "
                f"{', '.join(companies)} [influence: {influence_score:.1f}]"
            )
            results.append(
                {
                    "type": "shared_insider",
                    "person": person,
                    "companies": companies,
                    "roles": flat_roles,
                    "n_companies": n_companies,
                    "influence_score": influence_score,
                    "explanation": explanation,
                },
            )

        # Sort by n_companies descending, apply limit
        results.sort(key=lambda x: x["n_companies"], reverse=True)
        return results[:limit]

    @staticmethod
    def _score_influence(role_list: list, n_companies: int) -> float:
        """Score influence based on role types and company count.

        Board memberships score higher than pure shareholdings.
        """
        officer_count = sum(1 for r in role_list if r == "officer")
        shareholder_only = sum(1 for r in role_list if r == "shareholder")
        return float(officer_count * 2.0 + shareholder_only * 0.5 + n_companies * 0.5)

    async def discover_competitive_insiders(
        self,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find people who are insiders at competing companies.

        These represent potential conflicts of interest.
        """
        rows = await self._queries.query_raw(
            """
            MATCH (p:Person)-[r:IS_OFFICER|HOLDS_STAKE_IN]->(a:Company)
            MATCH (a)-[:COMPETES_WITH]->(b:Company)
            MATCH (p)-[r2:IS_OFFICER|HOLDS_STAKE_IN]->(b)
            RETURN DISTINCT p.person_name AS person,
                   a.symbol AS company_a, b.symbol AS company_b,
                   type(r) AS role_a, type(r2) AS role_b
            LIMIT $limit
            """,
            {"limit": limit},
        )
        results = []
        for row in rows:
            explanation = f"{row[0]} has roles at competitors {row[1]} and {row[2]}"
            results.append(
                {
                    "type": "competitive_insider",
                    "person": row[0],
                    "company_a": row[1],
                    "company_b": row[2],
                    "role_a": row[3],
                    "role_b": row[4],
                    "explanation": explanation,
                },
            )
        return results

    # ------------------------------------------------------------------
    # 4. Supply chain inference
    # ------------------------------------------------------------------

    async def infer_supply_chain(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Infer potential supplier-customer relationships based on industry links.

        Uses the ``SUPPLY_CHAIN_MAP`` to identify which industries typically
        supply which other industries, then suggests relationships between
        companies in those industries.
        """
        rows = await self._queries.query_raw(
            """
            MATCH (supplier:Company)-[:BELONGS_TO_INDUSTRY]->(si:Industry)
            MATCH (customer:Company)-[:BELONGS_TO_INDUSTRY]->(ci:Industry)
            WHERE supplier.symbol <> customer.symbol
            WHERE NOT (supplier)-[:COMPETES_WITH]-(customer)
              AND NOT (supplier)-[:SUBSIDIARY_OF]-(customer)
            RETURN supplier.symbol AS supplier_sym,
                   supplier.name AS supplier_name,
                   si.name AS supplier_industry,
                   customer.symbol AS customer_sym,
                   customer.name AS customer_name,
                   ci.name AS customer_industry,
                   supplier.market_cap AS supplier_mcap,
                   customer.market_cap AS customer_mcap
            LIMIT 5000
            """,
        )

        # Match against supply chain map
        matched: list[dict[str, Any]] = []
        for row in rows:
            sup_industry = row[2]
            cust_industry = row[5]
            if self._is_supply_chain_pair(sup_industry, cust_industry):
                explanation = (
                    f"{row[0]} ({sup_industry}) may supply {row[3]} ({cust_industry})"
                )
                matched.append(
                    {
                        "type": "supply_chain",
                        "supplier_symbol": row[0],
                        "supplier_name": row[1],
                        "supplier_industry": sup_industry,
                        "customer_symbol": row[3],
                        "customer_name": row[4],
                        "customer_industry": cust_industry,
                        "supplier_market_cap": row[6],
                        "customer_market_cap": row[7],
                        "explanation": explanation,
                    },
                )
                if len(matched) >= limit:
                    break

        return matched

    @staticmethod
    def _is_supply_chain_pair(supplier_industry: str, customer_industry: str) -> bool:
        """Check if one industry typically supplies another."""
        sup_lower = supplier_industry.lower()
        cust_lower = customer_industry.lower()

        for prod_industry, customers in SUPPLY_CHAIN_MAP.items():
            if prod_industry.lower() in sup_lower or sup_lower in prod_industry.lower():
                for cust in customers:
                    if cust.lower() in cust_lower or cust_lower in cust.lower():
                        return True
        return False

    # ------------------------------------------------------------------
    # 5. Influence network mapping
    # ------------------------------------------------------------------

    async def map_influence_networks(
        self,
        min_subsidiaries: int = 3,
        min_board_interlock: int = 2,
    ) -> dict[str, list[dict[str, Any]]]:
        """Map all hidden influence relationships.

        Returns a dict with keys: ``conglomerates``, ``indirect_control``,
        ``board_interlocks``, ``cross_influence``.
        """
        return {
            "conglomerates": await self._detect_conglomerates(min_subsidiaries),
            "indirect_control": await self._calculate_indirect_ownership(),
            "board_interlocks": await self._find_board_interlocks(min_board_interlock),
            "cross_influence": await self._analyze_cross_shareholding_influence(),
        }

    async def _detect_conglomerates(
        self,
        min_subsidiaries: int = 3,
    ) -> list[dict[str, Any]]:
        """Find companies with many subsidiaries."""
        rows = await self._queries.query_raw(
            """
            MATCH (parent:Company)<-[:SUBSIDIARY_OF]-(child:Company)
            WITH parent, count(child) AS n_subs,
                 collect(child.symbol) AS subsidiaries,
                 collect(child.name) AS sub_names
            WHERE n_subs >= $min_subs
            RETURN parent.symbol AS symbol,
                   parent.name AS name,
                   n_subs,
                   subsidiaries,
                   sub_names
            ORDER BY n_subs DESC
            """,
            {"min_subs": min_subsidiaries},
        )
        results = []
        for row in rows:
            explanation = (
                f"{row[0]} controls {row[2]} subsidiaries: {', '.join(row[3])}"
            )
            results.append(
                {
                    "type": "conglomerate",
                    "parent_symbol": row[0],
                    "parent_name": row[1],
                    "n_subsidiaries": int(row[2]),
                    "subsidiaries": list(row[3]),
                    "sub_names": list(row[4]),
                    "explanation": explanation,
                },
            )
        return results

    async def _calculate_indirect_ownership(
        self,
    ) -> list[dict[str, Any]]:
        """Find A → B → C chains where A indirectly controls C."""
        rows = await self._queries.query_raw(
            """
            MATCH (mid:Company)-[:SUBSIDIARY_OF]->(top:Company)
            MATCH (leaf:Company)-[:SUBSIDIARY_OF]->(mid)
            WHERE NOT (top)-[:SUBSIDIARY_OF]->(leaf)
            RETURN top.symbol AS parent,
                   leaf.symbol AS leaf,
                   mid.symbol AS mid_symbol
            LIMIT 100
            """,
        )
        results = []
        for row in rows:
            mid_sym = row[2] if len(row) > 2 else ""
            chain = [str(row[0]), str(mid_sym), str(row[1])]
            explanation = f"{row[0]} indirectly controls {row[1]} (via {mid_sym})"
            results.append(
                {
                    "type": "indirect_control",
                    "top_symbol": row[0],
                    "leaf_symbol": row[1],
                    "chain": chain,
                    "ownership_pcts": [],
                    "effective_ownership_pct": 0.0,
                    "explanation": explanation,
                },
            )
        return results

    async def _find_board_interlocks(
        self,
        min_companies: int = 2,
    ) -> list[dict[str, Any]]:
        """Find people on boards of multiple companies."""
        rows = await self._queries.query_raw(
            """
            MATCH (p:Person)-[:IS_BOARD_MEMBER]->(c:Company)
            WITH p, collect(DISTINCT c.symbol) AS companies,
                 count(DISTINCT c) AS n
            WHERE n >= $min_co
            RETURN p.person_name AS person,
                   companies,
                   n
            ORDER BY n DESC
            LIMIT 50
            """,
            {"min_co": min_companies},
        )
        results = []
        for row in rows:
            explanation = (
                f"{row[0]} serves on the board of {row[2]} companies: "
                f"{', '.join(row[1])}"
            )
            results.append(
                {
                    "type": "board_interlock",
                    "person": row[0],
                    "companies": list(row[1]),
                    "n_companies": int(row[2]),
                    "explanation": explanation,
                },
            )
        return results

    async def _analyze_cross_shareholding_influence(
        self,
        min_mutual_pct: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Analyze cross-shareholding patterns for mutual influence."""
        cross = await self.discover_cross_shareholdings(min_stake_pct=min_mutual_pct)
        for item in cross:
            item["type"] = "cross_influence"
            a_pct = item["a_holds_b_pct"]
            b_pct = item["b_holds_a_pct"]
            balance = (
                "balanced"
                if abs(a_pct - b_pct) < _MIN_CROSS_INFLUENCE_DELTA
                else (
                    f"{item['source_symbol']}-leaning"
                    if a_pct > b_pct
                    else f"{item['target_symbol']}-leaning"
                )
            )
            item["balance"] = balance
            item["explanation"] += f" [mutual influence: {balance}]"
        return cross

    # ------------------------------------------------------------------
    # Run all discovery
    # ------------------------------------------------------------------

    async def discover_all(
        self,
    ) -> dict[str, object]:
        """Run all discovery algorithms and return combined results."""
        results: dict[str, object] = {}

        logger.info("Discovering cross-shareholdings...")
        results["cross_shareholdings"] = await self.discover_cross_shareholdings()

        logger.info("Discovering subsidiary chains...")
        results["subsidiary_chains"] = await self.discover_subsidiary_chains()

        logger.info("Discovering shared insiders...")
        results["shared_insiders"] = await self.discover_shared_insiders()

        logger.info("Discovering competitive insiders...")
        results["competitive_insiders"] = await self.discover_competitive_insiders()

        logger.info("Inferring supply chains...")
        results["supply_chain"] = await self.infer_supply_chain()

        logger.info("Mapping influence networks...")
        results["influence_networks"] = await self.map_influence_networks()

        total = sum(len(v) for v in results.values() if isinstance(v, list))
        logger.info("Discovery complete: %d relationships found", total)
        return results

    # ------------------------------------------------------------------
    # Discovery for a single symbol
    # ------------------------------------------------------------------

    async def discover_for_symbol(
        self,
        symbol: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Run discovery targeted at a specific symbol."""
        results: dict[str, list[dict[str, Any]]] = {}

        # Cross-shareholdings involving this symbol
        rows = await self._queries.query_raw(
            """
            MATCH (a:Company)-[r1:HOLDS_STAKE_IN]->(b:Company)
                  -[r2:HOLDS_STAKE_IN]->(a)
            WHERE (a.symbol = $sym OR b.symbol = $sym)
              AND r1.stake_percent >= 0.5
              AND r2.stake_percent >= 0.5
            RETURN a.symbol, b.symbol, r1.stake_percent, r2.stake_percent
            """,
            {"sym": symbol},
        )
        results["cross_shareholdings"] = [
            {
                "type": "cross_shareholding",
                "source_symbol": row[0],
                "target_symbol": row[1],
                "a_holds_b_pct": row[2],
                "b_holds_a_pct": row[3],
            }
            for row in rows
        ]

        # Subsidiary chains
        rows = await self._queries.query_raw(
            """
            MATCH path = (top:Company)<-[:SUBSIDIARY_OF*1..5]-(leaf:Company)
            WHERE top.symbol = $sym OR leaf.symbol = $sym
            RETURN [n IN nodes(path) | n.symbol] AS chain,
                   [r IN relationships(path) | r.ownership_percent] AS pcts
            LIMIT 20
            """,
            {"sym": symbol},
        )
        results["subsidiary_chains"] = [
            {
                "type": "subsidiary_chain",
                "chain": list(row[0]),
                "ownership_pcts": list(row[1]),
            }
            for row in rows
        ]

        # Insiders
        insiders = await self._queries.get_company_insiders(symbol)
        results["insiders"] = (
            [
                {
                    "type": "insider",
                    "person": r.get("person_name")
                    if isinstance(r.get("person_name"), str)
                    else None,
                }
                for r in insiders.to_dicts()
            ]
            if hasattr(insiders, "to_dicts")
            else []
        )

        # Peers (competitors)
        peers = await self._queries.get_sector_peers(symbol)
        results["peers"] = (
            [
                {
                    "type": "peer",
                    "symbol": r.get("symbol"),
                    "name": r.get("name"),
                }
                for r in peers.to_dicts()
            ]
            if hasattr(peers, "to_dicts")
            else []
        )

        return results
