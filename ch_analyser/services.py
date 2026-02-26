import re

from ch_analyser.client import CHClient
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)

EXCLUDED_DATABASES = ("system", "INFORMATION_SCHEMA", "information_schema",
                      "_temporary_and_external_tables")

QUERY_LOG_DAYS_DEFAULT = 30


class AnalysisService:
    def __init__(self, client: CHClient):
        self._client = client

    def get_tables(self, log_days: int = QUERY_LOG_DAYS_DEFAULT) -> list[dict]:
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
                f"AND event_time > now() - INTERVAL {int(log_days)} DAY "
                "GROUP BY table_name "
                "HAVING NOT startsWith(table_name, '_temporary_and_external_tables.')",
            )
            for r in rows:
                tname = r["table_name"]
                last_selects[tname] = str(r["last_select"])
        except Exception as e:
            logger.warning("Failed to get last SELECT times: %s", e)

        # 3. Last INSERT per table (prefer part_log, fallback query_log + query_views_log)
        last_inserts = self._get_last_inserts(excluded, log_days=log_days)

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

    def _get_last_inserts(self, excluded: list, log_days: int = QUERY_LOG_DAYS_DEFAULT) -> dict[str, str]:
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
                f"AND event_time > now() - INTERVAL {int(log_days)} DAY "
                "GROUP BY table_name "
                "HAVING NOT startsWith(table_name, '_temporary_and_external_tables.')",
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

    def get_query_history_filters(self, full_table_name: str,
                                   direct_only: bool = True,
                                   log_days: int = QUERY_LOG_DAYS_DEFAULT) -> dict:
        """Get unique user/kind pairs from the full query history for a table."""
        short_name = full_table_name.split('.', 1)[1] if '.' in full_table_name else full_table_name
        try:
            sql = (
                "SELECT user, query_kind, count() AS cnt "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' "
                "AND has(tables, %(table)s) "
                f"AND event_time > now() - INTERVAL {int(log_days)} DAY "
            )
            if direct_only:
                sql += f"AND positionCaseInsensitive(query, '{short_name}') > 0 "
            sql += "GROUP BY user, query_kind ORDER BY user, query_kind"
            rows = self._client.execute(sql, {"table": full_table_name})
            users = sorted(set(r['user'] for r in rows))
            kinds = sorted(set(r['query_kind'] for r in rows))
            return {"users": users, "kinds": kinds, "counts": rows}
        except Exception as e:
            logger.error("Failed to get query history filters for %s: %s", full_table_name, e)
            return {"users": [], "kinds": [], "counts": []}

    def get_query_history(self, full_table_name: str, limit: int = 200,
                          users: list[str] | None = None,
                          kinds: list[str] | None = None,
                          direct_only: bool = True,
                          log_days: int = QUERY_LOG_DAYS_DEFAULT) -> list[dict]:
        short_name = full_table_name.split('.', 1)[1] if '.' in full_table_name else full_table_name
        try:
            select_cols = "event_time, user, query_kind, query"
            if not direct_only:
                select_cols += f", positionCaseInsensitive(query, '{short_name}') > 0 AS is_direct"
            parts = [
                f"SELECT {select_cols} "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' "
                "AND has(tables, %(table)s) "
                f"AND event_time > now() - INTERVAL {int(log_days)} DAY",
            ]
            params: dict = {"table": full_table_name, "limit": limit}

            if users:
                parts.append("AND user IN %(users)s")
                params["users"] = users
            if kinds:
                parts.append("AND query_kind IN %(kinds)s")
                params["kinds"] = kinds
            if direct_only:
                parts.append(f"AND positionCaseInsensitive(query, '{short_name}') > 0")

            parts.append("ORDER BY event_time DESC")
            parts.append("LIMIT %(limit)s")

            rows = self._client.execute(' '.join(parts), params)
            for r in rows:
                r["event_time"] = str(r["event_time"])
            return rows
        except Exception as e:
            logger.error("Failed to get query history for %s: %s", full_table_name, e)
            return []

    def get_query_history_sql(self, full_table_name: str, limit: int = 200,
                              users: list[str] | None = None,
                              kinds: list[str] | None = None,
                              direct_only: bool = True,
                              log_days: int = QUERY_LOG_DAYS_DEFAULT) -> str:
        """Return the SQL query used by get_query_history (with parameters substituted)."""
        short_name = full_table_name.split('.', 1)[1] if '.' in full_table_name else full_table_name
        select_cols = "event_time, user, query_kind, query"
        if not direct_only:
            select_cols += f", positionCaseInsensitive(query, '{short_name}') > 0 AS is_direct"
        parts = [
            f"SELECT {select_cols}",
            "FROM system.query_log",
            "WHERE type = 'QueryFinish'",
            f"AND has(tables, '{full_table_name}')",
            f"AND event_time > now() - INTERVAL {int(log_days)} DAY",
        ]
        if users:
            user_list = ', '.join(f"'{u}'" for u in users)
            parts.append(f"AND user IN ({user_list})")
        if kinds:
            kind_list = ', '.join(f"'{k}'" for k in kinds)
            parts.append(f"AND query_kind IN ({kind_list})")
        if direct_only:
            parts.append(f"AND positionCaseInsensitive(query, '{short_name}') > 0")
        parts.append("ORDER BY event_time DESC")
        parts.append(f"LIMIT {limit}")
        return ' '.join(parts)

    def get_table_references(self) -> dict[str, list[tuple[str, str]]]:
        """For each table, find other entities whose DDL references it.

        Returns dict mapping table name to list of (entity_name, engine) tuples.
        """
        excluded = list(EXCLUDED_DATABASES)
        try:
            rows = self._client.execute(
                "SELECT database, name, engine, create_table_query "
                "FROM system.tables "
                "WHERE database NOT IN %(excluded)s",
                {"excluded": excluded},
            )
        except Exception as e:
            logger.warning("Failed to get DDL for references: %s", e)
            return {}

        entities: dict[str, tuple[str, str]] = {}
        for r in rows:
            full_name = f"{r['database']}.{r['name']}"
            entities[full_name] = (r['create_table_query'] or '', r.get('engine', ''))

        references: dict[str, list[tuple[str, str]]] = {}
        for target in entities:
            db, short = target.split('.', 1)
            # Regex with word boundaries to avoid substring false positives
            full_pattern = re.compile(r'\b' + re.escape(target) + r'\b')
            short_pattern = re.compile(r'\b' + re.escape(short) + r'\b(?!\.)')
            # Pattern to detect target as DESTINATION (TO target in MV DDL)
            to_full_pattern = re.compile(r'\bTO\s+' + re.escape(target) + r'\b', re.IGNORECASE)
            to_short_pattern = re.compile(r'\bTO\s+' + re.escape(short) + r'\b(?!\.)', re.IGNORECASE)
            refs = []
            for entity_name, (ddl, engine) in entities.items():
                if entity_name == target:
                    continue
                matched = False
                # Full name match (any database)
                if full_pattern.search(ddl):
                    matched = True
                # Short name match only within the same database
                elif entity_name.startswith(db + '.') and short_pattern.search(ddl):
                    matched = True
                if not matched:
                    continue
                # Skip if target is the DESTINATION of this entity (MV writes TO target)
                if to_full_pattern.search(ddl):
                    continue
                if entity_name.startswith(db + '.') and to_short_pattern.search(ddl):
                    continue
                refs.append((entity_name, engine))
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

        # Only consider entities that reference our table as SOURCE (word boundary match)
        full_pattern = re.compile(r'\b' + re.escape(full_table_name) + r'\b')
        short_pattern = re.compile(r'\b' + re.escape(short) + r'\b(?!\.)')
        # Pattern to detect our table as DESTINATION (TO table in MV DDL)
        to_full_pattern = re.compile(r'\bTO\s+' + re.escape(full_table_name) + r'\b', re.IGNORECASE)
        to_short_pattern = re.compile(r'\bTO\s+' + re.escape(short) + r'\b(?!\.)', re.IGNORECASE)
        referring_entities: dict[str, str] = {}
        for r in rows:
            entity = f"{r['database']}.{r['name']}"
            ddl = r['create_table_query'] or ''
            if entity == full_table_name:
                continue
            matched = False
            if full_pattern.search(ddl):
                matched = True
            elif entity.startswith(db + '.') and short_pattern.search(ddl):
                matched = True
            if not matched:
                continue
            # Skip if our table is the DESTINATION of this entity
            if to_full_pattern.search(ddl):
                continue
            if entity.startswith(db + '.') and to_short_pattern.search(ddl):
                continue
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
            col_pattern = re.compile(r'\b' + re.escape(col_name) + r'\b')
            refs = [entity for entity, ddl in referring_entities.items() if col_pattern.search(ddl)]
            if refs:
                result[col_name] = sorted(refs)

        return result

    def get_tables_sql(self, log_days: int = QUERY_LOG_DAYS_DEFAULT) -> str:
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
            f"AND event_time > now() - INTERVAL {int(log_days)} DAY "
            f"GROUP BY table_name "
            f"HAVING NOT startsWith(table_name, '_temporary_and_external_tables.')",

            f"-- 3a. Last INSERT (preferred: part_log)\n"
            f"SELECT database, table, max(event_time) AS last_insert "
            f"FROM system.part_log "
            f"WHERE event_type = 'NewPart' AND database NOT IN ({excluded_str}) "
            f"GROUP BY database, table",

            f"-- 3b. Last INSERT fallback: query_log\n"
            f"SELECT arrayJoin(tables) AS table_name, max(event_time) AS last_insert "
            f"FROM system.query_log "
            f"WHERE type = 'QueryFinish' AND query_kind = 'Insert' "
            f"AND event_time > now() - INTERVAL {int(log_days)} DAY "
            f"GROUP BY table_name "
            f"HAVING NOT startsWith(table_name, '_temporary_and_external_tables.')",

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

    # --- Flow methods ---

    def get_mv_flow(self, full_table_name: str) -> dict:
        """Get materialized view flow chains involving the given table.

        Returns dict with 'nodes' and 'edges' for graph rendering.
        """
        excluded = list(EXCLUDED_DATABASES)
        try:
            rows = self._client.execute(
                "SELECT database, name, engine, create_table_query "
                "FROM system.tables "
                "WHERE database NOT IN %(excluded)s",
                {"excluded": excluded},
            )
        except Exception as e:
            logger.error("Failed to get tables for MV flow: %s", e)
            return {'nodes': [], 'edges': []}

        edges = []
        node_types = {}

        for r in rows:
            full_name = f"{r['database']}.{r['name']}"
            ddl = r['create_table_query'] or ''

            if r['engine'] == 'MaterializedView':
                node_types[full_name] = 'mv'

                # Parse source: AS SELECT ... FROM <table>
                as_match = re.search(r'\bAS\s+SELECT\b', ddl, re.IGNORECASE)
                if as_match:
                    select_part = ddl[as_match.start():]
                    from_match = re.search(
                        r'\bFROM\s+(\w+(?:\.\w+)?)', select_part, re.IGNORECASE,
                    )
                    if from_match:
                        source = from_match.group(1)
                        if '.' not in source:
                            source = f"{r['database']}.{source}"
                        edges.append((source, full_name))

                # Parse target: TO <table>
                to_match = re.search(r'\bTO\s+(\w+(?:\.\w+)?)', ddl, re.IGNORECASE)
                if to_match:
                    target = to_match.group(1)
                    if '.' not in target:
                        target = f"{r['database']}.{target}"
                    edges.append((full_name, target))
            else:
                if full_name not in node_types:
                    node_types[full_name] = 'table'

        # Build directed adjacency for BFS
        forward: dict[str, set[str]] = {}
        backward: dict[str, set[str]] = {}
        for src, dst in edges:
            forward.setdefault(src, set()).add(dst)
            backward.setdefault(dst, set()).add(src)

        if full_table_name not in forward and full_table_name not in backward:
            return {'nodes': [], 'edges': []}

        def _bfs(graph: dict[str, set[str]], start: str) -> set[str]:
            visited: set[str] = set()
            queue = [start]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                for neighbor in graph.get(node, []):
                    if neighbor not in visited:
                        queue.append(neighbor)
            return visited

        # Forward BFS (downstream) + Backward BFS (upstream)
        visited = _bfs(forward, full_table_name) | _bfs(backward, full_table_name)

        relevant_edges = [{'from': s, 'to': d} for s, d in edges if s in visited and d in visited]
        relevant_nodes = [
            {'id': n, 'type': node_types.get(n, 'table')}
            for n in visited
        ]
        return {'nodes': relevant_nodes, 'edges': relevant_edges}

    def get_query_flow(self, full_table_name: str, log_days: int = QUERY_LOG_DAYS_DEFAULT) -> dict:
        """Get query-based data flow (INSERT...SELECT patterns) involving the given table."""
        try:
            rows = self._client.execute(
                "SELECT DISTINCT query, tables "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' "
                "AND query_kind = 'Insert' "
                "AND length(tables) > 1 "
                "AND has(tables, %(table)s) "
                f"AND event_time > now() - INTERVAL {int(log_days)} DAY "
                "LIMIT 1000",
                {"table": full_table_name},
            )
        except Exception as e:
            logger.error("Failed to get query flow: %s", e)
            return {'nodes': [], 'edges': []}

        edges_set: set[tuple[str, str]] = set()
        all_tables: set[str] = set()

        for r in rows:
            tables_list = r['tables']
            query = r['query']

            insert_match = re.search(r'\bINSERT\s+INTO\s+(\S+)', query, re.IGNORECASE)
            if insert_match:
                target = insert_match.group(1).strip('`"')
                for t in tables_list:
                    if t != target:
                        edges_set.add((t, target))
                        all_tables.add(t)
                        all_tables.add(target)

        nodes = [{'id': t, 'type': 'table'} for t in all_tables]
        edges = [{'from': s, 'to': d} for s, d in edges_set]
        return {'nodes': nodes, 'edges': edges}

    # ── Text Log analysis ───────────────────────────────────────────

    def get_text_log_summary(self) -> list[dict]:
        """Aggregated text_log summary grouped by thread_name, level, message_format_string."""
        try:
            rows = self._client.execute(
                "SELECT thread_name, level, "
                "  multiIf(level=1,'Fatal', level=2,'Critical', level=3,'Error', "
                "          level=4,'Warning', toString(level)) AS level_name, "
                "  argMax(message, event_time_microseconds) AS message_example, "
                "  max(event_time_microseconds) AS max_time, "
                "  count() AS cnt "
                "FROM system.text_log "
                "WHERE event_time_microseconds > today() - interval 2 week "
                "AND level <= 4 "
                "GROUP BY thread_name, level, message_format_string "
                "ORDER BY max_time DESC"
            )
            for r in rows:
                r['max_time'] = str(r['max_time'])
            return rows
        except Exception as e:
            logger.error("Failed to get text_log summary: %s", e)
            return []

    def get_user_stats(self, log_days: int = QUERY_LOG_DAYS_DEFAULT) -> list[dict]:
        """Get per-user query statistics from query_log."""
        try:
            rows = self._client.execute(
                "SELECT "
                "  user, "
                "  count() AS query_count, "
                "  max(event_time) AS last_query_time, "
                "  sum(query_duration_ms) / 1000 AS total_duration_sec, "
                "  formatReadableSize(sum(read_bytes)) AS total_read, "
                "  sum(read_rows) AS total_read_rows, "
                "  formatReadableSize(sum(written_bytes)) AS total_written, "
                "  sum(written_rows) AS total_written_rows, "
                "  formatReadableSize(max(memory_usage)) AS peak_memory, "
                "  countIf(query_kind = 'Select') AS selects, "
                "  countIf(query_kind = 'Insert') AS inserts, "
                "  countIf(query_kind NOT IN ('Select', 'Insert')) AS other_queries "
                "FROM system.query_log "
                "WHERE type = 'QueryFinish' "
                f"AND event_time > now() - INTERVAL {int(log_days)} DAY "
                "GROUP BY user "
                "ORDER BY query_count DESC"
            )
            for r in rows:
                r['last_query_time'] = str(r['last_query_time'])
            return rows
        except Exception as e:
            logger.error("Failed to get user stats: %s", e)
            return []

    def get_text_log_detail(self, thread_name: str, level: int | None = None) -> list[dict]:
        """Detailed text_log entries for a specific thread_name."""
        try:
            parts = [
                "SELECT event_time_microseconds, thread_name, "
                "  multiIf(level=1,'Fatal', level=2,'Critical', level=3,'Error', "
                "          level=4,'Warning', toString(level)) AS level_name, "
                "  query_id, logger_name, message "
                "FROM system.text_log "
                "WHERE event_time_microseconds > today() - interval 2 week "
                "AND thread_name = %(thread_name)s"
            ]
            params: dict = {"thread_name": thread_name}
            if level is not None:
                parts.append("AND level = %(level)s")
                params["level"] = level
            parts.append("ORDER BY event_time_microseconds DESC LIMIT 200")
            rows = self._client.execute(' '.join(parts), params)
            for r in rows:
                r['event_time_microseconds'] = str(r['event_time_microseconds'])
            return rows
        except Exception as e:
            logger.error("Failed to get text_log detail for thread %s: %s", thread_name, e)
            return []
