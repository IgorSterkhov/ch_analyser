"""INSERT pipelines and ClickHouse dictionary sources for Query Flow."""

import re

from ch_analyser.dictionary_lineage import dictionary_source_table
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


class QueryFlowMixin:
    def get_query_flow(self, full_table_name: str, log_days: int = 30) -> dict:
        """Return the connected flow around a table, including dictionary refresh sources."""
        edges: set[tuple[str, str]] = set()
        node_types: dict[str, str] = {}

        try:
            rows = self._client.execute(
                "SELECT DISTINCT query, tables FROM system.query_log "
                "WHERE type = 'QueryFinish' AND query_kind = 'Insert' "
                "AND length(tables) > 1 AND has(tables, %(table)s) "
                f"AND event_time > now() - INTERVAL {int(log_days)} DAY LIMIT 1000",
                {'table': full_table_name},
            )
            for row in rows:
                match = re.search(r'\bINSERT\s+INTO\s+(\S+)', row['query'], re.IGNORECASE)
                if not match:
                    continue
                target = match.group(1).strip('`"')
                for table in row['tables']:
                    if table != target:
                        edges.add((table, target))
        except Exception as exc:
            logger.warning('Query log unavailable for flow of %s: %s', full_table_name, exc)

        try:
            dictionaries = self._client.execute(
                "SELECT database, name, engine, create_table_query FROM system.tables "
                "WHERE engine = 'Dictionary' AND database NOT IN %(excluded)s",
                {'excluded': ['system', 'INFORMATION_SCHEMA', 'information_schema',
                              '_temporary_and_external_tables']},
            )
            for row in dictionaries:
                if row['engine'] != 'Dictionary':
                    continue
                source = dictionary_source_table(row.get('create_table_query') or '', row['database'])
                if source:
                    dictionary = f"{row['database']}.{row['name']}"
                    edges.add((source, dictionary))
                    node_types[dictionary] = 'dictionary'
        except Exception as exc:
            logger.warning('Dictionary metadata unavailable for flow of %s: %s', full_table_name, exc)

        neighbors: dict[str, set[str]] = {}
        for source, target in edges:
            neighbors.setdefault(source, set()).add(target)
            neighbors.setdefault(target, set()).add(source)
        if full_table_name not in neighbors:
            return {'nodes': [], 'edges': []}

        visited = {full_table_name}
        queue = [full_table_name]
        while queue:
            current = queue.pop(0)
            for neighbor in neighbors[current] - visited:
                visited.add(neighbor)
                queue.append(neighbor)
        return {
            'nodes': [{'id': name, 'type': node_types.get(name, 'table')}
                      for name in sorted(visited)],
            'edges': [{'from': source, 'to': target} for source, target in sorted(edges)
                      if source in visited and target in visited],
        }
