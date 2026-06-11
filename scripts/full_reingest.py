#!/usr/bin/env python3
"""Full re-ingestion pipeline for ourgraph.

Usage:
    uv run python3 scripts/full_reingest.py

Clears the graph, ingests a batch of closely intertwined tickers
with full data (company profile, prices, financials, officers,
subsidiaries, shareholders), then runs scrapers to discover
lending, related-party, and joint-venture relationships.

Expects:
  - FalkorDB running (docker compose up -d)
  - vnstock API key in .env
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ourgraph.config import get_settings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.graph.discovery import GraphDiscovery
from ourgraph.graph.queries import GraphQueries
from ourgraph.ingest.pipeline import Pipeline

# Inline the ticker list to avoid cross-package import issues
exec(open(Path(__file__).parent / "ticker_batch.py").read())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("reingest")


async def main() -> None:
    t0 = time.monotonic()
    settings = get_settings()
    symbols = INTERTWINED_TICKERS
    logger.info("Selected %d intertwined tickers for ingestion", len(symbols))

    # ── Step 0: Clear the graph ───────────────────────────────────────
    logger.info("Clearing graph...")
    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        stats = await builder.clear_graph()
        logger.info(
            "Cleared: %d nodes, %d relationships deleted",
            stats["deleted_nodes"],
            stats["deleted_relationships"],
        )
        await builder.ensure_indices()

    # ── Step 1: Full pipeline ─────────────────────────────────────────
    pipeline = Pipeline(settings)
    logger.info("Running full pipeline for %d symbols...", len(symbols))
    await pipeline.run_full(symbols, resume=False)
    t_pipe = time.monotonic()
    logger.info("Pipeline complete in %.0fs", t_pipe - t0)

    # ── Step 2: Scrapers ──────────────────────────────────────────────
    logger.info("Running structured scrapers...")
    scrape_results = await pipeline.run_scrapers(
        symbols=symbols,
        cafef=True,
        hnx_bonds=True,
        scic=True,
        max_cafef_symbols=len(symbols),
    )
    logger.info("Scrapers: %s", scrape_results)

    # ── Step 3: Discovery ─────────────────────────────────────────────
    logger.info("Running graph discovery...")
    async with GraphQueries.from_settings(settings.falkordb) as queries:
        discovery = GraphDiscovery(queries)
        discovered = await discovery.discover_all(include_correlation=False)
        total = sum(
            len(v) for v in discovered.values()
            if isinstance(v, list)
        )
        logger.info("Discovery found %d hidden relationships", total)

    # ── Step 4: Final stats ───────────────────────────────────────────
    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        metrics = [
            ("Company nodes", "MATCH (c:Company) RETURN count(c)"),
            ("Person nodes", "MATCH (p:Person) RETURN count(p)"),
            ("StockPrice nodes", "MATCH (s:StockPrice) RETURN count(s)"),
            ("SUBSIDIARY_OF", "MATCH ()-[r:SUBSIDIARY_OF]->() RETURN count(r)"),
            ("IS_OFFICER", "MATCH ()-[r:IS_OFFICER]->() RETURN count(r)"),
            ("HOLDS_STAKE_IN", "MATCH ()-[r:HOLDS_STAKE_IN]->() RETURN count(r)"),
            ("AUDITED_BY", "MATCH ()-[r:AUDITED_BY]->() RETURN count(r)"),
            ("COMPETES_WITH", "MATCH ()-[r:COMPETES_WITH]->() RETURN count(r)"),
            ("LENDS_TO", "MATCH ()-[r:LENDS_TO]->() RETURN count(r)"),
            ("RELATED_PARTY_TRANSACTION", "MATCH ()-[r:RELATED_PARTY_TRANSACTION]->() RETURN count(r)"),
            ("HAS_JOINT_VENTURE_WITH", "MATCH ()-[r:HAS_JOINT_VENTURE_WITH]->() RETURN count(r)"),
            ("UNDERWRITTEN_BY", "MATCH ()-[r:UNDERWRITTEN_BY]->() RETURN count(r)"),
            ("GUARANTEES", "MATCH ()-[r:GUARANTEES]->() RETURN count(r)"),
            ("HAS_BUSINESS_COOPERATION", "MATCH ()-[r:HAS_BUSINESS_COOPERATION]->() RETURN count(r)"),
            ("STATE_OWNS", "MATCH ()-[r:STATE_OWNS]->() RETURN count(r)"),
            ("MacroIndicator", "MATCH (m:MacroIndicator) RETURN count(m)"),
        ]
        logger.info("─── Graph Stats ───")
        for label, query in metrics:
            rows = await builder._run(query)
            count = int(rows[0][0]) if rows else 0
            logger.info("  %-35s %d", label, count)

    t_total = time.monotonic()
    logger.info("Total time: %.0fs (%.0f min)", t_total - t0, (t_total - t0) / 60)


if __name__ == "__main__":
    asyncio.run(main())
