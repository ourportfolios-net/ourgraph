"""Daily batch scheduler.

Uses APScheduler to trigger the pipeline on a cron schedule.
The cron expression is fully configurable via SCHEDULER_CRON in .env.

Default: "0 7 * * 1-5" → every weekday at 07:00 local time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ourgraph.ingest.pipeline import Pipeline

if TYPE_CHECKING:
    from ourgraph.config import AppSettings

logger = logging.getLogger(__name__)
CRON_FIELD_COUNT = 5


def _parse_cron(expr: str) -> CronTrigger:
    """Parse a standard 5-field cron expression into an APScheduler CronTrigger.

    Fields: minute hour day_of_month month day_of_week
    """
    parts = expr.strip().split()
    if len(parts) != CRON_FIELD_COUNT:
        message = f"SCHEDULER_CRON must be a 5-field cron expression, got: {expr!r}"
        raise ValueError(
            message,
        )
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


class DailyScheduler:
    """Wraps APScheduler to run the pipeline on a cron schedule.

    Usage::

        scheduler = DailyScheduler(settings)
        scheduler.start()
        # block forever
        asyncio.get_event_loop().run_forever()
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Register the job and start the scheduler."""
        trigger = _parse_cron(self._settings.scheduler.cron)
        self._scheduler.add_job(
            self._run_daily_update,
            trigger=trigger,
            id="daily_update",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started — cron: %s",
            self._settings.scheduler.cron,
        )

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def _run_daily_update(self) -> None:
        logger.info("Scheduled daily update triggered")
        pipeline = Pipeline(self._settings)
        try:
            await pipeline.run_daily_update()
        except Exception:
            logger.exception("Daily update failed")


def run_scheduler(settings: AppSettings) -> None:
    """Start the scheduler and block until interruption.

    Call from the CLI.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    scheduler = DailyScheduler(settings)
    scheduler.start()

    try:
        logger.info("Scheduler running. Press Ctrl+C to stop.")
        loop.run_forever()
    except KeyboardInterrupt:
        scheduler.stop()
    finally:
        loop.close()
