"""CLI entry point.

Commands:
  ourgraph ingest full          Run the full pipeline (raw graph + Graphiti)
  ourgraph ingest daily         Run today's price update
  ourgraph ingest symbol ACB    Ingest a single symbol (raw graph + Graphiti)
  ourgraph ingest graphiti      Re-feed Graphiti from existing raw graph (no re-fetch)
  ourgraph schedule             Start the daily scheduler daemon
  ourgraph query "..."          GraphRAG query
  ourgraph graph peers ACB      Get sector peers
  ourgraph graph subs VCB       Get subsidiaries
  ourgraph graph prices ACB     Get price history
  ourgraph graph insiders VCB   Get officers + individual shareholders
  ourgraph graph network        Get company-to-company relationship network
  ourgraph setup                First-time setup (indices + Graphiti init)
  ourgraph info                 Print effective configuration
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from ourgraph.constants import (
    DEFAULT_CROSS_SHAREHOLDING_LIMIT,
    DEFAULT_NETWORK_LIMIT,
    DEFAULT_PEERS_LIMIT,
    DEFAULT_QUERY_RESULTS,
    DEFAULT_SHARED_INSIDERS_LIMIT,
    TABLE_DATE_COLUMN_WIDTH,
    TABLE_FACT_COLUMN_WIDTH,
)

if TYPE_CHECKING:
    import polars as pl

    from ourgraph.config import AppSettings

app = typer.Typer(
    help="Vietnamese stock market knowledge graph CLI",
    no_args_is_help=True,
)
ingest_app = typer.Typer(help="Data ingestion commands")
graph_app = typer.Typer(help="Graph query commands")
app.add_typer(ingest_app, name="ingest")
app.add_typer(graph_app, name="graph")

console = Console()
INGEST_SYMBOLS_ARG = typer.Argument(
    None,
    help="Optional list of symbols. Defaults to all VNIndex.",
)
MACRO_SOURCES_ARG = typer.Argument(
    None,
    help="Sources: worldbank, imf, yfinance, vnstock. Default: all configured.",
)
CLEAR_DEFAULT_CONFIRM = False
MASK_PREFIX_LENGTH = 4


def _settings() -> AppSettings:
    from ourgraph.config import get_settings

    return get_settings()


# ===========================================================================
# Setup
# ===========================================================================


@app.command()
def setup() -> None:
    """First-time setup: create graph indices and initialise Graphiti."""
    settings = _settings()

    async def _run() -> None:
        from ourgraph.graph.builder import GraphBuilder
        from ourgraph.graphiti_layer.client import build_graphiti_client

        console.print("[bold green]Setting up graph indices...[/bold green]")
        async with GraphBuilder.from_settings(settings.falkordb) as builder:
            await builder.ensure_indices()
        console.print("[green]✓ Graph indices created[/green]")

        console.print("[bold green]Initialising Graphiti indices...[/bold green]")
        client = build_graphiti_client(settings)
        await client.build_indices_and_constraints()
        await client.close()
        console.print("[green]✓ Graphiti indices created[/green]")

    asyncio.run(_run())


# ===========================================================================
# Ingest commands
# ===========================================================================


@ingest_app.command("full")
def ingest_full(
    symbols: list[str] = INGEST_SYMBOLS_ARG,
    resume: bool = typer.Option(  # noqa: FBT001
        False,  # noqa: FBT003
        "--resume",
        "-r",
        help="Skip symbols already in the graph; only ingest remaining ones.",
    ),
    industry: list[str] = typer.Option(  # noqa: B008
        None,
        "--industry",
        "-ind",
        help="Only process companies matching this industry (repeatable). "
        "E.g. --industry Banking --industry Steel",
    ),
    scrape: bool = typer.Option(  # noqa: FBT001
        False,  # noqa: FBT003
        "--scrape",
        "-s",
        help="Run structured scrapers (CafeF, HNX bonds, SCIC) after ingestion.",
    ),
) -> None:
    """Run the full pipeline — VNIndex symbols, raw graph + Graphiti ingestion.

    Use --resume to continue from a previously interrupted run without
    re-fetching data for symbols already in the graph.

    Use --industry to focus on specific industries (e.g. Banking, Steel).
    The pipeline fetches all company overviews first, then only fetches
    detailed data (officers, shareholders, prices, etc.) for companies
    in the specified industries.

    Use --scrape to run structured scrapers after the main pipeline completes.
    """
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    async def _run() -> None:
        syms = symbols or await Pipeline(settings).resolve_symbols_for_progress()
        total = len(syms)
        if total == 0:
            console.print("[yellow]No symbols to ingest[/yellow]")
            return

        if industry:
            console.print(
                f"[bold]Filtering to industries:[/bold] {', '.join(industry)}",
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_companies = progress.add_task("[dim]Companies[/dim]", total=total)
            task_details = progress.add_task("[dim]Details[/dim] ", total=total)

            def _on_done(sym: str, phase: str) -> None:
                if phase == "Company":
                    progress.update(
                        task_companies, advance=1, description=f"[cyan]{sym}[/cyan]",
                    )
                else:
                    progress.update(
                        task_details, advance=1, description=f"[cyan]{sym}[/cyan]",
                    )

            pipeline = Pipeline(settings, on_symbol_done=_on_done)
            await pipeline.run_full(
                symbols=syms,
                resume=resume,
                industries=industry,
            )
            progress.update(task_companies, description="[green]✓[/green]")
            progress.update(task_details, description="[green]✓[/green]")

        if scrape:
            console.print("[bold cyan]Running structured scrapers...[/bold cyan]")
            with console.status("[bold green]Scraping...[/bold green]"):
                results = await Pipeline(settings).run_scrapers(
                    symbols=syms,
                    cafef=True,
                    hnx_bonds=True,
                    scic=True,
                )
            for name, count in results.items():
                console.print(f"  [green]✓[/green] {name}: {count} relationships")
            console.print("[green]✓ Scraping complete[/green]")

    asyncio.run(_run())


@ingest_app.command("daily")
def ingest_daily() -> None:
    """Daily update is not needed after removing price data."""
    console.print(
        "[yellow]Daily update skipped — price data removed from graph[/yellow]",
    )


# Curated tickers with rich cross-relationships for testing the knowledge graph.
# Grouped by theme to maximise interesting edges (cross-shareholding, shared
# insiders, subsidiary chains, sector competition).
DEFAULT_TEST_SYMBOLS: list[str] = [
    # Conglomerate chain: VIC owns VHM (Vinhomes) + VRE (Vincom Retail)
    "VIC",
    "VHM",
    "VRE",
    # Steel sector: HPG (Hoa Phat) and HSG (Hoa Sen) compete, share industry
    "HPG",
    "HSG",
    # Banking cross-holdings: VCB and BID hold stakes in each other + in securities
    "VCB",
    "BID",
    # Securities: SSI cross-held by banks, deep subsidiary tree
    "SSI",
]


@ingest_app.command("test")
def ingest_test(
    symbols: list[str] = typer.Argument(  # noqa: B008
        None,
        help="Explicit ticker symbols. Overrides --industry/--symbols-list when provided.",
    ),
    industry: list[str] = typer.Option(  # noqa: B008
        None,
        "--industry",
        "-ind",
        help="Focus on specific industries (repeatable). "
        "Default: Banking, Steel, Real Estate, Technology, Securities.",
    ),
    symbols_list: list[str] = typer.Option(  # noqa: B008
        None,
        "--symbols-list",
        "-s",
        help="Named ticker list to use: 'curated' (default, ~30 related tickers), "
        "'banking' (10 banks), 'realestate' (real estate + construction), "
        "'steel' (steel & materials), 'conglomerates' (VIC, FPT, MSN + holdings).",
    ),
    scrape: bool = typer.Option(  # noqa: FBT001
        False,  # noqa: FBT003
        "--scrape",
        help="Run structured scrapers (CafeF, HNX bonds, SCIC) after ingestion.",
    ),
) -> None:
    """Run a focused test with ~30 closely-related tickers.

    Useful for testing edge creation without ingesting all ~400 VNIndex
    symbols. Three modes:

    1. Explicit symbols:  ourgraph ingest test VCB VHM HPG
    2. Industry filter:   ourgraph ingest test --industry Banking --industry Steel
    3. Named list:       ourgraph ingest test --symbols-list curated  (default)

    The curated list (~30 tickers) is designed to maximise cross-relationships:
    cross-shareholding, shared insiders, subsidiary chains, and sector competition.
    """
    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    async def _run() -> None:
        pipeline = Pipeline(settings)

        async def _run_scrapers(p: Pipeline, syms: list[str]) -> None:
            console.print("[bold cyan]Running scrapers...[/bold cyan]")
            with console.status("[bold green]Scraping...[/bold green]"):
                results = await p.run_scrapers(
                    symbols=syms,
                    cafef=True,
                    hnx_bonds=True,
                    scic=True,
                )
            for name, count in results.items():
                console.print(f"  [green]✓[/green] {name}: {count} relationships")

        # Mode 1: explicit symbols from positional args
        if symbols:
            console.print(
                f"[bold cyan]Test run:[/bold cyan] {len(symbols)} explicit symbols: "
                f"{', '.join(symbols)}",
            )
            with console.status("[bold green]Running test pipeline...[/bold green]"):
                await pipeline.run_full(symbols=symbols)
            if scrape:
                await _run_scrapers(pipeline, symbols)
            return

        # Mode 2: industry filter
        if industry:
            industries = industry
            console.print(
                f"[bold cyan]Test run:[/bold cyan] industries: {', '.join(industries)}",
            )
            syms = await pipeline.resolve_symbols_for_progress()
            console.print(
                f"Resolved {len(syms)} VNIndex symbols — will filter by industry",
            )
            with console.status("[bold green]Running test pipeline...[/bold green]"):
                await pipeline.run_full(symbols=syms, industries=industries)
            if scrape:
                await _run_scrapers(pipeline, syms)
            return

        # Mode 3: named symbol list (default: curated)
        list_name = (symbols_list or ["curated"])[0].lower()
        list_map = {
            "curated": DEFAULT_TEST_SYMBOLS,
            "banking": [
                s
                for s in DEFAULT_TEST_SYMBOLS
                if s
                in (
                    "VCB",
                    "BID",
                    "CTG",
                    "TCB",
                    "MBB",
                    "ACB",
                    "VPB",
                    "HDB",
                    "STB",
                    "LPB",
                )
            ],
            "realestate": [
                s
                for s in DEFAULT_TEST_SYMBOLS
                if s in ("VHM", "NVL", "KDH", "DXG", "HPG", "VIC")
            ],
            "steel": [
                s for s in DEFAULT_TEST_SYMBOLS if s in ("HPG", "HSG", "NKG", "POM")
            ],
            "conglomerates": [
                s
                for s in DEFAULT_TEST_SYMBOLS
                if s in ("VIC", "FPT", "MSN", "VNM", "SAB")
            ],
        }
        syms = list_map.get(list_name, DEFAULT_TEST_SYMBOLS)
        console.print(
            f"[bold cyan]Test run:[/bold cyan] list='{list_name}' — "
            f"{len(syms)} tickers: {', '.join(syms)}",
        )
        with console.status("[bold green]Running test pipeline...[/bold green]"):
            await pipeline.run_full(symbols=syms)
        if scrape:
            await _run_scrapers(pipeline, syms)

    asyncio.run(_run())
    console.print("[green]✓ Test run complete[/green]")


@ingest_app.command("symbol")
def ingest_symbol(
    symbol: str = typer.Argument(..., help="Ticker symbol, e.g. VCB"),
) -> None:
    """Ingest all data for a single symbol (raw graph + Graphiti episode)."""
    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    pipeline = Pipeline(settings)
    with console.status(f"[bold green]Ingesting {symbol}...[/bold green]"):
        asyncio.run(pipeline.run_full(symbols=[symbol]))
    console.print(f"[green]✓ {symbol} ingested[/green]")


@ingest_app.command("graphiti")
def ingest_graphiti(symbols: list[str] = INGEST_SYMBOLS_ARG) -> None:
    """Re-feed Graphiti from the existing raw FalkorDB graph.

    Use this when the raw graph is already built but Graphiti is empty or stale.
    Does NOT re-fetch data from vnstock — reads only from FalkorDB.

    This is what makes `ourgraph query` return actual results.
    """
    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    pipeline = Pipeline(settings)
    with console.status("[bold green]Feeding Graphiti from raw graph...[/bold green]"):
        asyncio.run(pipeline.run_graphiti_only(symbols=symbols or None))
    console.print("[green]✓ Graphiti ingestion complete[/green]")


@ingest_app.command("macro")
def ingest_macro(
    sources: list[str] = MACRO_SOURCES_ARG,
) -> None:
    """Ingest macro economic data from free APIs."""
    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    pipeline = Pipeline(settings)
    with console.status("[bold green]Ingesting macro data...[/bold green]"):
        results: dict[str, int] = asyncio.run(
            pipeline.run_macro_ingestion(sources=sources),
        )
    table = Table(title="Macro Ingestion Results", show_lines=True)
    table.add_column("Source", style="cyan")
    table.add_column("Indicators", style="white", justify="right")
    for source, count in results.items():
        table.add_row(source, str(count))
    console.print(table)


# ===========================================================================
# Scheduler
# ===========================================================================


@app.command()
def schedule() -> None:
    """Start the daily scheduler daemon (blocks until Ctrl+C)."""
    settings = _settings()
    from ourgraph.ingest.scheduler import run_scheduler

    console.print(
        f"[bold]Starting scheduler[/bold] — cron: [cyan]{settings.scheduler.cron}[/cyan]",
    )
    run_scheduler(settings)


# ===========================================================================
# GraphRAG query
# ===========================================================================


@app.command()
def query(
    question: str = typer.Argument(..., help="Natural language question"),
    num_results: int = typer.Option(
        DEFAULT_QUERY_RESULTS,
        "--results",
        "-n",
        help="Max results",
    ),
) -> None:
    """Run a GraphRAG query against the temporal knowledge graph."""
    settings = _settings()
    from ourgraph.graphiti_layer.search import GraphRAGSearch

    async def _run() -> list[dict]:
        search = await GraphRAGSearch.create(settings)
        results = await search.query(question, num_results=num_results)
        await search.close()
        return results

    with console.status("[bold green]Querying knowledge graph...[/bold green]"):
        results: list[dict] = asyncio.run(_run())

    if not results:
        console.print(
            "[yellow]No results found.[/yellow]\n"
            "Hint: if you haven't run [bold]ourgraph ingest graphiti[/bold] yet, "
            "Graphiti has no episodes and will always return empty.",
        )
        return

    table = Table(title=f"Results for: {question}", show_lines=True)
    table.add_column("Fact", style="white", max_width=TABLE_FACT_COLUMN_WIDTH)
    table.add_column("Valid At", style="cyan", width=TABLE_DATE_COLUMN_WIDTH)
    table.add_column("Invalid At", style="red", width=TABLE_DATE_COLUMN_WIDTH)

    for row in results:
        table.add_row(
            row.get("fact", ""),
            row.get("valid_at") or "—",
            row.get("invalid_at") or "—",
        )
    console.print(table)


# ===========================================================================
# Graph query commands
# ===========================================================================


@graph_app.command("peers")
def graph_peers(
    symbol: str = typer.Argument(..., help="Ticker symbol"),
    limit: int = typer.Option(DEFAULT_PEERS_LIMIT, "--limit", "-l"),
) -> None:
    """List sector peers for a symbol."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_sector_peers(symbol, limit=limit)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No peers found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("subs")
def graph_subs(symbol: str = typer.Argument(..., help="Ticker symbol")) -> None:
    """List direct subsidiaries of a company."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_subsidiaries(symbol)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No subsidiaries found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("shareholders")
def graph_shareholders(symbol: str = typer.Argument(..., help="Ticker symbol")) -> None:
    """List major shareholders (companies + individual people)."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_shareholders(symbol)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No shareholders found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("insiders")
def graph_insiders(symbol: str = typer.Argument(..., help="Ticker symbol")) -> None:
    """List all people connected to a company (officers + individual shareholders).

    Dual-role people appear with both officer position and stake shown.
    """
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_company_insiders(symbol)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No insider data found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("person")
def graph_person(name: str = typer.Argument(..., help="Person name")) -> None:
    """Show all roles a person holds across companies."""
    settings = _settings()
    from ourgraph.graph.builder import _normalize_person_name
    from ourgraph.graph.queries import GraphQueries

    # Normalize the search term to match the stored format
    normalized_name = _normalize_person_name(name)

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_person_roles(normalized_name)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No data found for {name}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("shared-insiders")
def graph_shared_insiders(
    limit: int = typer.Option(DEFAULT_SHARED_INSIDERS_LIMIT, "--limit", "-l"),
) -> None:
    """Find people who hold insider roles at multiple companies (hidden influence network)."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.find_shared_insiders(limit=limit)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print("[yellow]No shared insiders found.[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("network")
def graph_network(
    symbol: str = typer.Option(
        None,
        "--symbol",
        "-s",
        help="Filter to ego-network of one ticker",
    ),
    limit: int = typer.Option(DEFAULT_NETWORK_LIMIT, "--limit", "-l"),
) -> None:
    """Show inter-company relationship network (ownership, subsidiaries, competition)."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_company_network(symbol=symbol, limit=limit)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print("[yellow]No network data found.[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("cross-shareholding")
def graph_cross_shareholding(
    limit: int = typer.Option(DEFAULT_CROSS_SHAREHOLDING_LIMIT, "--limit", "-l"),
) -> None:
    """Find cross-shareholding pairs in the graph."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.find_cross_shareholding(limit=limit)

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print("[yellow]No cross-shareholding pairs found.[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("discover")
def graph_discover(
    symbol: str = typer.Option(
        None, "--symbol", "-s", help="Focus discovery on a specific symbol",
    ),
) -> None:
    """Discover hidden relationships in the knowledge graph.

    Runs cross-shareholding, subsidiary chain, shared insider,
    supply chain, and influence network discovery algorithms.
    """
    settings = _settings()
    from ourgraph.graph.discovery import GraphDiscovery
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> dict:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            discovery = GraphDiscovery(queries)
            if symbol:
                return await discovery.discover_for_symbol(symbol)
            return await discovery.discover_all()

    with console.status("[bold]Discovering hidden relationships..."):
        results: dict = asyncio.run(_run())

    if not results or all(len(v) == 0 for v in results.values() if isinstance(v, list)):
        console.print("[yellow]No hidden relationships discovered.[/yellow]")
        return

    for category, items in results.items():
        if isinstance(items, dict):
            # Nested dict (influence_networks)
            console.print(
                f"\n[bold cyan]🔍 {category.replace('_', ' ').title()}[/bold cyan]",
            )
            for sub_category, sub_items in items.items():
                if sub_items:
                    console.print(
                        f"  [bold]{sub_category.replace('_', ' ').title()}: {len(sub_items)} found[/bold]",
                    )
                    for item in sub_items[:5]:  # Top 5 per subcategory
                        console.print(f"    • {item.get('explanation', str(item))}")
        elif items:
            console.print(
                f"\n[bold cyan]🔍 {category.replace('_', ' ').title()}: {len(items)} found[/bold cyan]",
            )
            for item in items[:10]:  # Top 10
                console.print(f"  • {item.get('explanation', str(item))}")


@graph_app.command("macro")
def graph_macro(
    country: str = typer.Option(
        None, "--country", "-c", help="Filter by country code (VN, US, GLOBAL)",
    ),
    category: str = typer.Option(
        None,
        "--category",
        "-cat",
        help="Filter by category (vn_economy, global_commodity, etc.)",
    ),
    name: str = typer.Option(
        None, "--name", "-n", help="Filter by indicator name (partial match)",
    ),
    limit: int = typer.Option(50, "--limit", "-l"),
) -> None:
    """Query macro economic indicators."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> pl.DataFrame:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_macro_indicators(
                country=country,
                category=category,
                name=name,
                limit=limit,
            )

    df: pl.DataFrame = asyncio.run(_run())
    if df.is_empty():
        console.print("[yellow]No macro indicators found.[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("macro-stats")
def graph_macro_stats() -> None:
    """Show macro indicator coverage (count by country, category)."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> dict:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_macro_stats()

    stats: dict = asyncio.run(_run())

    table = Table(title="Macro Indicator Stats", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="white", justify="right")
    table.add_row("Total indicators", str(stats.get("total", 0)))
    for country, cnt in stats.get("by_country", {}).items():
        table.add_row(f"  {country}", str(cnt))
    for category, cnt in stats.get("by_category", {}).items():
        table.add_row(f"  {category}", str(cnt))
    console.print(table)


@graph_app.command("stats")
def graph_stats() -> None:
    """Print high-level graph counts to validate ingestion progress."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> dict:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_graph_stats()

    stats: dict = asyncio.run(_run())

    table = Table(title="Graph Stats", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="white", justify="right")
    table.add_row("Company nodes", str(stats.get("companies", 0)))
    table.add_row("Person nodes", str(stats.get("persons", 0)))
    table.add_row("FinancialStatement nodes", str(stats.get("financial_statements", 0)))
    table.add_row("FinancialIndicator nodes", str(stats.get("financial_indicators", 0)))
    table.add_row("MacroIndicator nodes", str(stats.get("macro_indicators", 0)))
    table.add_row("Country nodes", str(stats.get("countries", 0)))
    console.print(table)


@graph_app.command("dedupe")
def graph_dedupe() -> None:
    """Remove duplicate nodes by natural keys and rewire relationships."""
    settings = _settings()
    from ourgraph.graph.builder import GraphBuilder

    async def _run() -> dict:
        async with GraphBuilder.from_settings(settings.falkordb) as builder:
            return await builder.deduplicate_nodes()

    with console.status("[bold green]Deduplicating graph nodes...[/bold green]"):
        stats: dict = asyncio.run(_run())

    table = Table(title="Deduplication Result", show_lines=True)
    table.add_column("Node Type", style="cyan")
    table.add_column("Removed", style="white", justify="right")
    table.add_row("Company", str(stats.get("company", 0)))
    table.add_row("Person", str(stats.get("person", 0)))
    table.add_row("Indicator", str(stats.get("indicator", 0)))
    table.add_row("FinancialStatement", str(stats.get("financial_statement", 0)))
    table.add_row("Date", str(stats.get("date", 0)))
    table.add_row("Quarter", str(stats.get("quarter", 0)))
    table.add_row("Year", str(stats.get("year", 0)))
    table.add_row("Sector", str(stats.get("sector", 0)))
    table.add_row("Industry", str(stats.get("industry", 0)))
    console.print(table)


@graph_app.command("clear")
def graph_clear(
    *,
    yes: bool = typer.Option(
        CLEAR_DEFAULT_CONFIRM,
        "--yes",
        "-y",
        help="Confirm destructive operation: delete all graph data.",
    ),
) -> None:
    """Delete all nodes and relationships in the current graph."""
    if not yes:
        console.print(
            "[red]Refusing to clear graph without confirmation.[/red] "
            "Re-run with [bold]--yes[/bold].",
        )
        raise typer.Exit(code=1)

    settings = _settings()
    from ourgraph.graph.builder import GraphBuilder

    async def _run() -> dict:
        async with GraphBuilder.from_settings(settings.falkordb) as builder:
            return await builder.clear_graph()

    with console.status("[bold red]Clearing graph data...[/bold red]"):
        result: dict = asyncio.run(_run())

    table = Table(title="Graph Clear Result", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="white", justify="right")
    table.add_row("Deleted nodes", str(result.get("deleted_nodes", 0)))
    table.add_row("Deleted relationships", str(result.get("deleted_relationships", 0)))
    console.print(table)


@graph_app.command("export")
def graph_export(
    symbol: str = typer.Option(
        None, "--symbol", "-s", help="Export only the ego-network around a symbol",
    ),
    output: str = typer.Option(
        None, "--output", "-o", help="Output file path (default: stdout)",
    ),
) -> None:
    """Export the knowledge graph as JSON (nodes + edges) for visualization."""
    import json
    import sys

    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> dict:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.export_graph_json(symbol=symbol)

    with console.status("[bold]Exporting graph...[/bold]"):
        data: dict = asyncio.run(_run())

    console.print(
        f"[green]Exported {len(data['nodes'])} nodes, {len(data['edges'])} edges[/green]",
    )
    json_str = json.dumps(data, ensure_ascii=False, default=str)
    if output:
        import pathlib

        pathlib.Path(output).write_text(json_str)
        console.print(f"[green]Saved to {output}[/green]")
    else:
        sys.stdout.write(json_str)
        sys.stdout.write("\\n")


# ===========================================================================
# Info
# ===========================================================================


@app.command()
def info() -> None:
    """Print the effective configuration (sensitive values masked)."""
    settings = _settings()

    table = Table(title="ourgraph configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")

    def _mask(v: str) -> str:
        return (
            v[:MASK_PREFIX_LENGTH] + "****" if len(v) > MASK_PREFIX_LENGTH else "****"
        )

    rows = [
        ("FalkorDB host", settings.falkordb.host),
        ("FalkorDB port", str(settings.falkordb.port)),
        ("FalkorDB graph", settings.falkordb.graph_name),
        ("FalkorDB user", settings.falkordb.username or "(none)"),
        ("Ollama base URL", settings.ollama.base_url),
        ("Ollama LLM model", settings.ollama.llm_model),
        ("Ollama small model", settings.ollama.llm_small_model),
        ("Ollama embed model", settings.ollama.embedding_model),
        ("Ollama embed dim", str(settings.ollama.embedding_dim)),
        ("vnstock source", settings.vnstock.source),
        ("Batch size", str(settings.pipeline.batch_size)),
        ("Batch delay (s)", str(settings.pipeline.batch_delay)),
        ("Financial quarters", str(settings.pipeline.financial_quarters)),
        ("Scheduler cron", settings.scheduler.cron),
        ("Graphiti semaphore", str(settings.graphiti.semaphore_limit)),
        ("Log level", settings.log_level),
        ("Macro sources", settings.macro.sources),
        ("Macro start year", str(settings.macro.start_year)),
        ("Macro yfinance commodities", settings.macro.yfinance_commodities),
        ("Macro yfinance indices", settings.macro.yfinance_indices),
        (
            "Tiger Data URL",
            _mask(settings.tiger_data.url) if settings.tiger_data.url else "(not set)",
        ),
    ]

    for key, val in rows:
        table.add_row(key, val)

    console.print(table)


@app.command()
def diagnose(
    symbol: str = typer.Argument(..., help="Ticker symbol to diagnose, e.g. HPG"),
) -> None:
    """Diagnose what data vnstock returns for a symbol.

    Prints the columns, row counts, and sample data for each fetch method.
    Use this to debug missing nodes (industry, officers, etc.).
    """
    import asyncio

    settings = _settings()
    from ourgraph.ingest.vnstock_fetcher import VnstockFetcher

    fetcher = VnstockFetcher(settings.vnstock)
    sym = symbol.upper()

    async def _run() -> None:

        # Company overview
        df = fetcher.get_company_overview(sym)
        _print_section(f"Company Overview: {sym}", df)

        # Officers
        df = fetcher.get_officers(sym)
        _print_section(f"Officers: {sym}", df)

        # Shareholders
        df = fetcher.get_shareholders(sym)
        _print_section(f"Shareholders: {sym}", df)

        # Subsidiaries
        df = fetcher.get_subsidiaries(sym)
        _print_section(f"Subsidiaries: {sym}", df)

        # Financial ratios
        df = fetcher.get_financial_ratios(sym)
        _print_section(f"Financial Ratios: {sym}", df)

        # Price history
        df = fetcher.get_price_history(sym, start="2025-01-01")
        _print_section(f"Price History (2025): {sym}", df)

    def _print_section(title: str, df: pl.DataFrame) -> None:
        if df.is_empty():
            console.print(
                Panel("[yellow]EMPTY — no data returned[/yellow]", title=title),
            )
            return
        console.print(
            Panel(
                f"[green]{len(df)} rows × {len(df.columns)} columns[/green]\n"
                f"Columns: {', '.join(df.columns)}\n"
                f"Schema: {dict(df.schema)}",
                title=title,
            ),
        )
        console.print(df.head(3).to_pandas().to_string(index=False))
        console.print()

    with console.status(f"[bold green]Diagnosing {sym}...[/bold green]"):
        asyncio.run(_run())


@app.command()
def quality() -> None:
    """Run quality checks on the knowledge graph.

    Checks for:
    - Duplicate nodes (Company, Person, StockPrice, etc.)
    - Missing relationships (sector/industry links, isolated companies)
    - Subsidiary data quality
    - Shareholder classification (corporate vs individual)
    - Data completeness (prices, financials, indicators)
    """
    from ourgraph.quality import run_quality_sync

    issues = run_quality_sync()
    if issues:
        console.print(f"\n[red]Found {len(issues)} issue(s) to fix![/red]")
    else:
        console.print("\n[green]✓ No quality issues found![/green]")


if __name__ == "__main__":
    app()
