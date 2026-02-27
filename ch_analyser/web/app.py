"""NiceGUI web application bootstrap for ClickHouse Analyser."""

from nicegui import ui, app

import ch_analyser.web.state as state
from ch_analyser.monitoring.store import MonitoringStore
from ch_analyser.monitoring.scheduler import start_scheduler, stop_scheduler
from ch_analyser.logging_config import get_logger

# Import pages so their @ui.page decorators register routes
import ch_analyser.web.pages.login  # noqa: F401
import ch_analyser.web.pages.main  # noqa: F401

logger = get_logger(__name__)


@app.on_startup
async def _startup():
    db_path = state.app_settings.get("MONITORING_DB_PATH")
    store = MonitoringStore(db_path=db_path)
    state.monitoring_store = store
    retention = state.app_settings.get_int("MONITORING_RETENTION_DAYS", 365)
    start_scheduler(state.conn_manager, store, retention_days=retention)
    logger.info("Monitoring started (db=%s, retention=%d)", db_path, retention)


@app.on_shutdown
async def _shutdown():
    stop_scheduler()
    if state.monitoring_store:
        state.monitoring_store.close()
        state.monitoring_store = None
    logger.info("Monitoring stopped")


def start():
    """Run the NiceGUI web server."""
    ui.run(port=8080, title='ClickHouse Analyser', storage_secret='ch-analyser-secret')
