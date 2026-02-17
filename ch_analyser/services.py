from ch_analyser.client import CHClient
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)

EXCLUDED_DATABASES = ("system", "INFORMATION_SCHEMA", "information_schema")


class AnalysisService:
    def __init__(self, client: CHClient):
        self._client = client

    def get_tables(self) -> list[dict]:
        excluded = list(EXCLUDED_DATABASES)

        # 1. Table sizes from system.parts (all databases except system ones)
        sizes = {}
        sizes_bytes = {}
        try:
            rows = self._client.execute(
                "SELECT database, table, "
                "formatReadableSize(sum(bytes_on_disk)) AS size, "
                "sum(bytes_on_disk) AS size_bytes "
                "FROM system.parts "
                "WHERE active AND database NOT IN %(excluded)s "
                "GROUP BY database, table ORDER BY database, table",
                {"excluded": excluded},
            )
            for r in rows:
                key = f"{r['database']}.{r['table']}"
                sizes[key] = r["size"]
                sizes_bytes[key] = r["size_bytes"]
        except Exception as e:
            logger.warning("Failed to get table sizes: %s", e)

        # 2. Last SELECT per table from query_log
        last_selects = {}
        try:
            rows = self._client.execute(
                "SELECT arrayJoin(tables) AS table_name, max(event_time) AS last_select "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' AND query_kind = 'Select' "
                "GROUP BY table_name",
            )
            for r in rows:
                tname = r["table_name"]
                last_selects[tname] = str(r["last_select"])
        except Exception as e:
            logger.warning("Failed to get last SELECT times: %s", e)

        # 3. Last INSERT per table from query_log
        last_inserts = {}
        try:
            rows = self._client.execute(
                "SELECT arrayJoin(tables) AS table_name, max(event_time) AS last_insert "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' AND query_kind = 'Insert' "
                "GROUP BY table_name",
            )
            for r in rows:
                tname = r["table_name"]
                last_inserts[tname] = str(r["last_insert"])
        except Exception as e:
            logger.warning("Failed to get last INSERT times: %s", e)

        # Merge results
        all_tables = set(sizes.keys()) | set(last_selects.keys()) | set(last_inserts.keys())
        # Filter out system databases from query_log results too
        all_tables = {t for t in all_tables if not any(t.startswith(f"{db}.") for db in EXCLUDED_DATABASES)}

        result = []
        for table in all_tables:
            result.append({
                "name": table,
                "size": sizes.get(table, "0 B"),
                "size_bytes": sizes_bytes.get(table, 0),
                "last_select": last_selects.get(table, "-"),
                "last_insert": last_inserts.get(table, "-"),
            })
        result.sort(key=lambda t: t["size_bytes"], reverse=True)
        return result

    def get_columns(self, full_table_name: str) -> list[dict]:
        if "." in full_table_name:
            db, table_name = full_table_name.split(".", 1)
        else:
            db, table_name = "default", full_table_name

        try:
            rows = self._client.execute(
                "SELECT "
                "  c.name AS name, "
                "  c.type AS type, "
                "  c.compression_codec AS codec, "
                "  formatReadableSize(sum(pc.column_bytes_on_disk)) AS size, "
                "  sum(pc.column_bytes_on_disk) AS size_bytes "
                "FROM system.columns AS c "
                "LEFT JOIN ( "
                "  SELECT database, table, column, "
                "    sum(column_bytes_on_disk) AS column_bytes_on_disk "
                "  FROM system.parts_columns "
                "  WHERE active AND database = %(db)s AND table = %(table)s "
                "  GROUP BY database, table, column "
                ") AS pc "
                "ON c.name = pc.column AND c.table = pc.table AND c.database = pc.database "
                "WHERE c.database = %(db)s AND c.table = %(table)s "
                "GROUP BY c.name, c.type, c.compression_codec "
                "ORDER BY size_bytes DESC",
                {"db": db, "table": table_name},
            )
            return rows
        except Exception as e:
            logger.error("Failed to get columns for %s: %s", full_table_name, e)
            return []

    def get_disk_info(self) -> list[dict]:
        try:
            rows = self._client.execute(
                "SELECT "
                "  name, "
                "  formatReadableSize(total_space) AS total, "
                "  formatReadableSize(total_space - free_space) AS used, "
                "  total_space AS total_bytes, "
                "  (total_space - free_space) AS used_bytes, "
                "  round((total_space - free_space) * 100.0 / total_space, 1) AS usage_percent "
                "FROM system.disks"
            )
            return rows
        except Exception as e:
            logger.warning("Failed to get disk info: %s", e)
            return []

    def get_query_history(self, full_table_name: str, limit: int = 200) -> list[dict]:
        try:
            rows = self._client.execute(
                "SELECT event_time, user, query_kind, query "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' "
                "AND has(tables, %(table)s) "
                "ORDER BY event_time DESC "
                "LIMIT %(limit)s",
                {"table": full_table_name, "limit": limit},
            )
            for r in rows:
                r["event_time"] = str(r["event_time"])
            return rows
        except Exception as e:
            logger.error("Failed to get query history for %s: %s", full_table_name, e)
            return []
