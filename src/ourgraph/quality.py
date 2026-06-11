"""Graph Quality Check module.

Provides functions to check graph quality and identify issues.
Used by both the CLI (`ourgraph quality`) and standalone scripts.
"""

import asyncio

from rich.console import Console

from ourgraph.config import AppSettings, get_settings
from ourgraph.graph.builder import GraphBuilder

console = Console()


async def run_quality_check(settings: AppSettings | None = None) -> list[str]:
    """Run comprehensive quality checks. Returns list of issues found."""
    if settings is None:
        settings = get_settings()

    issues: list[str] = []

    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        # === Check 1: Duplicate Nodes ===
        console.print("[bold]Check 1: Duplicate Nodes[/bold]")
        dups = await _check_duplicates(builder)
        for node_type, count in dups.items():
            if count > 0:
                console.print(f"  [red]✗[/red] {node_type}: {count} duplicates")
                issues.append(f"Duplicates in {node_type}: {count}")
            else:
                console.print(f"  [green]✓[/green] {node_type}: No duplicates")

        # === Check 2: Missing Relationships ===
        console.print("\n[bold]Check 2: Missing Relationships[/bold]")
        missing = await _check_missing_relationships(builder)
        for rel_type, count in missing.items():
            if count > 0:
                console.print(f"  [red]✗[/red] {rel_type}: {count} companies missing")
                issues.append(f"Missing {rel_type}: {count} companies")
            else:
                console.print(f"  [green]✓[/green] {rel_type}: All present")

        # === Check 3: Subsidiary Data ===
        console.print("\n[bold]Check 3: Subsidiary Data[/bold]")
        sub_issues = await _check_subsidiaries(builder)
        if sub_issues:
            for issue in sub_issues:
                console.print(f"  [red]✗[/red] {issue}")
                issues.append(issue)
        else:
            console.print("  [green]✓[/green] Subsidiaries OK")

        # === Check 4: Shareholder Classification ===
        console.print("\n[bold]Check 4: Shareholder Classification[/bold]")
        holder_issues = await _check_shareholder_classification(builder)
        if holder_issues:
            for issue in holder_issues:
                console.print(f"  [red]✗[/red] {issue}")
                issues.append(issue)
        else:
            console.print("  [green]✓[/green] Shareholders classified correctly")

        # === Check 5: Data Completeness ===
        console.print("\n[bold]Check 5: Data Completeness[/bold]")
        completeness = await _check_data_completeness(builder)
        for metric, (present, total, pct) in completeness.items():
            color = "green" if pct > 80 else "yellow" if pct > 50 else "red"
            console.print(
                f"  [{color}]{metric}: {present}/{total} ({pct:.1f}%)[/{color}]",
            )

        # === Summary ===
        console.print("\n" + "=" * 60)
        if issues:
            console.print(f"[red]Found {len(issues)} issue(s) to fix:[/red]")
            for i, issue in enumerate(issues, 1):
                console.print(f"  {i}. {issue}")
        else:
            console.print("[green]✓ No quality issues found![/green]")
        console.print("=" * 60)

    return issues


async def _check_duplicates(builder: GraphBuilder) -> dict[str, int]:
    """Check for duplicate nodes using correct composite keys."""
    results = {}

    # Company: check by symbol
    rows = await builder.query_raw(
        "MATCH (n:Company) "
        "WITH n.symbol AS key, collect(n) AS nodes "
        "WHERE key IS NOT NULL AND key <> '' AND size(nodes) > 1 "
        "RETURN count(*)",
    )
    results["Company"] = rows[0][0] if rows else 0

    # Person: check by person_name
    rows = await builder.query_raw(
        "MATCH (n:Person) "
        "WITH n.person_name AS key, collect(n) AS nodes "
        "WHERE key IS NOT NULL AND key <> '' AND size(nodes) > 1 "
        "RETURN count(*)",
    )
    results["Person"] = rows[0][0] if rows else 0

    # StockPrice: check by (symbol, date)
    rows = await builder.query_raw(
        "MATCH (n:StockPrice) "
        "WITH n.symbol AS sym, n.date AS dt, collect(n) AS nodes "
        "WHERE sym IS NOT NULL AND sym <> '' AND dt IS NOT NULL AND dt <> '' AND size(nodes) > 1 "
        "RETURN count(*)",
    )
    results["StockPrice"] = rows[0][0] if rows else 0

    # Indicator: check by (symbol, year, quarter)
    rows = await builder.query_raw(
        "MATCH (n:Indicator) "
        "WITH n.symbol AS sym, n.year AS y, n.quarter AS q, collect(n) AS nodes "
        "WHERE sym IS NOT NULL AND sym <> '' AND y IS NOT NULL AND q IS NOT NULL AND size(nodes) > 1 "
        "RETURN count(*)",
    )
    results["Indicator"] = rows[0][0] if rows else 0

    # FinancialStatement: check by (symbol, statement_type, period, year, quarter)
    rows = await builder.query_raw(
        "MATCH (n:FinancialStatement) "
        "WITH n.symbol AS sym, n.statement_type AS st, n.period AS p, n.year AS y, n.quarter AS q, collect(n) AS nodes "
        "WHERE sym IS NOT NULL AND sym <> '' AND st IS NOT NULL AND p IS NOT NULL AND y IS NOT NULL AND q IS NOT NULL AND size(nodes) > 1 "
        "RETURN count(*)",
    )
    results["FinancialStatement"] = rows[0][0] if rows else 0

    return results


async def _check_missing_relationships(builder: GraphBuilder) -> dict[str, int]:
    """Check for missing expected relationships."""
    results = {}

    # Companies missing sector links
    rows = await builder.query_raw(
        "MATCH (c:Company) WHERE NOT (c)-[:BELONGS_TO]->(:Sector) RETURN count(c)",
    )
    results["Sector links"] = rows[0][0] if rows else 0

    # Companies missing industry links
    rows = await builder.query_raw(
        "MATCH (c:Company) "
        "WHERE NOT (c)-[:BELONGS_TO_INDUSTRY]->(:Industry) "
        "RETURN count(c)",
    )
    results["Industry links"] = rows[0][0] if rows else 0

    # Companies missing any relationship
    rows = await builder.query_raw(
        "MATCH (c:Company) WHERE NOT (c)--() RETURN count(c)",
    )
    results["Isolated companies"] = rows[0][0] if rows else 0

    return results


async def _check_subsidiaries(builder: GraphBuilder) -> list[str]:
    """Check subsidiary data quality."""
    issues = []

    # Subsidiaries with missing ownership_percent
    rows = await builder.query_raw(
        "MATCH (c1:Company)-[r:SUBSIDIARY_OF]->(c2:Company) "
        "WHERE r.ownership_percent IS NULL OR r.ownership_percent = 0 "
        "RETURN count(r)",
    )
    if rows and rows[0][0] > 0:
        issues.append(f"Subsidiaries with missing ownership: {rows[0][0]}")

    # Subsidiary nodes that don't have company profiles
    rows = await builder.query_raw(
        "MATCH (child:Company)-[:SUBSIDIARY_OF]->(:Company) "
        "WHERE child.name IS NULL OR child.name = child.symbol "
        "RETURN count(child)",
    )
    if rows and rows[0][0] > 0:
        issues.append(f"Subsidiaries with missing company profiles: {rows[0][0]}")

    return issues


async def _check_shareholder_classification(builder: GraphBuilder) -> list[str]:
    """Check if corporate shareholders are properly classified."""
    issues = []

    # Corporate shareholders that are Person nodes
    rows = await builder.query_raw(
        "MATCH (p:Person)-[:HOLDS_STAKE_IN]->(:Company) "
        "WHERE p.name CONTAINS 'JSC' OR p.name CONTAINS 'Corp' OR p.name CONTAINS 'Ltd' "
        "RETURN count(p)",
    )
    if rows and rows[0][0] > 0:
        issues.append(f"Corporate shareholders classified as Person: {rows[0][0]}")

    # Company shareholders that don't have proper symbol
    rows = await builder.query_raw(
        "MATCH (c:Company)-[:HOLDS_STAKE_IN]->(:Company) "
        "WHERE c.symbol IS NULL OR c.symbol = c.name "
        "RETURN count(c)",
    )
    if rows and rows[0][0] > 0:
        issues.append(f"Company shareholders with missing symbols: {rows[0][0]}")

    return issues


async def _check_data_completeness(
    builder: GraphBuilder,
) -> dict[str, tuple[int, int, float]]:
    """Check data completeness for companies."""
    results = {}

    # Companies with financials
    rows = await builder.query_raw(
        "MATCH (c:Company) "
        "OPTIONAL MATCH (c)-[:HAS_FINANCIAL_STATEMENTS]->(fs:FinancialStatement) "
        "WITH c, count(fs) AS fs_count "
        "RETURN count(CASE WHEN fs_count > 0 THEN 1 END) as with_fs, count(c) as total",
    )
    if rows:
        results["Companies with financials"] = (
            rows[0][0],
            rows[0][1],
            100.0 * rows[0][0] / rows[0][1] if rows[0][1] > 0 else 0,
        )

    # Companies with indicators
    rows = await builder.query_raw(
        "MATCH (c:Company) "
        "OPTIONAL MATCH (c)-[:HAS_INDICATOR]->(i:Indicator) "
        "WITH c, count(i) AS i_count "
        "RETURN count(CASE WHEN i_count > 0 THEN 1 END) as with_i, count(c) as total",
    )
    if rows:
        results["Companies with indicators"] = (
            rows[0][0],
            rows[0][1],
            100.0 * rows[0][0] / rows[0][1] if rows[0][1] > 0 else 0,
        )

    return results


def run_quality_sync(settings: AppSettings | None = None) -> list[str]:
    """Synchronous wrapper for run_quality_check."""
    return asyncio.run(run_quality_check(settings))
