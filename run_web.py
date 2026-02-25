#!/usr/bin/env python3
"""Entry point for the ClickHouse Analyser web interface."""

import argparse
import logging

from ch_analyser.logging_config import setup_logging
from ch_analyser.web.app import start

if __name__ in {"__main__", "__mp_main__"}:
    parser = argparse.ArgumentParser(description="ClickHouse Analyser Web UI")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging (all queries visible)")
    args = parser.parse_args()
    setup_logging(logging.DEBUG if args.debug else None)
    start()
