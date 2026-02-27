"""MonitoringStore — DuckDB wrapper for monitoring snapshots."""

import os
import threading
from datetime import datetime

import duckdb

from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)

_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS server_disk_snapshots (
        ts          TIMESTAMP NOT NULL,
        year        SMALLINT NOT NULL,
        server_name VARCHAR NOT NULL,
        disk_name   VARCHAR NOT NULL,
        total_bytes BIGINT NOT NULL,
        used_bytes  BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS table_disk_snapshots (
        ts              TIMESTAMP NOT NULL,
        year            SMALLINT NOT NULL,
        server_name     VARCHAR NOT NULL,
        database_name   VARCHAR NOT NULL,
        table_name      VARCHAR NOT NULL,
        size_bytes      BIGINT NOT NULL
    )
    """,
]

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_server_disk_ts ON server_disk_snapshots (server_name, ts)",
    "CREATE INDEX IF NOT EXISTS idx_table_disk_ts ON table_disk_snapshots (server_name, ts)",
]


class MonitoringStore:
    def __init__(self, db_path: str = "data/monitoring.duckdb"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = duckdb.connect(db_path)
        self._init_schema()
        logger.info("MonitoringStore opened: %s", db_path)

    def _init_schema(self):
        with self._lock:
            for sql in _SCHEMA_SQL:
                self._conn.execute(sql)
            for sql in _INDEX_SQL:
                self._conn.execute(sql)

    def close(self):
        with self._lock:
            self._conn.close()
        logger.info("MonitoringStore closed")

    # ── Insert (idempotent — skip if hour already recorded) ──

    def insert_server_disk(self, ts: datetime, server_name: str, disks: list[dict]):
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        year = hour_ts.year
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM server_disk_snapshots "
                "WHERE server_name = ? AND ts = ? LIMIT 1",
                [server_name, hour_ts],
            ).fetchone()
            if existing:
                return
            for d in disks:
                self._conn.execute(
                    "INSERT INTO server_disk_snapshots (ts, year, server_name, disk_name, total_bytes, used_bytes) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [hour_ts, year, server_name, d["name"], d["total_bytes"], d["used_bytes"]],
                )

    def insert_table_sizes(self, ts: datetime, server_name: str, tables: list[dict]):
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        year = hour_ts.year
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM table_disk_snapshots "
                "WHERE server_name = ? AND ts = ? LIMIT 1",
                [server_name, hour_ts],
            ).fetchone()
            if existing:
                return
            for t in tables:
                self._conn.execute(
                    "INSERT INTO table_disk_snapshots (ts, year, server_name, database_name, table_name, size_bytes) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [hour_ts, year, server_name, t["database"], t["table"], t["size_bytes"]],
                )

    # ── Query (for dashboard) ──

    def get_server_disk_latest(self) -> list[dict]:
        """Last snapshot per server (across all disks summed)."""
        with self._lock:
            rows = self._conn.execute("""
                WITH latest AS (
                    SELECT server_name, max(ts) AS max_ts
                    FROM server_disk_snapshots
                    GROUP BY server_name
                )
                SELECT s.server_name, s.ts,
                       sum(s.total_bytes) AS total_bytes,
                       sum(s.used_bytes) AS used_bytes
                FROM server_disk_snapshots s
                JOIN latest l ON s.server_name = l.server_name AND s.ts = l.max_ts
                GROUP BY s.server_name, s.ts
                ORDER BY s.server_name
            """).fetchall()
            cols = ["server_name", "ts", "total_bytes", "used_bytes"]
            return [dict(zip(cols, r)) for r in rows]

    def get_server_disk_history(self, days: int = 30) -> list[dict]:
        """Time series of disk usage per server (sum of all disks)."""
        with self._lock:
            rows = self._conn.execute(f"""
                SELECT server_name, ts,
                       sum(total_bytes) AS total_bytes,
                       sum(used_bytes) AS used_bytes
                FROM server_disk_snapshots
                WHERE ts >= now() - INTERVAL '{int(days)} days'
                GROUP BY server_name, ts
                ORDER BY server_name, ts
            """).fetchall()
            cols = ["server_name", "ts", "total_bytes", "used_bytes"]
            return [dict(zip(cols, r)) for r in rows]

    def get_table_disk_latest(self, server_name: str) -> list[dict]:
        """Latest table sizes for a specific server."""
        with self._lock:
            rows = self._conn.execute("""
                WITH latest AS (
                    SELECT max(ts) AS max_ts
                    FROM table_disk_snapshots
                    WHERE server_name = ?
                )
                SELECT database_name, table_name, size_bytes
                FROM table_disk_snapshots t
                JOIN latest l ON t.ts = l.max_ts
                WHERE t.server_name = ?
                ORDER BY size_bytes DESC
            """, [server_name, server_name]).fetchall()
            cols = ["database_name", "table_name", "size_bytes"]
            return [dict(zip(cols, r)) for r in rows]

    def get_table_disk_history(self, server_name: str, days: int = 30, top_n: int = 30) -> list[dict]:
        """Time series of table sizes (top-N + 'other') for a server."""
        with self._lock:
            # Find top-N tables by latest snapshot
            top_tables = self._conn.execute("""
                WITH latest AS (
                    SELECT max(ts) AS max_ts
                    FROM table_disk_snapshots
                    WHERE server_name = ?
                )
                SELECT database_name || '.' || table_name AS full_name
                FROM table_disk_snapshots t
                JOIN latest l ON t.ts = l.max_ts
                WHERE t.server_name = ?
                ORDER BY size_bytes DESC
                LIMIT ?
            """, [server_name, server_name, top_n]).fetchall()
            top_names = {r[0] for r in top_tables}

            rows = self._conn.execute(f"""
                SELECT ts,
                       database_name || '.' || table_name AS full_name,
                       size_bytes
                FROM table_disk_snapshots
                WHERE server_name = ?
                  AND ts >= now() - INTERVAL '{int(days)} days'
                ORDER BY ts, full_name
            """, [server_name]).fetchall()

            # Group into top-N + other
            result: list[dict] = []
            other_by_ts: dict[str, int] = {}
            for ts, full_name, size_bytes in rows:
                ts_str = str(ts)
                if full_name in top_names:
                    result.append({"ts": ts, "table_name": full_name, "size_bytes": size_bytes})
                else:
                    other_by_ts[ts_str] = other_by_ts.get(ts_str, 0) + size_bytes

            for ts_str, size in other_by_ts.items():
                result.append({"ts": datetime.fromisoformat(ts_str), "table_name": "__other__", "size_bytes": size})

            return result

    # ── Cleanup ──

    def cleanup_expired(self, retention_days: int = 365):
        """Delete snapshots older than retention_days."""
        with self._lock:
            for table in ("server_disk_snapshots", "table_disk_snapshots"):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE ts < now() - INTERVAL '{int(retention_days)} days'",
                )
        logger.info("Cleanup done (retention=%d days)", retention_days)
