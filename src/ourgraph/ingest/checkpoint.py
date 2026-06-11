"""Checkpoint manager for ingestion resume/pause."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

CHECKPOINT_VERSION = 1


class CheckpointManager:
    """Manages a JSON checkpoint file for tracking ingestion progress.

    Supports pause/resume, failure tracking with retries, and graceful shutdown.
    All writes are atomic (write to .tmp, rename over original).
    """

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any] | None:
        """Read checkpoint from disk. Returns None if missing or corrupt."""
        if not os.path.isfile(self.path):
            return None
        try:
            with open(self.path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt checkpoint file %s: %s", self.path, exc)
            return None

    def save(self, cp: dict[str, Any]) -> None:
        """Atomically write checkpoint to disk."""
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cp, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def reset(self) -> None:
        """Delete the checkpoint file if it exists."""
        try:
            if os.path.isfile(self.path):
                os.remove(self.path)
            tmp = self.path + ".tmp"
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError as exc:
            logger.warning("Failed to remove checkpoint: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure(self) -> dict[str, Any]:
        """Load existing checkpoint or create a fresh one."""
        cp = self.load()
        if cp is not None:
            return cp
        return {
            "version": CHECKPOINT_VERSION,
            "started_at": datetime.now(UTC).isoformat(),
            "last_updated": datetime.now(UTC).isoformat(),
            "total_symbols": 0,
            "completed": [],
            "failed": [],
        }

    def _touch(self, cp: dict[str, Any]) -> None:
        cp["last_updated"] = datetime.now(UTC).isoformat()

    # ------------------------------------------------------------------
    # Mutation methods
    # ------------------------------------------------------------------

    def init(self, total_symbols: int) -> dict[str, Any]:
        """Create a fresh checkpoint (replaces any existing)."""
        cp = {
            "version": CHECKPOINT_VERSION,
            "started_at": datetime.now(UTC).isoformat(),
            "last_updated": datetime.now(UTC).isoformat(),
            "total_symbols": total_symbols,
            "completed": [],
            "failed": [],
        }
        self.save(cp)
        return cp

    def mark_completed(self, symbol: str) -> None:
        cp = self._ensure()
        if symbol not in cp["completed"]:
            cp["completed"].append(symbol)
        # Also remove from failed if present
        cp["failed"] = [e for e in cp["failed"] if e["symbol"] != symbol]
        self._touch(cp)
        self.save(cp)

    def mark_failed(self, symbol: str, error: str) -> None:
        cp = self._ensure()
        # Find existing entry
        found = False
        for entry in cp["failed"]:
            if entry["symbol"] == symbol:
                entry["error"] = error
                entry["retries"] += 1
                found = True
                break
        if not found:
            cp["failed"].append(
                {
                    "symbol": symbol,
                    "error": error,
                    "retries": 1,
                },
            )
        self._touch(cp)
        self.save(cp)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def is_completed(self, symbol: str) -> bool:
        cp = self.load()
        if cp is None:
            return False
        return symbol in cp.get("completed", [])

    def get_incomplete(self, all_symbols: list[str]) -> list[str]:
        cp = self.load()
        if cp is None:
            return list(all_symbols)
        completed_set = set(cp.get("completed", []))
        return [s for s in all_symbols if s not in completed_set]

    def get_retryable(self, max_retries: int = 3) -> list[str]:
        cp = self.load()
        if cp is None or not cp.get("failed"):
            return []
        return [e["symbol"] for e in cp["failed"] if e.get("retries", 0) < max_retries]

    def print_status(self) -> None:
        cp = self.load()
        if cp is None:
            print("No checkpoint found.")
            return
        total = cp.get("total_symbols", 0)
        completed = len(cp.get("completed", []))
        failed_entries = cp.get("failed", [])
        print("Checkpoint status:")
        print(f"  Total symbols:  {total}")
        print(
            f"  Completed:      {completed} ({completed / total * 100:.1f}% done)"
            if total
            else "  Completed:      0",
        )
        if failed_entries:
            print(f"  Failed:         {len(failed_entries)}")
            for e in failed_entries:
                print(
                    f"    - {e['symbol']} ({e.get('retries', 0)}×): {e.get('error', '?')}",
                )
        print(f"  Last updated:   {cp.get('last_updated', '?')}")
