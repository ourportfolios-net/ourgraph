"""CLI entry point.

All commands load config from environment / .env.
Nothing is hardcoded — flags only override defaults.

Commands:
  ourgraph ingest full          Run the full pipeline
  ourgraph ingest daily         Run today's price update
  ourgraph ingest symbol ACB    Ingest a single symbol
  ourgraph schedule             Start the daily scheduler daemon
  ourgraph query "..."          GraphRAG query
  ourgraph graph peers ACB      Get sector peers
  ourgraph graph subs VCB       Get subsidiaries
  ourgraph graph prices ACB     Get price history
  ourgraph setup                First-time setup (indices + Graphiti init)
  ourgraph info                 Print effective configuration
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
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
    help="Optional list of symbols. Defaults to all.",
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
    """First-time setup: create graph indices and initialise Graphiti.

    Run this once after starting FalkorDB for the first time.
    """
    settings = _settings()

    async def _run() -> object:
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
        return None

    asyncio.run(_run())


# ===========================================================================
# Ingest commands
# ===========================================================================


@ingest_app.command("full")
def ingest_full(symbols: list[str] = INGEST_SYMBOLS_ARG) -> None:
    """Run the full pipeline (all symbols, all data)."""
    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    pipeline = Pipeline(settings)
    with console.status("[bold green]Running full pipeline...[/bold green]"):
        asyncio.run(pipeline.run_full(symbols=symbols or None))
    console.print("[green]✓ Full pipeline complete[/green]")


@ingest_app.command("daily")
def ingest_daily() -> None:
    """Run the daily price update (lightweight)."""
    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    pipeline = Pipeline(settings)
    with console.status("[bold green]Running daily update...[/bold green]"):
        asyncio.run(pipeline.run_daily_update())
    console.print("[green]✓ Daily update complete[/green]")


@ingest_app.command("symbol")
def ingest_symbol(symbol: str = typer.Argument(..., help="Ticker symbol, e.g. VCB")) -> None:
    """Ingest all data for a single symbol."""
    settings = _settings()
    from ourgraph.ingest.pipeline import Pipeline

    pipeline = Pipeline(settings)
    with console.status(f"[bold green]Ingesting {symbol}...[/bold green]"):
        asyncio.run(pipeline.run_full(symbols=[symbol]))
    console.print(f"[green]✓ {symbol} ingested[/green]")


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
    num_results: int = typer.Option(10, "--results", "-n", help="Max results"),
) -> None:
    """Run a GraphRAG query against the temporal knowledge graph."""
    settings = _settings()
    from ourgraph.graphiti_layer.search import GraphRAGSearch

    async def _run() -> object:
        search = await GraphRAGSearch.create(settings)
        results = await search.query(question, num_results=num_results)
        await search.close()
        return results

    with console.status("[bold green]Querying knowledge graph...[/bold green]"):
        results = asyncio.run(_run())

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Results for: {question}", show_lines=True)
    table.add_column("Fact", style="white", max_width=80)
    table.add_column("Valid At", style="cyan", width=12)
    table.add_column("Invalid At", style="red", width=12)

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
    limit: int = typer.Option(20, "--limit", "-l"),
) -> None:
    """List sector peers for a symbol."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> object:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_sector_peers(symbol, limit=limit)

    df = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No peers found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("subs")
def graph_subs(symbol: str = typer.Argument(..., help="Ticker symbol")) -> None:
    """List direct subsidiaries of a company."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> object:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_subsidiaries(symbol)

    df = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No subsidiaries found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("shareholders")
def graph_shareholders(symbol: str = typer.Argument(..., help="Ticker symbol")) -> None:
    """List major shareholders of a company."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> object:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_shareholders(symbol)

    df = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No shareholders found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("prices")
def graph_prices(
    symbol: str = typer.Argument(..., help="Ticker symbol"),
    start: str = typer.Option(None, "--start", "-s", help="Start date YYYY-MM-DD"),
    end: str = typer.Option(None, "--end", "-e", help="End date YYYY-MM-DD"),
) -> None:
    """Show price history for a symbol."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> object:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_price_history(symbol, start=start, end=end)

    df = asyncio.run(_run())
    if df.is_empty():
        console.print(f"[yellow]No price data found for {symbol}[/yellow]")
        return
    console.print(df.to_pandas().tail(30).to_string(index=False))


@graph_app.command("cross-shareholding")
def graph_cross_shareholding(
    limit: int = typer.Option(50, "--limit", "-l"),
) -> None:
    """Find cross-shareholding pairs in the graph."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> object:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.find_cross_shareholding(limit=limit)

    df = asyncio.run(_run())
    if df.is_empty():
        console.print("[yellow]No cross-shareholding pairs found.[/yellow]")
        return
    console.print(df.to_pandas().to_string(index=False))


@graph_app.command("stats")
def graph_stats() -> None:
    """Print high-level graph counts to validate ingestion progress."""
    settings = _settings()
    from ourgraph.graph.queries import GraphQueries

    async def _run() -> object:
        async with GraphQueries.from_settings(settings.falkordb) as queries:
            return await queries.get_graph_stats()

    stats = asyncio.run(_run())

    table = Table(title="Graph Stats", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="white", justify="right")
    table.add_row("Distinct trading tickers", str(stats.get("distinct_symbols", 0)))
    table.add_row("All company entities", str(stats.get("companies", 0)))
    table.add_row("StockPrice nodes", str(stats.get("stock_prices", 0)))
    table.add_row(
        "Distinct symbols with prices",
        str(stats.get("stock_price_symbols", 0)),
    )
    table.add_row("FinancialStatement nodes", str(stats.get("financial_statements", 0)))
    table.add_row("FinancialIndicator nodes", str(stats.get("financial_indicators", 0)))
    console.print(table)


@graph_app.command("dedupe")
def graph_dedupe() -> None:
    """Remove duplicate nodes by natural keys and rewire relationships."""
    settings = _settings()
    from ourgraph.graph.builder import GraphBuilder

    async def _run() -> object:
        async with GraphBuilder.from_settings(settings.falkordb) as builder:
            return await builder.deduplicate_nodes()

    with console.status("[bold green]Deduplicating graph nodes...[/bold green]"):
        stats = asyncio.run(_run())

    table = Table(title="Deduplication Result", show_lines=True)
    table.add_column("Node Type", style="cyan")
    table.add_column("Removed", style="white", justify="right")
    table.add_row("Company", str(stats.get("company", 0)))
    table.add_row("StockPrice", str(stats.get("stock_price", 0)))
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

    async def _run() -> object:
        async with GraphBuilder.from_settings(settings.falkordb) as builder:
            return await builder.clear_graph()

    with console.status("[bold red]Clearing graph data...[/bold red]"):
        result = asyncio.run(_run())

    table = Table(title="Graph Clear Result", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="white", justify="right")
    table.add_row("Deleted nodes", str(result.get("deleted_nodes", 0)))
    table.add_row("Deleted relationships", str(result.get("deleted_relationships", 0)))
    console.print(table)


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
            v[:MASK_PREFIX_LENGTH] + "****"
            if len(v) > MASK_PREFIX_LENGTH
            else "****"
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
        (
            "Supabase DB URL",
            _mask(settings.supabase.supabase_db_url)
            if settings.supabase.supabase_db_url
            else "(not set)",
        ),
    ]

    for key, val in rows:
        table.add_row(key, val)

    console.print(table)


if __name__ == "__main__":
    app()
