"""Behavior of table details and dictionary lineage."""

from types import SimpleNamespace

import ch_analyser.web.components.settings_dialog as settings_dialog
from ch_analyser.services import AnalysisService
from ch_analyser.web.pages._shared import flow_to_mermaid


class CatalogClient:
    def __init__(self, catalog=None, parts=None, indexes=None, dictionaries=None, queries=None):
        self.catalog = catalog or []
        self.parts = parts or []
        self.indexes = indexes or []
        self.dictionaries = dictionaries or []
        self.queries = queries or []

    def execute(self, query, params=None):
        if 'FROM system.query_log' in query:
            return self.queries
        if 'FROM system.tables' in query:
            if params and 'db' in params:
                return [r for r in self.catalog if r['database'] == params['db'] and r['name'] == params['table']]
            return self.catalog
        if 'FROM system.parts' in query:
            return self.parts
        if 'FROM system.data_skipping_indices' in query:
            return self.indexes
        if 'FROM system.dictionaries' in query:
            return self.dictionaries
        raise AssertionError(query)


def test_compact_is_new_default_and_legacy_default_keeps_standard_size(monkeypatch):
    user = {}
    monkeypatch.setattr(settings_dialog, 'app', SimpleNamespace(storage=SimpleNamespace(user=user)))
    assert settings_dialog.get_settings()['table_density'] == 'compact'
    user['settings'] = {'table_density': 'default'}
    assert settings_dialog.get_settings()['table_density'] == 'standard'


def test_table_info_from_catalog_parts_and_indexes():
    catalog = [{
        'database': 'test_db', 'name': 'events', 'engine': 'MergeTree',
        'partition_key': 'toYYYYMM(event_date)', 'sorting_key': '(event_date, id)',
        'primary_key': '(event_date, id)', 'sampling_key': '', 'total_rows': 25,
        'total_bytes': 2048, 'comment': 'demo',
        'create_table_query': "CREATE TABLE test_db.events (...) ENGINE = MergeTree ORDER BY id TTL event_date + toIntervalDay(30) SETTINGS index_granularity = 8192",
    }]
    parts = [{'rows': 25, 'active_parts': 2, 'inactive_parts': 1,
              'partitions': 2, 'compressed_size': '1.00 KiB',
              'uncompressed_size': '4.00 KiB', 'size_on_disk': '2.00 KiB',
              'inactive_size': '100.00 B', 'primary_keys_size': '64.00 B',
              'actual_compression': 4.0, 'latest_modification': '2026-09-29 12:00:00'}]
    indexes = [{'name': 'ix_user', 'expr': 'user_id', 'type': 'set', 'granularity': 4}]
    info = AnalysisService(CatalogClient(catalog, parts, indexes)).get_table_info('test_db.events')
    assert info['engine'] == 'MergeTree'
    assert info['partition_key'] == 'toYYYYMM(event_date)'
    assert info['ttl'] == 'event_date + toIntervalDay(30)'
    assert info['rows'] == 25
    assert info['inactive_parts'] == 1
    assert info['indexes'] == indexes
    assert 'create_table_query' not in info


def test_query_flow_includes_dictionary_from_multiline_source_query_without_insert():
    ddl = """CREATE DICTIONARY dict.sellers_portal (supplier_id Int32, supplier_name String)
    PRIMARY KEY supplier_id
    SOURCE(CLICKHOUSE(NAME dictator_ch3_personal DB 'dict_personal'
    QUERY 'SELECT supplier_id, supplier_name\r\n FROM dict_personal.sellers_portal FINAL'))
    LIFETIME(MIN 86000 MAX 86400) LAYOUT(HASHED_ARRAY())"""
    catalog = [{'database': 'dict', 'name': 'sellers_portal',
                'engine': 'Dictionary', 'create_table_query': ddl}]
    flow = AnalysisService(CatalogClient(catalog)).get_query_flow('dict_personal.sellers_portal')
    assert {'from': 'dict_personal.sellers_portal', 'to': 'dict.sellers_portal'} in flow['edges']
    assert {'id': 'dict.sellers_portal', 'type': 'dictionary'} in flow['nodes']


def test_query_flow_includes_dictionary_table_source_when_query_log_unavailable():
    class NoLogClient(CatalogClient):
        def execute(self, query, params=None):
            if 'FROM system.query_log' in query:
                raise RuntimeError('query_log denied')
            return super().execute(query, params)

    catalog = [{'database': 'dict', 'name': 'users_dict', 'engine': 'Dictionary',
                'create_table_query': "CREATE DICTIONARY dict.users_dict (id UInt32) PRIMARY KEY id SOURCE(CLICKHOUSE(DB 'test_db' TABLE 'users')) LAYOUT(FLAT())"}]
    flow = AnalysisService(NoLogClient(catalog)).get_query_flow('test_db.users')
    assert {'from': 'test_db.users', 'to': 'dict.users_dict'} in flow['edges']


def test_query_flow_keeps_insert_select_pipeline():
    queries = [{'query': 'INSERT INTO test_db.target SELECT * FROM test_db.source',
                'tables': ['test_db.source', 'test_db.target']}]
    flow = AnalysisService(CatalogClient(queries=queries)).get_query_flow('test_db.source')
    assert {'from': 'test_db.source', 'to': 'test_db.target'} in flow['edges']
    assert {'id': 'test_db.target', 'type': 'table'} in flow['nodes']


def test_dictionary_non_clickhouse_source_creates_no_table_edge():
    catalog = [{'database': 'dict', 'name': 'remote_dict', 'engine': 'Dictionary',
                'create_table_query': "CREATE DICTIONARY dict.remote_dict (id UInt32) PRIMARY KEY id SOURCE(HTTP(URL 'https://example.invalid/file.csv')) LAYOUT(FLAT())"}]
    flow = AnalysisService(CatalogClient(catalog)).get_query_flow('test_db.users')
    assert flow == {'nodes': [], 'edges': []}


def test_dictionary_has_distinct_graph_shape():
    flow = {'nodes': [{'id': 'test_db.users', 'type': 'table'},
                      {'id': 'test_db.users_query_dict', 'type': 'dictionary'}],
            'edges': [{'from': 'test_db.users', 'to': 'test_db.users_query_dict'}]}
    mermaid = flow_to_mermaid(flow, highlight_table='test_db.users_query_dict')
    assert 'test_db_users["test_db.users"]' in mermaid
    assert 'test_db_users_query_dict{{"' in mermaid
    assert 'dict</' in mermaid
    assert 'style test_db_users_query_dict fill:#eef5fc' in mermaid
    assert 'test_db_users --> test_db_users_query_dict' in mermaid


def test_dictionary_graph_escapes_html_in_table_name():
    flow = {'nodes': [{'id': 'test_db.<img src=x>', 'type': 'dictionary'}], 'edges': []}
    mermaid = flow_to_mermaid(flow)
    assert '<img' not in mermaid
    assert '&lt;img src=x&gt;' in mermaid


def test_dictionary_info_exposes_definition_when_not_loaded_but_not_credentials():
    ddl = "CREATE DICTIONARY dict.users_dict (id UInt32) PRIMARY KEY id SOURCE(CLICKHOUSE(DB 'test_db' TABLE 'users' PASSWORD 'secret')) LIFETIME(MIN 60 MAX 120) LAYOUT(FLAT())"
    catalog = [{'database': 'dict', 'name': 'users_dict', 'engine': 'Dictionary',
                'create_table_query': ddl, 'partition_key': '', 'sorting_key': '',
                'primary_key': '', 'sampling_key': '', 'total_rows': None,
                'total_bytes': None, 'comment': ''}]
    dictionaries = [{'status': 'NOT_LOADED', 'query_count': 0, 'type': '',
                     'element_count': 0, 'bytes_allocated': 0,
                     'lifetime_min': 0, 'lifetime_max': 0}]
    info = AnalysisService(CatalogClient(catalog, dictionaries=dictionaries)).get_table_info('dict.users_dict')
    assert info['dictionary']['status'] == 'NOT_LOADED'
    assert info['dictionary']['type'] == 'FLAT'
    assert info['dictionary']['lifetime_min'] == 60
    assert info['dictionary']['lifetime_max'] == 120
    assert info['dictionary']['source_table'] == 'test_db.users'
    assert 'secret' not in str(info)
