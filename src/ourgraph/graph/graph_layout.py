"""Server-side graph element formatter.

Replaces the client-side ``_formatElements()`` in ``_cytoscape.js``.
Produces pre-positioned element arrays that Cytoscape.js can consume
directly with a ``preset`` layout, eliminating redundant client-side
layout computation.
"""

from __future__ import annotations

import hashlib
from typing import Any

# ── Style constants (mirrors state.py) ──────────────────────────────────

_NODE_COLORS: dict[str, str] = {
    "Company": "rgba(96, 165, 250, 0.85)",
    "Person": "rgba(74, 222, 128, 0.85)",
    "Sector": "rgba(249, 115, 22, 0.85)",
    "Industry": "rgba(249, 115, 22, 0.85)",
    "MacroIndicator": "rgba(239, 68, 68, 0.85)",
    "Country": "rgba(168, 85, 247, 0.85)",
}

_NODE_SHAPES: dict[str, str] = {
    "Company": "ellipse",
    "Person": "diamond",
    "Sector": "round-rectangle",
    "Industry": "round-rectangle",
    "MacroIndicator": "triangle",
    "Country": "hexagon",
}

_COMPANY_TYPE_COLORS: dict[str, str] = {
    "listed": "rgba(59, 130, 246, 0.9)",
    "subsidiary": "rgba(100, 116, 139, 0.5)",
}

_REL_COLORS: dict[str, str] = {
    "HOLDS_STAKE_IN": "#64748b",
    "SUBSIDIARY_OF": "#8b5cf6",
    "COMPETES_WITH": "#ef4444",
    "IS_OFFICER": "#22c55e",
    "IS_BOARD_MEMBER": "#22c55e",
    "IS_FOUNDER": "#22c55e",
    "IS_EXECUTIVE": "#22c55e",
    "BELONGS_TO": "#475569",
    "BELONGS_TO_INDUSTRY": "#475569",
    "AFFECTS_SECTOR": "#f97316",
    "AFFECTS_INDUSTRY": "#f97316",
    "HAS_MACRO_INDICATOR": "#ef4444",
    "RELATED_PARTY_TRANSACTION": "#f59e0b",
    "GUARANTEES": "#ec4899",
    "LENDS_TO": "#06b6d4",
    "HAS_JOINT_VENTURE_WITH": "#8b5cf6",
    "UNDERWRITTEN_BY": "#f97316",
    "HAS_BUSINESS_COOPERATION": "#10b981",
    "STATE_OWNS": "#3b82f6",
}

_REL_STYLES: dict[str, str] = {
    "HOLDS_STAKE_IN": "solid",
    "SUBSIDIARY_OF": "dotted",
    "COMPETES_WITH": "dashed",
    "IS_OFFICER": "solid",
    "IS_BOARD_MEMBER": "solid",
    "IS_FOUNDER": "solid",
    "IS_EXECUTIVE": "solid",
    "BELONGS_TO": "solid",
    "BELONGS_TO_INDUSTRY": "solid",
    "AFFECTS_SECTOR": "dashed",
    "AFFECTS_INDUSTRY": "dashed",
    "HAS_MACRO_INDICATOR": "dotted",
    "RELATED_PARTY_TRANSACTION": "dashed",
    "GUARANTEES": "dotted",
    "LENDS_TO": "solid",
    "HAS_JOINT_VENTURE_WITH": "dashed",
    "UNDERWRITTEN_BY": "dotted",
    "HAS_BUSINESS_COOPERATION": "dashed",
    "STATE_OWNS": "solid",
}

_EDGE_LABELS: dict[str, str] = {
    "HOLDS_STAKE_IN": "holds stake in",
    "SUBSIDIARY_OF": "subsidiary",
    "COMPETES_WITH": "competes",
    "IS_OFFICER": "officer",
    "IS_BOARD_MEMBER": "board member",
    "IS_FOUNDER": "founder",
    "IS_EXECUTIVE": "executive",
    "BELONGS_TO": "belongs to",
    "BELONGS_TO_INDUSTRY": "belongs to",
    "AFFECTS_SECTOR": "affects",
    "AFFECTS_INDUSTRY": "affects",
    "HAS_MACRO_INDICATOR": "macro",
    "RELATED_PARTY_TRANSACTION": "related party",
    "GUARANTEES": "guarantees",
    "LENDS_TO": "lends to",
    "HAS_JOINT_VENTURE_WITH": "joint venture",
    "UNDERWRITTEN_BY": "underwritten by",
    "HAS_BUSINESS_COOPERATION": "cooperation",
    "STATE_OWNS": "state owns",
}

_CATEGORY_MAP: dict[str, list[str]] = {
    "ownership": ["HOLDS_STAKE_IN", "SUBSIDIARY_OF"],
    "competition": ["COMPETES_WITH"],
    "roles": ["IS_OFFICER", "IS_BOARD_MEMBER", "IS_FOUNDER", "IS_EXECUTIVE"],
    "industry": ["BELONGS_TO", "BELONGS_TO_INDUSTRY"],
    "macro": ["AFFECTS_SECTOR", "AFFECTS_INDUSTRY", "HAS_MACRO_INDICATOR"],
    "related_party": ["RELATED_PARTY_TRANSACTION"],
    "guarantees": ["GUARANTEES"],
    "lends_to": ["LENDS_TO"],
    "joint_venture": ["HAS_JOINT_VENTURE_WITH"],
    "underwritten_by": ["UNDERWRITTEN_BY"],
    "cooperation": ["HAS_BUSINESS_COOPERATION"],
    "state_owns": ["STATE_OWNS"],
}

# Edges and nodes excluded from the canvas (kept in raw JSON for detail panel)
_EXCLUDED_EDGE_TYPES = {"AUDITED_BY", "HAS_INDICATOR", "HAS_FINANCIAL_STATEMENTS"}
_EXCLUDED_NODE_TYPES = {"Indicator", "FinancialStatement", "Industry"}


# ── Helpers ─────────────────────────────────────────────────────────────


def _sector_to_color(sector_name: str) -> str:
    """Deterministic HSL color from sector name."""
    h = hashlib.sha256(sector_name.encode()).hexdigest()
    hue = int(h[:8], 16) % 360
    return f"hsl({hue}, 50%, 45%)"


def _derive_label(node_id: str) -> str:
    """Extract display label from a node ID like 'Company:HPG' -> 'HPG'."""
    idx = node_id.rfind(":")
    if 0 <= idx < len(node_id) - 1:
        return node_id[idx + 1 :]
    return node_id


# ── Sector map builder ──────────────────────────────────────────────────


def _build_sector_map(
    nodes_raw: list[dict],
    edges_raw: list[dict],
) -> dict[str, dict]:
    """Build sector map from BELONGS_TO edges.

    Returns a dict mapping company node IDs to
    ``{"sectorLevel", "sectorName"}``.
    """
    sector_names: dict[str, str] = {}
    for n in nodes_raw:
        ntype = (n.get("labels") or ["Unknown"])[0]
        if ntype not in ("Sector", "Industry"):
            continue
        props = n.get("properties") or {}
        sn = props.get("name") or _derive_label(n.get("id", ""))
        sector_names[n["id"]] = sn

    sector_map: dict[str, dict] = {}
    sector_levels: dict[str, int] = {}

    belongs_edges = [
        e
        for e in edges_raw
        if e.get("relationship") in ("BELONGS_TO", "BELONGS_TO_INDUSTRY")
    ]
    belongs_edges.sort(key=lambda e: sector_names.get(e.get("target", ""), ""))

    for e in belongs_edges:
        company_id = e.get("source", "")
        sector_id = e.get("target", "")
        sector_name = sector_names.get(sector_id, "Unknown")
        if sector_name not in sector_levels:
            sector_levels[sector_name] = len(sector_levels) + 1
        if company_id not in sector_map:
            sector_map[company_id] = {
                "sectorLevel": sector_levels[sector_name],
                "sectorName": sector_name,
            }

    return sector_map


# ── Single-element builders ─────────────────────────────────────────────


def _build_node_element(
    node: dict,
    filtered_edges: list[dict],
    sector_map: dict[str, dict],
) -> dict[str, Any] | None:
    """Build a single node element, or None if it should be excluded."""
    ntype = (node.get("labels") or ["Unknown"])[0]
    props = node.get("properties") or {}

    if ntype in _EXCLUDED_NODE_TYPES:
        return None
    if ntype == "Company" and props.get("company_type") == "audit_firm":
        return None

    nid = node.get("id", "")
    label = (
        props.get("name")
        or props.get("person_name")
        or props.get("symbol")
        or _derive_label(nid)
    )

    degree = sum(
        1 for e in filtered_edges if e.get("source") == nid or e.get("target") == nid
    )

    sec = sector_map.get(nid)
    if sec:
        sector_level = sec["sectorLevel"]
        sector_name = sec["sectorName"]
        sector_color: str | None = _sector_to_color(sector_name)
    elif ntype in ("Sector", "Industry"):
        sector_level = 0
        sector_name = props.get("name", "") or label
        sector_color = None
    elif ntype == "Person":
        sector_level = 50
        sector_name = ""
        sector_color = None
    else:
        sector_level = 99
        sector_name = ""
        sector_color = None

    return {
        "group": "nodes",
        "data": {
            **props,
            "id": nid,
            "label": label,
            "ntype": ntype,
            "size": min(50, max(20, 15 + degree * 3)),
            "sectorLevel": sector_level,
            "sectorName": sector_name,
            "sectorColor": sector_color,
        },
    }


def _build_edge_element(
    edge: dict,
    included_node_ids: set[str],
) -> dict[str, Any] | None:
    """Build a single edge element, or None if endpoints are excluded."""
    src = edge.get("source", "")
    tgt = edge.get("target", "")
    if src not in included_node_ids or tgt not in included_node_ids:
        return None

    rel_type = edge.get("relationship", "")
    eprops = edge.get("properties") or {}

    eid = f"{src}--{rel_type}--{tgt}"
    stake = eprops.get("stake_percent")
    if stake is not None:
        eid += f"--{stake}"

    return {
        "group": "edges",
        "data": {
            **eprops,
            "id": eid,
            "source": src,
            "target": tgt,
            "rtype": rel_type,
            "label": _EDGE_LABELS.get(rel_type, rel_type.replace("_", " ")),
        },
    }


# ── Main formatter ──────────────────────────────────────────────────────


def format_elements(graph_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Transform raw graph data into Cytoscape.js element arrays with positions."""
    nodes_raw: list[dict] = graph_data.get("nodes", [])
    edges_raw: list[dict] = graph_data.get("edges", [])

    filtered_edges = [
        e for e in edges_raw if e.get("relationship") not in _EXCLUDED_EDGE_TYPES
    ]

    sector_map = _build_sector_map(nodes_raw, edges_raw)

    elements: list[dict] = []
    included_node_ids: set[str] = set()

    for n in nodes_raw:
        el = _build_node_element(n, filtered_edges, sector_map)
        if el is not None:
            elements.append(el)
            included_node_ids.add(el["data"]["id"])

    for e in filtered_edges:
        el = _build_edge_element(e, included_node_ids)
        if el is not None:
            elements.append(el)

    _apply_cluster_layout(elements)
    return elements


# ── Cluster Layout ──────────────────────────────────────────────────────


def _position_cluster(
    cluster: dict,
    cx: float,
    cy: float,
) -> None:
    """Position a single cluster's sector node and company nodes."""
    if cluster["node"]:
        cluster["node"]["position"] = {"x": cx, "y": cy}

    companies = cluster["companies"]
    n_comp = len(companies)
    for cj, comp in enumerate(companies):
        a = (cj / max(n_comp, 1)) * 2 * 3.14159
        r = min(100, 20 + n_comp * 3)
        comp["position"] = {
            "x": cx + r * _cos(a),
            "y": cy + r * _sin(a),
        }


def _apply_cluster_layout(elements: list[dict]) -> None:
    """Position nodes using the sector-cluster algorithm."""
    sector_nodes: dict[str, dict] = {}
    other_nodes: list[dict] = []

    for el in elements:
        if el.get("group") != "nodes":
            continue
        data = el.get("data", {})
        ntype = data.get("ntype", "")
        sname = data.get("sectorName", "")

        if ntype == "Sector":
            sector_nodes.setdefault(sname, {"node": None, "companies": []})
            sector_nodes[sname]["node"] = el
        elif ntype == "Company" and sname:
            sector_nodes.setdefault(sname, {"node": None, "companies": []})
            sector_nodes[sname]["companies"].append(el)
        elif ntype == "Company" and not sname:
            sector_nodes.setdefault("__unassigned__", {"node": None, "companies": []})
            sector_nodes["__unassigned__"]["companies"].append(el)
        else:
            other_nodes.append(el)

    cluster_names = [n for n in sector_nodes if n != "__unassigned__"]
    num_clusters = len(cluster_names)
    cluster_radius = min(600, max(250, num_clusters * 45))
    cluster_r = min(120, max(50, 70))

    for ci, name in enumerate(cluster_names):
        angle = (ci / max(num_clusters, 1)) * 2 * 3.14159 - 3.14159 / 2
        cx = cluster_radius * _cos(angle)
        cy = cluster_radius * _sin(angle)
        _position_cluster(sector_nodes[name], cx, cy)

    unassigned = sector_nodes.get("__unassigned__")
    if unassigned:
        ucomps = unassigned["companies"]
        outer_r = cluster_radius + cluster_r + 200
        for uj, comp in enumerate(ucomps):
            ua = (uj / max(len(ucomps), 1)) * 2 * 3.14159
            comp["position"] = {
                "x": outer_r * _cos(ua),
                "y": outer_r * _sin(ua),
            }

    for oi, el in enumerate(other_nodes):
        oa = (oi / max(len(other_nodes), 1)) * 2 * 3.14159
        or_ = cluster_radius + cluster_r + 400
        el["position"] = {"x": or_ * _cos(oa), "y": or_ * _sin(oa)}


# ── Math helpers ────────────────────────────────────────────────────────


def _cos(x: float) -> float:
    """Cosine via Taylor series (good enough for layout positioning)."""
    x = x % (2 * 3.14159)
    x2 = x * x
    return 1 - x2 / 2 + x2 * x2 / 24 - x2 * x2 * x2 / 720 + x2 * x2 * x2 * x2 / 40320


def _sin(x: float) -> float:
    """Sine via Taylor series."""
    x = x % (2 * 3.14159)
    x3 = x * x * x
    x5 = x3 * x * x
    x7 = x5 * x * x
    return x - x3 / 6 + x5 / 120 - x7 / 5040


# ── Style JSON ──────────────────────────────────────────────────────────


def build_style_json() -> dict[str, Any]:
    """Return style constants as a serializable dict for the frontend."""
    return {
        "nodeColors": _NODE_COLORS,
        "nodeShapes": _NODE_SHAPES,
        "companyTypeColors": _COMPANY_TYPE_COLORS,
        "relColors": _REL_COLORS,
        "relStyles": _REL_STYLES,
        "edgeLabels": _EDGE_LABELS,
        "categoryMap": _CATEGORY_MAP,
    }
