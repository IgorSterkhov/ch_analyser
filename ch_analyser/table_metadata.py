"""Table and dictionary metadata from ClickHouse system tables."""

import re

from ch_analyser.dictionary_lineage import dictionary_definition, dictionary_source_table
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


def _ttl_from_ddl(ddl: str) -> str:
    engine = re.search(r'\bENGINE\s*=', ddl, re.IGNORECASE)
    if not engine:
        return ''
    match = re.search(r'\bTTL\s+(.+?)(?=\s+SETTINGS\b|\s+COMMENT\b|$)',
                      ddl[engine.end():], re.IGNORECASE | re.DOTALL)
    return ' '.join(match.group(1).split()) if match else ''


class TableMetadataMixin:
    def get_table_info(self, full_table_name: str) -> dict:
        database, separator, table = full_table_name.partition('.')
        if not separator:
            database, table = 'default', database
        params = {'db': database, 'table': table}
        rows = self._client.execute(
            "SELECT database, name, engine, partition_key, sorting_key, primary_key, "
            "sampling_key, total_rows, total_bytes, comment, create_table_query "
            "FROM system.tables WHERE database = %(db)s AND name = %(table)s LIMIT 1",
            params,
        )
        if not rows:
            return {}
        catalog = rows[0]
        ddl = catalog.get('create_table_query') or ''
        info = {key: catalog.get(key) for key in (
            'database', 'name', 'engine', 'partition_key', 'sorting_key',
            'primary_key', 'sampling_key', 'total_rows', 'total_bytes', 'comment',
        )}
        info['ttl'] = _ttl_from_ddl(ddl) if info['engine'] != 'Dictionary' else ''
        info['indexes'] = []
        info['errors'] = []

        try:
            parts = self._client.execute(
                "SELECT sumIf(rows, active) AS rows, "
                "countIf(active) AS active_parts, countIf(NOT active) AS inactive_parts, "
                "uniqExactIf(partition, active) AS partitions, "
                "formatReadableSize(sumIf(data_compressed_bytes, active)) AS compressed_size, "
                "formatReadableSize(sumIf(data_uncompressed_bytes, active)) AS uncompressed_size, "
                "formatReadableSize(sumIf(bytes_on_disk, active)) AS size_on_disk, "
                "formatReadableSize(sumIf(bytes_on_disk, NOT active)) AS inactive_size, "
                "formatReadableSize(sumIf(primary_key_bytes_in_memory, active)) AS primary_keys_size, "
                "round(if(sumIf(data_compressed_bytes, active) = 0, 0, "
                "sumIf(data_uncompressed_bytes, active) / sumIf(data_compressed_bytes, active)), 2) AS actual_compression, "
                "maxIf(modification_time, active) AS latest_modification "
                "FROM system.parts WHERE database = %(db)s AND table = %(table)s",
                params,
            )
            if parts:
                info.update(parts[0])
        except Exception as exc:
            logger.warning('Failed to load parts metadata for %s: %s', full_table_name, exc)
            info['errors'].append('Part statistics unavailable')

        try:
            info['indexes'] = self._client.execute(
                "SELECT name, expr, type, granularity FROM system.data_skipping_indices "
                "WHERE database = %(db)s AND table = %(table)s ORDER BY name", params,
            )
        except Exception as exc:
            logger.warning('Failed to load index metadata for %s: %s', full_table_name, exc)
            info['errors'].append('Skipping indexes unavailable')

        if info['engine'] == 'Dictionary':
            try:
                dictionary = self._client.execute(
                    "SELECT status, query_count, type, element_count, bytes_allocated, "
                    "lifetime_min, lifetime_max FROM system.dictionaries "
                    "WHERE database = %(db)s AND name = %(table)s LIMIT 1", params,
                )
                info['dictionary'] = dict(dictionary[0]) if dictionary else {}
                info['dictionary']['source_table'] = dictionary_source_table(ddl, database)
            except Exception as exc:
                logger.warning('Failed to load dictionary metadata for %s: %s', full_table_name, exc)
                info['errors'].append('Dictionary runtime statistics unavailable')
                info['dictionary'] = {'source_table': dictionary_source_table(ddl, database)}
            definition = dictionary_definition(ddl)
            if not info['dictionary'].get('type'):
                info['dictionary']['type'] = definition.get('type')
            if not info['dictionary'].get('lifetime_min') and not info['dictionary'].get('lifetime_max'):
                info['dictionary'].update({key: value for key, value in definition.items()
                                           if key in ('lifetime_min', 'lifetime_max')})
        return info
