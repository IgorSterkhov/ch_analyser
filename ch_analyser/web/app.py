"""NiceGUI web application bootstrap for ClickHouse Analyser."""

from nicegui import app, ui

from ch_analyser.config import ConnectionManager

# Import pages so their @ui.page decorators register routes
import ch_analyser.web.pages.connections  # noqa: F401
import ch_analyser.web.pages.tables  # noqa: F401
import ch_analyser.web.pages.columns  # noqa: F401


def _init_storage():
    """Initialize shared application state on startup."""
    storage = app.storage.general
    if 'conn_manager' not in storage:
        storage['conn_manager'] = ConnectionManager()
    storage.setdefault('client', None)
    storage.setdefault('service', None)
    storage.setdefault('active_connection_name', None)


app.on_startup(_init_storage)


def start():
    """Run the NiceGUI web server."""
    ui.run(port=8080, title='ClickHouse Analyser', storage_secret='ch-analyser-secret')
