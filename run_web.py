#!/usr/bin/env python3
"""Entry point for the ClickHouse Analyser web interface."""

from ch_analyser.logging_config import setup_logging
from ch_analyser.web.app import start

if __name__ in {"__main__", "__mp_main__"}:
    setup_logging()
    start()
