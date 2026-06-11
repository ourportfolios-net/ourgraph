"""Ingest all 217 tracked stocks into FalkorDB cloud from Supabase, skipping macro.

Supports checkpoint/resume via progress.json so interrupted runs can continue.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import signal
import sys
import time

sys.path.insert(0, "src")

from ourgraph.config import AppSettings
from ourgraph.graph.builder import GraphBuilder
from ourgraph.ingest.checkpoint import CheckpointManager
from ourgraph.ingest.pipeline import Pipeline

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Ingest 217 tracked stocks into FalkorDB cloud",
)
parser.add_argument(
    "--force", "-f",
    action="store_true",
    help="Delete existing checkpoint and start fresh",
)
parser.add_argument(
    "--status", "-s",
    action="store_true",
    help="Show checkpoint progress and exit",
)
parser.add_argument(
    "--max-retries", "-r",
    type=int,
    default=3,
    help="Max retry attempts per failed symbol (default: 3)",
)

CHECKPOINT_PATH = "progress_217.json"

# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

shutdown_event = asyncio.Event()


def _handle_shutdown(*_: object) -> None:
    shutdown_event.set()
    print("\n⚠ Graceful shutdown requested — saving checkpoint...")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _get_symbols() -> list[str]:
    """Fetch the 217 tracked stock symbols from Supabase."""
    import os

    import asyncpg

    db_uri = os.environ.get("COMPANY_DB_URI", "")
    if not db_uri:
        with open("/home/dank/Documents/Codebases/ourportfolios-net/ourportfolios/.env") as f:
            for line in f:
                if line.startswith("COMPANY_DB_URI="):
                    db_uri = line.strip().split("=", 1)[1]
                    break
    if not db_uri:
        raise RuntimeError("COMPANY_DB_URI not found")

    print("Connecting to Supabase...")
    conn = await asyncpg.connect(db_uri, statement_cache_size=0, timeout=15)
    print("Fetching symbols...")
    rows = await conn.fetch("SELECT symbol FROM tickers.profile_df ORDER BY symbol")
    symbols = [r["symbol"] for r in rows]
    await conn.close()
    print(f"Got {len(symbols)} symbols")
    return symbols


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    args = parser.parse_args()
    cp = CheckpointManager(CHECKPOINT_PATH)

    # --force: nuke checkpoint
    if args.force:
        print("--force: deleting existing checkpoint")
        cp.reset()

    # --status: show progress and exit
    if args.status:
        cp.print_status()
        return

    # Register graceful shutdown handler
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_shutdown)

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    settings = AppSettings()
    pipeline = Pipeline(settings)
    symbols = await _get_symbols()
    total = len(symbols)

    print(f"Symbols to ingest: {total}")
    print(f"First 10: {symbols[:10]}")
    print(f"Last 10:  {symbols[-10:]}")
    print()

    # Load existing checkpoint or create fresh one
    checkpoint = cp.load()
    if checkpoint is None:
        cp.init(total)
        checkpoint = cp.load()
        print(f"Checkpoint created: {cp.path}")
    else:
        completed = len(checkpoint.get("completed", []))
        failed = len(checkpoint.get("failed", []))
        print(f"Resuming from checkpoint: {completed}/{total} done, {failed} failed")
        if completed >= total:
            print("All symbols already completed — running Step 3 only.")
        print()

    start = time.time()

    async with GraphBuilder.from_settings(settings.falkordb) as builder:
        await builder.ensure_indices()

        # ------------------------------------------------------------------
        # Step 1: Company overviews (always run — quick batch, not per-symbol)
        # ------------------------------------------------------------------

        incomplete = cp.get_incomplete(symbols)
        if incomplete:
            print("Step 1: Ingesting company overviews...")
            await pipeline._ingest_companies(builder, symbols)
            name_to_symbol = await pipeline._build_name_to_symbol_map(builder)
            print(f"  Name-to-symbol map: {len(name_to_symbol)} entries")
        else:
            print("Step 1: Skipped (all companies already ingested)")
            name_to_symbol = await pipeline._build_name_to_symbol_map(builder)

        # ------------------------------------------------------------------
        # Step 2: Per-symbol ingestion with checkpoint
        # ------------------------------------------------------------------

        remaining = cp.get_incomplete(symbols)
        retryable = cp.get_retryable(args.max_retries)
        retryable = [s for s in retryable if s not in remaining]

        if not remaining and not retryable:
            print("Step 2: Skipped (all symbols already ingested)")
        else:
            phase_label = "Step 2: Ingesting per-symbol data"
            if retryable:
                phase_label += f" (+ {len(retryable)} retries)"
            print(f"{phase_label}...")

            done_so_far = total - len(remaining)

            # --- Primary pass ---
            for idx, sym in enumerate(remaining, 1):
                if shutdown_event.is_set():
                    print("\nShutdown requested — stopping primary pass.")
                    break

                try:
                    await pipeline._ingest_symbol(builder, sym, name_to_symbol)
                    cp.mark_completed(sym)
                except Exception as e:
                    cp.mark_failed(sym, str(e))

                elapsed = time.time() - start
                overall = done_so_far + idx
                print(
                    f"  [{overall}/{total}] {sym}: "
                    f"{'DONE' if cp.is_completed(sym) else 'FAILED'} "
                    f"({elapsed:.0f}s elapsed)"
                )

            # --- Retry pass ---
            if not shutdown_event.is_set():
                still_retryable = cp.get_retryable(args.max_retries)
                if still_retryable:
                    print(
                        f"\nRetry pass: {len(still_retryable)} symbols "
                        f"(up to {args.max_retries} retries each)..."
                    )
                    for sym in still_retryable:
                        if shutdown_event.is_set():
                            print("\nShutdown requested — stopping retry pass.")
                            break
                        try:
                            await pipeline._ingest_symbol(builder, sym, name_to_symbol)
                            cp.mark_completed(sym)
                        except Exception as e:
                            cp.mark_failed(sym, str(e))
                        elapsed = time.time() - start
                        print(
                            f"  [retry] {sym}: "
                            f"{'DONE' if cp.is_completed(sym) else 'FAILED'} "
                            f"({elapsed:.0f}s elapsed)"
                        )

        # ------------------------------------------------------------------
        # Step 3: Deduplication + competition edges (always run)
        # ------------------------------------------------------------------

        print("\nStep 3: Deduplication + competition edges...")
        dedupe_stats = await builder.deduplicate_nodes()
        print(f"  Dedup: {dedupe_stats}")
        await builder.upsert_competes_with()

    elapsed = time.time() - start

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    checkpoint = cp.load()
    completed_total = len(checkpoint["completed"]) if checkpoint else 0
    failed_list = checkpoint["failed"] if checkpoint else []

    print(f"\n=== All done in {elapsed:.0f}s ===")
    print(f"  Completed: {completed_total}/{total}")
    if failed_list:
        print(f"  Failed:    {len(failed_list)}")
        for entry in failed_list:
            print(f"    {entry['symbol']} (retries={entry.get('retries', 0)})")
        print(f"  Re-run with --status to check progress")
    else:
        print("  No failures — removing checkpoint.")
        cp.reset()


if __name__ == "__main__":
    asyncio.run(main())
