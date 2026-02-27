"""Collector — gathers monitoring data from all configured ClickHouse servers."""

from datetime import datetime

from ch_analyser.client import CHClient
from ch_analyser.config import ConnectionManager
from ch_analyser.monitoring.store import MonitoringStore
from ch_analyser.services import AnalysisService
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


class Collector:
    def __init__(self, conn_manager: ConnectionManager, store: MonitoringStore):
        self._conn_manager = conn_manager
        self._store = store

    def collect_all(self) -> dict[str, str]:
        """Collect disk and table data from every configured connection.

        Creates a temporary CHClient per connection (does not touch the user's
        active connection in state.client).

        Returns dict mapping server_name -> status string.
        """
        results: dict[str, str] = {}
        connections = self._conn_manager.list_connections()
        if not connections:
            logger.info("No connections configured, skipping collection")
            return results

        ts = datetime.now()
        ca_cert = self._conn_manager.ca_cert

        for cfg in connections:
            try:
                cfg.ca_cert = ca_cert
                client = CHClient(cfg)
                client.connect()
                try:
                    svc = AnalysisService(client)

                    disks = svc.get_disk_usage_bytes()
                    self._store.insert_server_disk(ts, cfg.name, disks)

                    tables = svc.get_table_sizes_bytes()
                    self._store.insert_table_sizes(ts, cfg.name, tables)

                    results[cfg.name] = "ok"
                    logger.info("Collected data from %s: %d disks, %d tables",
                                cfg.name, len(disks), len(tables))
                finally:
                    client.disconnect()
            except Exception as e:
                results[cfg.name] = f"error: {e}"
                logger.warning("Failed to collect from %s: %s", cfg.name, e)

        return results
