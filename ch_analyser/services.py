import re

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

        # 3. Last INSERT per table (prefer part_log, fallback query_log + query_views_log)
        last_inserts = self._get_last_inserts(excluded)

        # 4. Replicated tables (active on multiple replicas)
        replicated = set()
        try:
            rows = self._client.execute(
                "SELECT database, table FROM system.replicas "
                "WHERE length(replica_is_active) > 1",
            )
            for r in rows:
                replicated.add(f"{r['database']}.{r['table']}")
        except Exception as e:
            logger.warning("Failed to get replicated tables: %s", e)

        # 5. DDL + TTL from system.tables
        ttl_map: dict[str, str] = {}
        try:
            rows = self._client.execute(
                "SELECT database, name, create_table_query "
                "FROM system.tables "
                "WHERE database NOT IN %(excluded)s",
                {"excluded": excluded},
            )
            for r in rows:
                ddl = r["create_table_query"] or ""
                ttl_match = re.search(
                    r'\bTTL\s+(.+?)(?=\s+(?:DELETE|TO\s+DISK|TO\s+VOLUME|RECOMPRESS|SETTINGS|ENGINE)\b|,|\Z)',
                    ddl, re.IGNORECASE,
                )
                if ttl_match:
                    full_name = f"{r['database']}.{r['name']}"
                    ttl_map[full_name] = ttl_match.group(1).strip()
        except Exception as e:
            logger.warning("Failed to get TTL info: %s", e)

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
                "replicated": table in replicated,
                "ttl": ttl_map.get(table, ""),
            })
        result.sort(key=lambda t: t["size_bytes"], reverse=True)
        return result

    def _get_last_inserts(self, excluded: list) -> dict[str, str]:
        """Get last insert time per table. Prefer part_log, fallback to query_log + query_views_log."""
        result: dict[str, str] = {}

        # Try system.part_log first (most reliable)
        try:
            rows = self._client.execute(
                "SELECT database, table, max(event_time) AS last_insert "
                "FROM system.part_log "
                "WHERE event_type = 'NewPart' AND database NOT IN %(excluded)s "
                "GROUP BY database, table",
                {"excluded": excluded},
            )
            for r in rows:
                result[f"{r['database']}.{r['table']}"] = str(r["last_insert"])
            return result
        except Exception:
            pass  # part_log not enabled, fallback below

        # Fallback: query_log
        try:
            rows = self._client.execute(
                "SELECT arrayJoin(tables) AS table_name, max(event_time) AS last_insert "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' AND query_kind = 'Insert' "
                "GROUP BY table_name",
            )
            for r in rows:
                result[r["table_name"]] = str(r["last_insert"])
        except Exception as e:
            logger.warning("Failed to get last INSERT from query_log: %s", e)

        # Fallback: query_views_log (materialized views)
        try:
            rows = self._client.execute(
                "SELECT database || '.' || view_name AS table_name, "
                "max(event_time) AS last_insert "
                "FROM system.query_views_log "
                "WHERE view_type = 'Materialized' AND status = 'QueryFinish' "
                "GROUP BY table_name",
            )
            for r in rows:
                tname = r["table_name"]
                existing = result.get(tname, "")
                new_val = str(r["last_insert"])
                if new_val > existing:
                    result[tname] = new_val
        except Exception as e:
            logger.warning("Failed to get last INSERT from query_views_log: %s", e)

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
        rows = self._client.execute(
            "SELECT "
            "  name, "
            "  formatReadableSize(total_space) AS total, "
            "  formatReadableSize(total_space - free_space) AS used, "
            "  total_space AS total_bytes, "
            "  (total_space - free_space) AS used_bytes, "
            "  if(total_space > 0, "
            "     round((total_space - free_space) * 100.0 / total_space, 1), "
            "     0) AS usage_percent "
            "FROM system.disks"
        )
        return rows

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

    def get_query_history_sql(self, full_table_name: str, limit: int = 200,
                              users: list[str] | None = None,
                              kinds: list[str] | None = None) -> str:
        """Return the SQL query used by get_query_history (with parameters substituted)."""
        parts = [
            "SELECT event_time, user, query_kind, query",
            "FROM system.query_log",
            "WHERE type = 'QueryFinish'",
            f"AND has(tables, '{full_table_name}')",
        ]
        if users:
            user_list = ', '.join(f"'{u}'" for u in users)
            parts.append(f"AND user IN ({user_list})")
        if kinds:
            kind_list = ', '.join(f"'{k}'" for k in kinds)
            parts.append(f"AND query_kind IN ({kind_list})")
        parts.append("ORDER BY event_time DESC")
        parts.append(f"LIMIT {limit}")
        return ' '.join(parts)

    def get_table_references(self) -> dict[str, list[str]]:
        """For each table, find other entities whose DDL references it."""
        excluded = list(EXCLUDED_DATABASES)
        try:
            rows = self._client.execute(
                "SELECT database, name, create_table_query "
                "FROM system.tables "
                "WHERE database NOT IN %(excluded)s",
                {"excluded": excluded},
            )
        except Exception as e:
            logger.warning("Failed to get DDL for references: %s", e)
            return {}

        entities: dict[str, str] = {}
        for r in rows:
            full_name = f"{r['database']}.{r['name']}"
            entities[full_name] = r['create_table_query'] or ''

        references: dict[str, list[str]] = {}
        for target in entities:
            db, short = target.split('.', 1)
            refs = []
            for entity_name, ddl in entities.items():
                if entity_name == target:
                    continue
                if target in ddl or short in ddl:
                    refs.append(entity_name)
            if refs:
                references[target] = sorted(refs)

        return references

    def get_column_references(self, full_table_name: str) -> dict[str, list[str]]:
        """For each column of a table, find entities whose DDL references the column name."""
        excluded = list(EXCLUDED_DATABASES)
        try:
            rows = self._client.execute(
                "SELECT database, name, create_table_query "
                "FROM system.tables "
                "WHERE database NOT IN %(excluded)s",
                {"excluded": excluded},
            )
        except Exception as e:
            logger.warning("Failed to get DDL for column references: %s", e)
            return {}

        db, short = full_table_name.split('.', 1) if '.' in full_table_name else ('default', full_table_name)

        # Only consider entities that reference our table
        referring_entities: dict[str, str] = {}
        for r in rows:
            entity = f"{r['database']}.{r['name']}"
            ddl = r['create_table_query'] or ''
            if entity != full_table_name and (full_table_name in ddl or short in ddl):
                referring_entities[entity] = ddl

        # Get column names of our table
        try:
            cols = self._client.execute(
                "SELECT name FROM system.columns WHERE database = %(db)s AND table = %(table)s",
                {"db": db, "table": short},
            )
        except Exception:
            return {}

        result: dict[str, list[str]] = {}
        for col_row in cols:
            col_name = col_row['name']
            refs = [entity for entity, ddl in referring_entities.items() if col_name in ddl]
            if refs:
                result[col_name] = sorted(refs)

        return result

    def get_tables_sql(self) -> str:
        """Return the SQL queries used by get_tables()."""
        excluded = list(EXCLUDED_DATABASES)
        excluded_str = ', '.join(f"'{db}'" for db in excluded)
        queries = [
            f"-- 1. Table sizes\n"
            f"SELECT database, table, formatReadableSize(sum(bytes_on_disk)) AS size, "
            f"sum(bytes_on_disk) AS size_bytes "
            f"FROM system.parts "
            f"WHERE active AND database NOT IN ({excluded_str}) "
            f"GROUP BY database, table ORDER BY database, table",

            f"-- 2. Last SELECT per table\n"
            f"SELECT arrayJoin(tables) AS table_name, max(event_time) AS last_select "
            f"FROM system.query_log "
            f"WHERE type = 'QueryFinish' AND query_kind = 'Select' "
            f"GROUP BY table_name",

            f"-- 3a. Last INSERT (preferred: part_log)\n"
            f"SELECT database, table, max(event_time) AS last_insert "
            f"FROM system.part_log "
            f"WHERE event_type = 'NewPart' AND database NOT IN ({excluded_str}) "
            f"GROUP BY database, table",

            f"-- 3b. Last INSERT fallback: query_log\n"
            f"SELECT arrayJoin(tables) AS table_name, max(event_time) AS last_insert "
            f"FROM system.query_log "
            f"WHERE type = 'QueryFinish' AND query_kind = 'Insert' "
            f"GROUP BY table_name",

            f"-- 3c. Last INSERT fallback: query_views_log\n"
            f"SELECT database || '.' || view_name AS table_name, "
            f"max(event_time) AS last_insert "
            f"FROM system.query_views_log "
            f"WHERE view_type = 'Materialized' AND status = 'QueryFinish' "
            f"GROUP BY table_name",

            f"-- 4. Replicated tables\n"
            f"SELECT database, table FROM system.replicas "
            f"WHERE length(replica_is_active) > 1",

            f"-- 5. DDL + TTL\n"
            f"SELECT database, name, create_table_query "
            f"FROM system.tables "
            f"WHERE database NOT IN ({excluded_str})",
        ]
        return ';\n\n'.join(queries)
