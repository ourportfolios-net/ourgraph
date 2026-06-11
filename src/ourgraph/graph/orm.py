"""Pythonic graph query interface — SQLAlchemy-like ORM for FalkorDB/Cypher.

Provides a fluent, discoverable API so users never need to write raw Cypher.

Basic usage:
    from ourgraph.graph import Graph, Company, Person
    g = Graph()

    # Simple lookups
    hpg = g.get(Company, symbol="HPG")

    # Queries (use .eq(), .gt(), .lt() etc. for filters)
    big = g.query(Company).filter(Company.market_cap.gt(1e9)).all()

    # Traversal
    for sub in hpg.outgoing("SUBSIDIARY_OF").targets():
        print(sub.symbol, sub.ownership_percent)

    # Cross-shareholding
    for x in g.cross_shareholdings():
        print(x)
"""

from __future__ import annotations

import contextlib
import inspect
from typing import TYPE_CHECKING, Any, Self

from ourgraph.graph.schema import NodeLabel, Prop, RelType

if TYPE_CHECKING:
    from ourgraph.config import FalkorDBSettings


# ---------------------------------------------------------------------------
# Node property descriptors — enable Python comparisons that record themselves
# ---------------------------------------------------------------------------


class NodeProperty:
    """Descriptor for node properties that can build filter conditions.

    Usage:
        Company.symbol == "HPG"  # Returns FilterCondition (type checker may complain)
        Company.symbol.eq("HPG")  # Explicit, type-safe version
    """

    def __init__(self, prop_name: str, display_name: str | None = None) -> None:
        self.prop_name = prop_name
        self.display_name = display_name or prop_name

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, NodeProperty):
            return False
        return self.prop_name == value.prop_name

    def __hash__(self) -> int:
        return hash(self.prop_name)

    def eq(self, value: Any) -> FilterCondition:
        return FilterCondition(self.prop_name, "=", value)

    def ne(self, value: Any) -> FilterCondition:
        return FilterCondition(self.prop_name, "<>", value)

    def gt(self, value: Any) -> FilterCondition:
        return FilterCondition(self.prop_name, ">", value)

    def lt(self, value: Any) -> FilterCondition:
        return FilterCondition(self.prop_name, "<", value)

    def ge(self, value: Any) -> FilterCondition:
        return FilterCondition(self.prop_name, ">=", value)

    def le(self, value: Any) -> FilterCondition:
        return FilterCondition(self.prop_name, "<=", value)

    def in_(self, values: list) -> FilterCondition:
        return FilterCondition(self.prop_name, "IN", values)

    def contains(self, value: str) -> FilterCondition:
        return FilterCondition(self.prop_name, "CONTAINS", value)


class FilterCondition:
    """Represents a filter condition that can be compiled to Cypher."""

    def __init__(self, prop: str, op: str, value: Any) -> None:
        self.prop = prop
        self.op = op
        self.value = value

    def to_cypher(self, var: str) -> tuple[str, dict]:
        """Return (cypher_fragment, params)."""
        param_name = f"p_{abs(hash(self.prop)) % 10000}"
        if self.op == "IN":
            return f"{var}.{self.prop} IN ${param_name}", {param_name: self.value}
        if self.op == "CONTAINS":
            return f"{var}.{self.prop} CONTAINS ${param_name}", {param_name: self.value}
        return f"{var}.{self.prop} {self.op} ${param_name}", {param_name: self.value}

    def __and__(self, other: FilterCondition) -> CombinedFilter:
        return CombinedFilter(self, "AND", other)

    def __or__(self, other: FilterCondition) -> CombinedFilter:
        return CombinedFilter(self, "OR", other)


class CombinedFilter:
    """Combine multiple filter conditions."""

    def __init__(self, left: Any, op: str, right: Any) -> None:
        self.left = left
        self.op = op
        self.right = right

    def to_cypher(self, var: str) -> tuple[str, dict]:
        left_cypher, left_params = self.left.to_cypher(var)
        right_cypher, right_params = self.right.to_cypher(var)
        return f"({left_cypher} {self.op} {right_cypher})", {
            **left_params,
            **right_params,
        }

    def __and__(self, other: FilterCondition) -> CombinedFilter:
        return CombinedFilter(self, "AND", other)

    def __or__(self, other: FilterCondition) -> CombinedFilter:
        return CombinedFilter(self, "OR", other)


# ---------------------------------------------------------------------------
# Node class factory — creates Python classes for each node label
# ---------------------------------------------------------------------------

_node_classes: dict[str, type] = {}


def _create_node_class(label: str, properties: list[str]) -> type:
    """Dynamically create a Node class with property descriptors."""
    attrs: dict[str, Any] = {"__label__": label, "__properties__": properties}

    for prop in properties:
        attrs[prop] = NodeProperty(prop)

    def _repr(self) -> str:
        name = getattr(self, "name", None) or getattr(self, "symbol", None) or "?"
        return f"<{self.__class__.__name__} {name}>"

    attrs["__repr__"] = _repr

    cls = type(label, (_BaseNode,), attrs)
    _node_classes[label] = cls
    return cls


class _BaseNode:
    """Base class for all node types."""

    __label__: str
    __properties__: list[str]

    def __init__(self, graph: Graph, data: dict[str, Any]) -> None:
        self._graph = graph
        self._data = data
        for k, v in data.items():
            setattr(self, k, v)

    def __repr__(self) -> str:
        name = getattr(self, "name", None) or getattr(self, "symbol", None) or "?"
        return f"<{self.__class__.__name__} {name}>"

    def outgoing(self, rel_type: str) -> RelationshipQuery:
        """Start traversing relationships outgoing from this node."""
        return RelationshipQuery(self._graph, self, rel_type, direction="out")

    def incoming(self, rel_type: str) -> RelationshipQuery:
        """Start traversing relationships incoming to this node."""
        return RelationshipQuery(self._graph, self, rel_type, direction="in")

    def peers(self) -> list[_BaseNode]:
        """Find companies in the same industry/sector."""
        return self._graph._run_sync(self._graph._get_peers(self))

    def subsidiaries(self) -> list[_BaseNode]:
        """Get subsidiaries of this company."""
        return self._graph._run_sync(
            self._graph._get_subsidiaries(self, parent=True),
        )

    def parent_companies(self) -> list[_BaseNode]:
        """Get parent companies (this company is a subsidiary)."""
        return self._graph._run_sync(
            self._graph._get_subsidiaries(self, parent=False),
        )

    def shareholders(self) -> list[_BaseNode]:
        """Get entities that hold stakes in this company."""
        return self._graph._run_sync(self._graph._get_holders(self))

    def held_companies(self) -> list[_BaseNode]:
        """Get companies this entity holds stakes in."""
        return self._graph._run_sync(self._graph._get_held_companies(self))

    def insiders(self) -> list[_BaseNode]:
        """Get people connected to this company (officers + shareholders)."""
        return self._graph._run_sync(self._graph._get_insiders(self))

    # ------------------------------------------------------------------
    # New derived role traversals
    # ------------------------------------------------------------------

    def board_members(self) -> list[_BaseNode]:
        """Get board members of this company (IS_BOARD_MEMBER)."""
        return self._graph._run_sync(
            self._graph._get_role_holders(self, RelType.IS_BOARD_MEMBER),
        )

    def founders(self) -> list[_BaseNode]:
        """Get founders of this company (IS_FOUNDER)."""
        return self._graph._run_sync(
            self._graph._get_role_holders(self, RelType.IS_FOUNDER),
        )

    def executives(self) -> list[_BaseNode]:
        """Get executives of this company (IS_EXECUTIVE)."""
        return self._graph._run_sync(
            self._graph._get_role_holders(self, RelType.IS_EXECUTIVE),
        )

    def siblings(self) -> list[_BaseNode]:
        """Get sister companies (share the same parent)."""
        return self._graph._run_sync(self._graph._get_siblings(self))


# Create node classes for each label
Company = _create_node_class(
    NodeLabel.COMPANY,
    [
        Prop.SYMBOL,
        Prop.NAME,
        Prop.EXCHANGE,
        Prop.MARKET_CAP,
        Prop.NO_EMPLOYEES,
        Prop.ESTABLISHED_YEAR,
        Prop.WEBSITE,
        Prop.OUTSTANDING_SHARE,
        Prop.FOREIGN_PERCENT,
    ],
)

Person = _create_node_class(
    NodeLabel.PERSON,
    [Prop.PERSON_NAME, Prop.NAME],
)

Sector = _create_node_class(NodeLabel.SECTOR, [Prop.NAME])
Industry = _create_node_class(NodeLabel.INDUSTRY, [Prop.NAME])

Indicator = _create_node_class(
    NodeLabel.INDICATOR,
    [Prop.SYMBOL, Prop.YEAR, Prop.QUARTER, Prop.PBR, Prop.PER, Prop.EPS, Prop.PAYLOAD],
)

FinancialStatement = _create_node_class(
    NodeLabel.FINANCIAL_STATEMENT,
    [
        Prop.SYMBOL,
        Prop.YEAR,
        Prop.QUARTER,
        Prop.STATEMENT_TYPE,
        Prop.PERIOD,
        Prop.PAYLOAD,
    ],
)

MacroIndicator = _create_node_class(
    NodeLabel.MACRO_INDICATOR,
    [
        Prop.NAME,
        Prop.VALUE,
        Prop.UNIT,
        Prop.DATE,
        Prop.COUNTRY,
        Prop.CATEGORY,
        Prop.FREQUENCY,
        Prop.SOURCE,
    ],
)

Country = _create_node_class(
    NodeLabel.COUNTRY,
    [Prop.CODE, Prop.NAME],
)


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------


class Query:
    """Fluent query builder for Cypher — SQLAlchemy-style."""

    def __init__(
        self,
        graph: Graph,
        node_class: type | None = None,
        var: str = "n",
    ) -> None:
        self._graph = graph
        self._node_class = node_class
        self._var = var
        self._label: str | None = (
            getattr(node_class, "__label__", None) if node_class else None
        )
        self._filters: list[FilterCondition] = []
        self._return_exprs: list[str] = []
        self._order_by: str | None = None
        self._limit_val: int | None = None
        self._skip_val: int | None = None

    def filter(self, *conditions: FilterCondition) -> Self:
        """Add filter conditions."""
        self._filters.extend(conditions)
        return self

    def where(self, cypher: str, **params: Any) -> Self:
        """Add a raw Cypher WHERE clause (for advanced use)."""
        self._raw_where = (cypher, params)
        return self

    def order_by(self, expr: str, desc: bool = False) -> Self:
        """Add ORDER BY clause."""
        direction = "DESC" if desc else "ASC"
        self._order_by = f"{expr} {direction}"
        return self

    def limit(self, n: int) -> Self:
        """Add LIMIT clause."""
        self._limit_val = n
        return self

    def skip(self, n: int) -> Self:
        """Add SKIP clause."""
        self._skip_val = n
        return self

    def return_(self, *exprs: str) -> Self:
        """Set RETURN expressions."""
        self._return_exprs = list(exprs)
        return self

    def _build_cypher(self) -> tuple[str, dict]:
        """Compile the query to a Cypher string."""
        params: dict[str, Any] = {}
        parts: list[str] = []

        # MATCH
        label_str = f":{self._label}" if self._label else ""
        parts.append(f"MATCH ({self._var}{label_str})")

        # WHERE
        if self._filters:
            where_parts: list[str] = []
            for f in self._filters:
                cypher, p = f.to_cypher(self._var)
                where_parts.append(cypher)
                params.update(p)
            if where_parts:
                parts.append(f"WHERE {' AND '.join(where_parts)}")

        # RETURN
        if self._return_exprs:
            ret = ", ".join(self._return_exprs)
        else:
            ret = self._var
        parts.append(f"RETURN {ret}")

        # ORDER BY
        if self._order_by:
            parts.append(f"ORDER BY {self._order_by}")

        # SKIP / LIMIT
        if self._skip_val is not None:
            parts.append(f"SKIP {self._skip_val}")
        if self._limit_val is not None:
            parts.append(f"LIMIT {self._limit_val}")

        return " ".join(parts), params

    async def _execute(self) -> list[dict[str, Any]]:
        """Execute the query and return results."""
        cypher, params = self._build_cypher()
        rows = await self._graph._query(cypher, params)
        return rows

    async def _all(self) -> list:
        """Execute and return node objects."""
        rows = await self._execute()
        if self._node_class and self._return_exprs == [self._var]:
            return [self._node_class(self._graph, dict(r)) for r in rows]
        return rows

    def all(self) -> list:
        """Execute synchronously and return results."""
        return self._graph._run_sync(self._all())

    def first(self) -> Any:
        """Execute and return the first result."""
        return self._graph._run_sync(self._first())

    async def _first(self) -> Any | None:
        self._limit_val = 1
        rows = await self._execute()
        if not rows:
            return None
        if self._node_class and self._return_exprs == [self._var]:
            return self._node_class(self._graph, dict(rows[0]))
        return rows[0]


# ---------------------------------------------------------------------------
# Relationship traversal
# ---------------------------------------------------------------------------


class RelationshipQuery:
    """Query for traversing relationships."""

    def __init__(
        self,
        graph: Graph,
        source: _BaseNode,
        rel_type: str,
        direction: str = "out",
    ) -> None:
        self._graph = graph
        self._source = source
        self._rel_type = rel_type
        self._direction = direction
        self._target_label: str | None = None

    def targets(self, node_class: type | None = None) -> list[_BaseNode]:
        """Get target nodes of this relationship."""
        return self._graph._run_sync(self._get_targets(node_class))

    async def _get_targets(self, node_class: type | None) -> list[_BaseNode]:
        """Async implementation for getting targets."""
        source_id_prop = (
            Prop.SYMBOL if hasattr(self._source, "symbol") else Prop.PERSON_NAME
        )
        source_id = getattr(self._source, source_id_prop, None)
        if source_id is None:
            return []

        # Build the Cypher pattern with proper escaping
        label = self._source.__label__
        cypher_filter = f"{{{source_id_prop}: $sid}}"

        if self._direction == "out":
            cypher = f"""
                MATCH (a:{label} {cypher_filter})
                      -[r:{self._rel_type}]->(b)
                RETURN b, r
            """
        else:
            cypher = f"""
                MATCH (a:{label} {cypher_filter})
                      <-[r:{self._rel_type}]-(b)
                RETURN b, r
            """

        rows = await self._graph._query(cypher, {"sid": source_id})

        results = []
        for row in rows:
            node_data = dict(row[0]) if isinstance(row[0], dict) else dict(row[0])
            rel_data = dict(row[1]) if len(row) > 1 and isinstance(row[1], dict) else {}
            node_data.update({f"rel_{k}": v for k, v in rel_data.items()})
            if node_class:
                results.append(node_class(self._graph, node_data))
            else:
                label = self._get_label_from_data(node_data)
                cls = _node_classes.get(label, _BaseNode)
                results.append(cls(self._graph, node_data))
        return results

    @staticmethod
    def _get_label_from_data(data: dict) -> str:
        """Infer node label from returned data."""
        if "symbol" in data:
            return NodeLabel.COMPANY
        if "person_name" in data:
            return NodeLabel.PERSON
        return NodeLabel.COMPANY


# ---------------------------------------------------------------------------
# Graph — main entry point
# ---------------------------------------------------------------------------


class Graph:
    """Main entry point for the Pythonic graph API.

    Usage:
        g = Graph()

        # Get a node
        hpg = g.get(Company, symbol="HPG")

        # Query
        big = g.query(Company).filter(Company.market_cap > 1e9).all()

        # Cross-shareholdings
        for a, b, pct_a, pct_b in g.cross_shareholdings():
            print(f"{a} ↔ {b}: {pct_a}% / {pct_b}%")
    """

    def __init__(
        self,
        settings: FalkorDBSettings | None = None,
    ) -> None:
        from ourgraph.config import get_settings
        from ourgraph.db.falkordb import build_falkordb_client

        self._settings = settings or get_settings().falkordb
        self._client = build_falkordb_client(self._settings)
        self._graph_name = self._settings.graph_name

    @classmethod
    def from_settings(cls, settings: FalkorDBSettings) -> Graph:
        return cls(settings=settings)

    def query(self, node_class: type, var: str = "n") -> Query:
        """Start building a query for a node type."""
        return Query(self, node_class=node_class, var=var)

    def get(self, node_class: type, **kwargs: Any) -> _BaseNode | None:
        """Get a single node by properties."""
        q = self.query(node_class)
        for k, v in kwargs.items():
            prop = getattr(node_class, k, None)
            if prop:
                q = q.filter(prop == v)
        return q.first()

    async def _query(self, cypher: str, params: dict | None = None) -> list:
        """Execute a raw Cypher query."""
        g = self._client.select_graph(self._graph_name)
        result = await g.ro_query(cypher, params or {})
        return result.result_set

    def _run_sync(self, coro: Any) -> Any:
        """Run an async coroutine synchronously."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)

    # ------------------------------------------------------------------
    # Company network queries
    # ------------------------------------------------------------------

    async def _get_company_network(self, symbol: str | None = None) -> list[dict]:
        """Get inter-company relationships."""
        where = (
            f"WHERE a.{Prop.SYMBOL} = $symbol OR b.{Prop.SYMBOL} = $symbol"
            if symbol
            else ""
        )
        params: dict = {"limit": 1000}
        if symbol:
            params["symbol"] = symbol

        cypher = f"""
            MATCH (a:{NodeLabel.COMPANY})-[r:{RelType.HOLDS_STAKE_IN}|{RelType.SUBSIDIARY_OF}|{RelType.COMPETES_WITH}]->(b:{NodeLabel.COMPANY})
            {where}
            RETURN a.{Prop.SYMBOL} AS source,
                   a.{Prop.NAME} AS source_name,
                   type(r) AS rel_type,
                   b.{Prop.SYMBOL} AS target,
                   b.{Prop.NAME} AS target_name,
                   r.{Prop.STAKE_PERCENT} AS stake_pct,
                   r.{Prop.OWNERSHIP_PERCENT} AS ownership_pct
            ORDER BY type(r), source, target
            LIMIT $limit
        """
        return await self._query(cypher, params)

    def company_network(self, symbol: str | None = None) -> list[dict]:
        """Get company-to-company relationship network."""
        return self._run_sync(self._get_company_network(symbol))

    async def _get_peers(self, node: _BaseNode) -> list[_BaseNode]:
        """Get companies in the same industry."""
        symbol = getattr(node, "symbol", None)
        if not symbol:
            return []

        cypher = f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                  -[:{RelType.BELONGS_TO_INDUSTRY}]->(ind:{NodeLabel.INDUSTRY})
                  <-[:{RelType.BELONGS_TO_INDUSTRY}]-(peer:{NodeLabel.COMPANY})
            WHERE peer.{Prop.SYMBOL} <> $symbol
            RETURN peer
            ORDER BY peer.{Prop.MARKET_CAP} DESC
        """
        rows = await self._query(cypher, {"symbol": symbol})
        return [Company(self, dict(r[0])) for r in rows if r]

    async def _get_subsidiaries(
        self,
        node: _BaseNode,
        parent: bool = False,
    ) -> list[_BaseNode]:
        """Get subsidiaries or parent companies."""
        symbol = getattr(node, "symbol", None)
        if not symbol:
            return []

        if parent:
            cypher = f"""
                MATCH (child:{NodeLabel.COMPANY})-[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
                RETURN child, r.{Prop.OWNERSHIP_PERCENT} AS pct, r.{Prop.RELATION_TYPE} AS rel_type
            """
        else:
            cypher = f"""
                MATCH (child:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})-[r:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY})
                RETURN parent, r.{Prop.OWNERSHIP_PERCENT} AS pct, r.{Prop.RELATION_TYPE} AS rel_type
            """

        rows = await self._query(cypher, {"symbol": symbol})
        results = []
        for r in rows:
            data = dict(r[0]) if isinstance(r[0], dict) else {}
            if len(r) > 1:
                data["ownership_pct"] = r[1]
                data["relation_type"] = r[2]
            results.append(Company(self, data))
        return results

    async def _get_holders(self, node: _BaseNode) -> list[_BaseNode]:
        """Get shareholders of a company."""
        symbol = getattr(node, "symbol", None)
        if not symbol:
            return []

        cypher = f"""
            MATCH (holder)-[r:{RelType.HOLDS_STAKE_IN}]->(target:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN holder, labels(holder)[0] AS holder_type, r.{Prop.STAKE_PERCENT} AS stake_pct
            ORDER BY r.{Prop.STAKE_PERCENT} DESC
        """
        rows = await self._query(cypher, {"symbol": symbol})
        results = []
        for r in rows:
            data = dict(r[0]) if isinstance(r[0], dict) else {}
            if len(r) > 1:
                data["holder_type"] = r[1]
                data["stake_pct"] = r[2]
            cls = Company if data.get("holder_type") == NodeLabel.COMPANY else Person
            results.append(cls(self, data))
        return results

    async def _get_held_companies(self, node: _BaseNode) -> list[_BaseNode]:
        """Get companies that this entity holds stakes in."""
        if hasattr(node, "symbol"):
            key, val = Prop.SYMBOL, node.symbol
        elif hasattr(node, "person_name"):
            key, val = Prop.PERSON_NAME, node.person_name
        else:
            return []

        cypher = f"""
            MATCH (holder {{{key}: $val}})-[r:{RelType.HOLDS_STAKE_IN}]->(target:{NodeLabel.COMPANY})
            RETURN target, r.{Prop.STAKE_PERCENT} AS stake_pct
            ORDER BY r.{Prop.STAKE_PERCENT} DESC
        """
        rows = await self._query(cypher, {"val": val})
        results = []
        for r in rows:
            data = dict(r[0]) if isinstance(r[0], dict) else {}
            if len(r) > 1:
                data["stake_pct"] = r[1]
            results.append(Company(self, data))
        return results

    async def _get_insiders(self, node: _BaseNode) -> list[_BaseNode]:
        """Get insiders (officers + shareholders) of a company."""
        symbol = getattr(node, "symbol", None)
        if not symbol:
            return []

        cypher = f"""
            MATCH (p:{NodeLabel.PERSON})-[off:{RelType.IS_OFFICER}]->(c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            OPTIONAL MATCH (p)-[hold:{RelType.HOLDS_STAKE_IN}]->(c)
            RETURN p, off.{Prop.POSITION} AS position, off.{Prop.OWN_PERCENT} AS own_pct, hold.{Prop.STAKE_PERCENT} AS stake_pct
            UNION ALL
            MATCH (p:{NodeLabel.PERSON})-[hold:{RelType.HOLDS_STAKE_IN}]->(c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            WHERE NOT (p)-[:{RelType.IS_OFFICER}]->(c)
            RETURN p, null AS position, null AS own_pct, hold.{Prop.STAKE_PERCENT} AS stake_pct
        """
        rows = await self._query(cypher, {"symbol": symbol})
        results = []
        for r in rows:
            data = dict(r[0]) if isinstance(r[0], dict) else {}
            if len(r) > 1:
                data["officer_position"] = r[1]
                data["officer_own_pct"] = r[2]
                data["stake_pct"] = r[3]
            results.append(Person(self, data))
        return results

    # ------------------------------------------------------------------
    # Derived role queries
    # ------------------------------------------------------------------

    async def _get_role_holders(
        self, node: _BaseNode, role_type: str,
    ) -> list[_BaseNode]:
        """Get people with a specific role relationship to a company."""
        symbol = getattr(node, "symbol", None)
        if not symbol:
            return []

        cypher = f"""
            MATCH (p:{NodeLabel.PERSON})-[r:{role_type}]->(c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})
            RETURN p, r.{Prop.POSITION} AS position
        """
        rows = await self._query(cypher, {"symbol": symbol})
        results = []
        for r in rows:
            data = dict(r[0]) if isinstance(r[0], dict) else {}
            if len(r) > 1:
                data["role_position"] = r[1]
            results.append(Person(self, data))
        return results

    async def _get_siblings(self, node: _BaseNode) -> list[_BaseNode]:
        """Get sister companies (share the same parent)."""
        symbol = getattr(node, "symbol", None)
        if not symbol:
            return []

        cypher = f"""
            MATCH (c:{NodeLabel.COMPANY} {{{Prop.SYMBOL}: $symbol}})-[:{RelType.SUBSIDIARY_OF}]->(parent:{NodeLabel.COMPANY})
            MATCH (sibling:{NodeLabel.COMPANY})-[:{RelType.SUBSIDIARY_OF}]->(parent)
            WHERE sibling.{Prop.SYMBOL} <> $symbol
            RETURN sibling
        """
        rows = await self._query(cypher, {"symbol": symbol})
        return [Company(self, dict(r[0])) for r in rows if r]

    # ------------------------------------------------------------------
    # Market insight queries
    # ------------------------------------------------------------------

    def cross_shareholdings(self) -> list[dict]:
        """Find pairs of companies that hold stakes in each other."""

        async def _run():
            cypher = f"""
                MATCH (a:{NodeLabel.COMPANY})-[r1:{RelType.HOLDS_STAKE_IN}]->(b:{NodeLabel.COMPANY})
                      -[r2:{RelType.HOLDS_STAKE_IN}]->(a)
                RETURN a.{Prop.SYMBOL} AS symbol_a,
                       a.{Prop.NAME} AS name_a,
                       b.{Prop.SYMBOL} AS symbol_b,
                       b.{Prop.NAME} AS name_b,
                       r1.{Prop.STAKE_PERCENT} AS a_holds_b_pct,
                       r2.{Prop.STAKE_PERCENT} AS b_holds_a_pct
            """
            return await self._query(cypher)

        rows = self._run_sync(_run())
        return [
            {
                "symbol_a": r[0],
                "name_a": r[1],
                "symbol_b": r[2],
                "name_b": r[3],
                "a_holds_b_pct": r[4],
                "b_holds_a_pct": r[5],
            }
            for r in rows
        ]

    def shared_insiders(self, min_companies: int = 2) -> list[dict]:
        """Find people who are insiders at multiple companies."""

        async def _run():
            cypher = f"""
                MATCH (p:{NodeLabel.PERSON})-[r:{RelType.IS_OFFICER}|{RelType.HOLDS_STAKE_IN}]->(c:{NodeLabel.COMPANY})
                WITH p.{Prop.PERSON_NAME} AS person, collect(DISTINCT c.{Prop.SYMBOL}) AS companies, COUNT(DISTINCT c) AS n
                WHERE n >= $min_c
                RETURN person, companies, n
                ORDER BY n DESC
            """
            return await self._query(cypher, {"min_c": min_companies})

        rows = self._run_sync(_run())
        return [
            {
                "person": r[0],
                "companies": r[1],
                "n_companies": r[2],
            }
            for r in rows
        ]

    def sector_overview(self, sector_name: str | None = None) -> list[dict]:
        """Get overview of sectors with company counts and market caps."""

        async def _run():
            where = f"WHERE s.{Prop.NAME} = $sector" if sector_name else ""
            cypher = f"""
                MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO}]->(s:{NodeLabel.SECTOR})
                {where}
                RETURN s.{Prop.NAME} AS sector,
                       COUNT(c) AS n_companies,
                       SUM(c.{Prop.MARKET_CAP}) AS total_mcap
                ORDER BY total_mcap DESC
            """
            params = {"sector": sector_name} if sector_name else {}
            return await self._query(cypher, params)

        rows = self._run_sync(_run())
        return [
            {
                "sector": r[0],
                "n_companies": r[1],
                "total_market_cap": r[2],
            }
            for r in rows
        ]

    def industry_overview(self) -> list[dict]:
        """Get overview of industries."""

        async def _run():
            cypher = f"""
                MATCH (c:{NodeLabel.COMPANY})-[:{RelType.BELONGS_TO_INDUSTRY}]->(i:{NodeLabel.INDUSTRY})
                RETURN i.{Prop.NAME} AS industry,
                       COUNT(c) AS n_companies,
                       COLLECT(DISTINCT c.{Prop.SYMBOL}) AS symbols
                ORDER BY n_companies DESC
            """
            return await self._query(cypher)

        rows = self._run_sync(_run())
        return [
            {
                "industry": r[0],
                "n_companies": r[1],
                "symbols": r[2],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Hidden relationship discovery
    # ------------------------------------------------------------------

    def hidden_relationships(self) -> dict[str, list]:
        """Discover hidden relationships in the graph.

        Returns a dict with:
          - cross_shareholdings: Companies that hold stakes in each other
          - shared_insiders: People on multiple company boards
          - competitive_ownership: Competitors with shared major shareholders
          - subsidiary_chains: Multi-level ownership chains
        """
        return {
            "cross_shareholdings": self.cross_shareholdings(),
            "shared_insiders": self.shared_insiders(),
            "competitive_ownership": self._competitive_ownership(),
            "subsidiary_chains": self._subsidiary_chains(),
        }

    def _competitive_ownership(self) -> list[dict]:
        """Find competitors that share major shareholders."""

        async def _run():
            cypher = f"""
                MATCH (holder)-[r1:{RelType.HOLDS_STAKE_IN}]->(c1:{NodeLabel.COMPANY})
                      -[:{RelType.COMPETES_WITH}]->(c2:{NodeLabel.COMPANY})
                      <-[r2:{RelType.HOLDS_STAKE_IN}]-(holder)
                WHERE r1.{Prop.STAKE_PERCENT} > 1 AND r2.{Prop.STAKE_PERCENT} > 1
                RETURN holder, c1.{Prop.SYMBOL} AS c1_sym, c2.{Prop.SYMBOL} AS c2_sym,
                       r1.{Prop.STAKE_PERCENT} AS pct1, r2.{Prop.STAKE_PERCENT} AS pct2
                ORDER BY pct1 + pct2 DESC
            """
            return await self._query(cypher)

        rows = self._run_sync(_run())
        return [
            {
                "holder": r[0].get(Prop.PERSON_NAME) or r[0].get(Prop.NAME, "Unknown"),
                "company_a": r[1],
                "company_b": r[2],
                "stake_in_a": r[3],
                "stake_in_b": r[4],
            }
            for r in rows
        ]

    def _subsidiary_chains(self) -> list[dict]:
        """Find multi-level subsidiary relationships (A owns B owns C)."""

        async def _run():
            cypher = f"""
                MATCH (a:{NodeLabel.COMPANY})-[r1:{RelType.SUBSIDIARY_OF}]->(b:{NodeLabel.COMPANY})
                      -[r2:{RelType.SUBSIDIARY_OF}]->(c:{NodeLabel.COMPANY})
                RETURN a.{Prop.SYMBOL} AS sub, b.{Prop.SYMBOL} AS mid, c.{Prop.SYMBOL} AS top,
                       r1.{Prop.OWNERSHIP_PERCENT} AS pct1, r2.{Prop.OWNERSHIP_PERCENT} AS pct2
            """
            return await self._query(cypher)

        rows = self._run_sync(_run())
        return [
            {
                "subsidiary": r[0],
                "parent": r[1],
                "grandparent": r[2],
                "ownership_pct_l1": r[3],
                "ownership_pct_l2": r[4],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Graph statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Get graph statistics."""

        async def _run():
            queries = {
                "companies": f"MATCH (c:{NodeLabel.COMPANY}) RETURN COUNT(c)",
                "persons": f"MATCH (p:{NodeLabel.PERSON}) RETURN COUNT(p)",
                "indicators": f"MATCH (i:{NodeLabel.INDICATOR}) RETURN COUNT(i)",
                "financial_statements": f"MATCH (s:{NodeLabel.FINANCIAL_STATEMENT}) RETURN COUNT(s)",
                "relationships": "MATCH ()-[r]->() RETURN COUNT(r)",
            }
            results = {}
            for key, cypher in queries.items():
                rows = await self._query(cypher)
                results[key] = int(rows[0][0]) if rows else 0
            return results

        return self._run_sync(_run())

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            close = getattr(self._client, "close", None)
            if callable(close):
                maybe_awaitable = close()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
