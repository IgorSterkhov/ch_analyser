"""Scheduler — runs monitoring collection periodically."""

import asyncio

from nicegui import run

from ch_analyser.config import ConnectionManager
from ch_analyser.monitoring.collector import Collector
from ch_analyser.monitoring.store import MonitoringStore
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)

_task: asyncio.Task | None = None


async def _collection_loop(collector: Collector, store: MonitoringStore, retention_days: int):
    """Run collection immediately, then every hour."""
    while True:
        try:
            results = await run.io_bound(collector.collect_all)
            logger.info("Monitoring collection done: %s", results)
        except Exception as e:
            logger.error("Monitoring collection error: %s", e)

        try:
            await run.io_bound(store.cleanup_expired, retention_days)
        except Exception as e:
            logger.error("Monitoring cleanup error: %s", e)

        await asyncio.sleep(3600)


def start_scheduler(conn_manager: ConnectionManager, store: MonitoringStore, retention_days: int = 365):
    global _task
    if _task is not None:
        logger.warning("Scheduler already running")
        return
    collector = Collector(conn_manager, store)
    _task = asyncio.ensure_future(_collection_loop(collector, store, retention_days))
    logger.info("Monitoring scheduler started (retention=%d days)", retention_days)


def stop_scheduler():
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
        logger.info("Monitoring scheduler stopped")
