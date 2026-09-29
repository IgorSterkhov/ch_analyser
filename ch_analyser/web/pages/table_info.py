"""Read-only Table Info panel in the server table drawer."""

from nicegui import ui


def _line(label: str, value, tooltip: str = ''):
    if value is None or value == '':
        value = '—'
    with ui.element('div').classes('w-full').style(
        'display: grid; grid-template-columns: minmax(112px, 145px) minmax(0, 1fr); '
        'gap: 8px; padding: 4px 3px; border-bottom: 1px solid #e9edf0; align-items: start'
    ):
        title = ui.label(label).classes('text-grey-7 text-caption').style('line-height: 1.35')
        if tooltip:
            title.tooltip(tooltip)
        ui.label(str(value)).classes('text-body2').style('line-height: 1.35; overflow-wrap: anywhere')


def _section(title: str):
    ui.label(title).classes('text-subtitle2 text-weight-medium').style('margin: 10px 3px 3px')


def render_table_info(info: dict):
    if not info:
        ui.label('Table metadata not found in system.tables.').classes('text-grey-7 q-pa-sm')
        return
    if info.get('error'):
        ui.label(info['error']).classes('text-negative q-pa-sm')
        return

    _section('Definition')
    _line('Engine', info.get('engine'))
    _line('Comment', info.get('comment'))
    if info.get('engine') == 'Dictionary':
        dictionary = info.get('dictionary') or {}
        _section('Dictionary')
        _line('Source table', dictionary.get('source_table'),
              'Direct ClickHouse table or first FROM target in source query')
        _line('Status', dictionary.get('status'))
        _line('Layout', dictionary.get('type'))
        _line('Elements', dictionary.get('element_count'))
        _line('Allocated bytes', dictionary.get('bytes_allocated'))
        _line('Queries', dictionary.get('query_count'))
        lifetime = dictionary.get('lifetime_min')
        maximum = dictionary.get('lifetime_max')
        _line('Lifetime, seconds', f'{lifetime}–{maximum}' if lifetime is not None else None)
    else:
        _section('Keys and retention')
        _line('Partition by', info.get('partition_key'))
        _line('Order by', info.get('sorting_key'))
        _line('Primary key', info.get('primary_key'))
        _line('Sample by', info.get('sampling_key'))
        _line('TTL', info.get('ttl'), 'Table-level TTL expression from the table definition')

        _section('Storage')
        has_parts = 'MergeTree' in (info.get('engine') or '') and info.get('active_parts') is not None
        _line('Rows', info.get('rows') if has_parts else info.get('total_rows'))
        _line('On disk', info.get('size_on_disk') if has_parts else None)
        _line('Compressed', info.get('compressed_size') if has_parts else None)
        _line('Uncompressed', info.get('uncompressed_size') if has_parts else None)
        ratio = info.get('actual_compression') if has_parts and info.get('active_parts') else None
        _line('Compression ratio', f'{ratio}×' if ratio is not None else None)
        _line('Active parts', info.get('active_parts') if has_parts else None)
        _line('Partitions', info.get('partitions') if has_parts else None)
        _line('Latest modification', info.get('latest_modification') if has_parts and info.get('active_parts') else None)
        _line('Primary key memory', info.get('primary_keys_size') if has_parts else None)
        _line('Inactive parts', info.get('inactive_parts') if has_parts else None)
        _line('Inactive size', info.get('inactive_size') if has_parts else None)

        _section('Skipping indexes')
        indexes = info.get('indexes') or []
        if not indexes and 'Skipping indexes unavailable' not in info.get('errors', []):
            ui.label('No skipping indexes found.').classes('text-grey-7 q-px-xs')
        for index in indexes:
            with ui.element('div').classes('w-full').style(
                'border-left: 2px solid #9bb9d2; margin: 6px 0; padding-left: 8px'
            ):
                ui.label(index['name']).classes('text-weight-medium text-body2')
                _line('Expression', index.get('expr'))
                _line('Type', index.get('type'))
                _line('Granularity', index.get('granularity'))

    for error in info.get('errors', []):
        ui.label(error).classes('text-warning q-mt-sm')
