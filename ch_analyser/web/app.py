"""NiceGUI web application bootstrap for ClickHouse Analyser."""

from nicegui import ui

# Import state module to ensure it's initialized
import ch_analyser.web.state  # noqa: F401

# Import pages so their @ui.page decorators register routes
import ch_analyser.web.pages.login  # noqa: F401
import ch_analyser.web.pages.main  # noqa: F401


def start():
    """Run the NiceGUI web server."""
    ui.run(port=8080, title='ClickHouse Analyser', storage_secret='ch-analyser-secret')
