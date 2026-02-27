"""All Servers dashboard — disk usage overview with tables and ECharts."""

from datetime import datetime

from nicegui import ui

import ch_analyser.web.state as state
from ch_analyser.web.components.settings_dialog import get_admin_settings
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


def _format_bytes(b: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(b) < 1024:
            return f'{b:.1f} {unit}'
        b /= 1024
    return f'{b:.1f} PiB'


def build_all_servers_view(parent, on_drill_down=None):
    """Build the 'All Servers' dashboard view inside parent container."""
    with parent:
        _build_dashboard(on_drill_down)


def _build_dashboard(on_drill_down=None):
    store = state.monitoring_store
    if not store:
        ui.label('Monitoring not available.').classes('text-grey-7')
        return

    thresholds = get_admin_settings()
    warn_pct = thresholds['disk_warning_pct']
    crit_pct = thresholds['disk_critical_pct']

    # ── Block 1: Disk usage by servers ──
    ui.label('Disk usage by servers').classes('text-h6 q-mb-sm')

    with ui.row().classes('w-full gap-4 items-start'):
        # Left: table (40%)
        with ui.column().classes('q-pa-xs').style('width: 40%; min-width: 300px'):
            _build_server_disk_table(store, warn_pct, crit_pct, on_drill_down)

        # Right: chart (60%)
        with ui.column().classes('q-pa-xs').style('width: 58%; min-width: 400px'):
            _build_server_disk_chart(store, warn_pct, crit_pct)

    ui.separator().classes('q-my-md')

    # ── Block 2: Disk usage by tables ──
    ui.label('Disk usage by tables').classes('text-h6 q-mb-sm')

    # Server selector + top-N
    connections = state.conn_manager.list_connections()
    server_names = [c.name for c in connections]

    with ui.row().classes('items-center gap-2 q-mb-sm'):
        table_server_select = ui.select(
            options=server_names,
            value=server_names[0] if server_names else None,
            label='Server',
        ).props('dense outlined').style('min-width: 200px')

        table_topn_select = ui.select(
            options=[30, 50, 100],
            value=30,
            label='Top N',
        ).props('dense outlined').style('min-width: 100px')

    tables_container = ui.column().classes('w-full')

    def _reload_tables():
        tables_container.clear()
        srv = table_server_select.value
        topn = table_topn_select.value
        if not srv:
            return
        with tables_container:
            with ui.row().classes('w-full gap-4 items-start'):
                with ui.column().classes('q-pa-xs').style('width: 40%; min-width: 300px'):
                    _build_table_disk_table(store, srv, topn, on_drill_down)
                with ui.column().classes('q-pa-xs').style('width: 58%; min-width: 400px'):
                    _build_table_disk_chart(store, srv, topn)

    table_server_select.on_value_change(lambda _: _reload_tables())
    table_topn_select.on_value_change(lambda _: _reload_tables())

    _reload_tables()


def _build_server_disk_table(store, warn_pct, crit_pct, on_drill_down=None):
    """Render the server disk usage table."""
    data = store.get_server_disk_latest()

    if not data:
        ui.label('No monitoring data yet. Data appears after the first collection cycle.').classes('text-grey-7')
        return

    rows = []
    for d in data:
        total = d['total_bytes']
        used = d['used_bytes']
        pct = round(used / total * 100, 1) if total > 0 else 0
        if pct >= crit_pct:
            status = 'critical'
        elif pct >= warn_pct:
            status = 'warning'
        else:
            status = 'ok'
        rows.append({
            'server_name': d['server_name'],
            'used': _format_bytes(used),
            'total': _format_bytes(total),
            'pct': pct,
            'status': status,
        })

    rows.sort(key=lambda r: r['pct'], reverse=True)

    columns = [
        {'name': 'server_name', 'label': 'Server', 'field': 'server_name', 'align': 'left', 'sortable': True},
        {'name': 'used', 'label': 'Used', 'field': 'used', 'align': 'right'},
        {'name': 'pct', 'label': '%', 'field': 'pct', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b'},
        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center'},
        {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'center'},
    ]

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='server_name',
        pagination={'rowsPerPage': 0, 'sortBy': 'pct', 'descending': True},
    ).classes('w-full')

    tbl.add_slot('body', r'''
        <q-tr :props="props">
            <q-td key="server_name" :props="props">
                <span class="text-weight-bold">{{ props.row.server_name }}</span>
            </q-td>
            <q-td key="used" :props="props">{{ props.row.used }}</q-td>
            <q-td key="pct" :props="props">
                <q-badge :color="
                    props.row.status === 'critical' ? 'negative' :
                    props.row.status === 'warning' ? 'warning' :
                    'positive'
                " :label="props.row.pct + '%'" />
            </q-td>
            <q-td key="status" :props="props">
                <q-icon v-if="props.row.status === 'critical'" name="error" color="negative" size="sm" />
                <q-icon v-else-if="props.row.status === 'warning'" name="warning" color="warning" size="sm" />
                <q-icon v-else name="check_circle" color="positive" size="sm" />
            </q-td>
            <q-td key="actions" :props="props">
                <q-btn flat dense size="sm" icon="open_in_new" color="primary"
                       @click.stop="$parent.$emit('drill-down', props.row)" />
            </q-td>
        </q-tr>
    ''')

    if on_drill_down:
        def _on_drill(e):
            row = e.args
            on_drill_down(row['server_name'])
        tbl.on('drill-down', _on_drill)


def _build_server_disk_chart(store, warn_pct, crit_pct):
    """Render the server disk usage chart (ECharts line chart)."""
    history = store.get_server_disk_history(days=30)

    if not history:
        ui.label('No historical data yet.').classes('text-grey-7')
        return

    # Group by server
    servers: dict[str, list] = {}
    for row in history:
        name = row['server_name']
        total = row['total_bytes']
        used = row['used_bytes']
        pct = round(used / total * 100, 1) if total > 0 else 0
        ts = row['ts']
        if isinstance(ts, datetime):
            ts_str = ts.strftime('%Y-%m-%d %H:%M')
        else:
            ts_str = str(ts)
        servers.setdefault(name, []).append([ts_str, pct])

    series = []
    for name, points in servers.items():
        series.append({
            'name': name,
            'type': 'line',
            'data': points,
            'smooth': True,
            'symbol': 'none',
        })

    options = {
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'cross'},
        },
        'legend': {
            'data': list(servers.keys()),
            'bottom': 0,
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '15%',
            'containLabel': True,
        },
        'xAxis': {
            'type': 'category',
            'boundaryGap': False,
        },
        'yAxis': {
            'type': 'value',
            'name': 'Usage %',
            'min': 0,
            'max': 100,
        },
        'series': series,
        'dataZoom': [
            {'type': 'slider', 'start': 0, 'end': 100},
            {'type': 'inside'},
        ],
    }

    # Add threshold markLines to first series
    if series:
        series[0]['markLine'] = {
            'silent': True,
            'lineStyle': {'type': 'dashed'},
            'data': [
                {'yAxis': warn_pct, 'label': {'formatter': f'Warning {warn_pct}%'}, 'lineStyle': {'color': '#fb8c00'}},
                {'yAxis': crit_pct, 'label': {'formatter': f'Critical {crit_pct}%'}, 'lineStyle': {'color': '#e53935'}},
            ],
        }

    ui.echart(options).classes('w-full').style('height: 350px')


def _build_table_disk_table(store, server_name: str, top_n: int, on_drill_down=None):
    """Render the table-level disk usage table."""
    data = store.get_table_disk_latest(server_name)

    if not data:
        ui.label('No table data for this server.').classes('text-grey-7')
        return

    total_bytes = sum(d['size_bytes'] for d in data)

    # Top-N + other
    top_data = data[:top_n]
    other_bytes = sum(d['size_bytes'] for d in data[top_n:])

    rows = []
    for d in top_data:
        pct = round(d['size_bytes'] / total_bytes * 100, 1) if total_bytes > 0 else 0
        rows.append({
            'table_name': f"{d['database_name']}.{d['table_name']}",
            'size': _format_bytes(d['size_bytes']),
            'size_bytes': d['size_bytes'],
            'pct': pct,
        })

    if other_bytes > 0:
        pct = round(other_bytes / total_bytes * 100, 1) if total_bytes > 0 else 0
        rows.append({
            'table_name': f'(other {len(data) - top_n} tables)',
            'size': _format_bytes(other_bytes),
            'size_bytes': other_bytes,
            'pct': pct,
        })

    columns = [
        {'name': 'table_name', 'label': 'Table', 'field': 'table_name', 'align': 'left', 'sortable': True},
        {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
        {'name': 'pct', 'label': '%', 'field': 'pct', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b'},
    ]

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='table_name',
        pagination={'rowsPerPage': 0, 'sortBy': 'size', 'descending': True},
    ).classes('w-full')


def _build_table_disk_chart(store, server_name: str, top_n: int):
    """Render the table-level disk usage chart."""
    history = store.get_table_disk_history(server_name, days=30, top_n=top_n)

    if not history:
        ui.label('No historical table data.').classes('text-grey-7')
        return

    # Group by table
    tables: dict[str, list] = {}
    for row in history:
        name = row['table_name']
        if name == '__other__':
            name = '(other)'
        ts = row['ts']
        if isinstance(ts, datetime):
            ts_str = ts.strftime('%Y-%m-%d %H:%M')
        else:
            ts_str = str(ts)
        size_gb = round(row['size_bytes'] / (1024 ** 3), 2)
        tables.setdefault(name, []).append([ts_str, size_gb])

    series = []
    for name, points in tables.items():
        series.append({
            'name': name,
            'type': 'line',
            'data': points,
            'smooth': True,
            'symbol': 'none',
            'areaStyle': {'opacity': 0.1},
        })

    options = {
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'cross'},
        },
        'legend': {
            'data': list(tables.keys()),
            'bottom': 0,
            'type': 'scroll',
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '15%',
            'containLabel': True,
        },
        'xAxis': {
            'type': 'category',
            'boundaryGap': False,
        },
        'yAxis': {
            'type': 'value',
            'name': 'Size (GiB)',
        },
        'series': series,
        'dataZoom': [
            {'type': 'slider', 'start': 0, 'end': 100},
            {'type': 'inside'},
        ],
    }

    ui.echart(options).classes('w-full').style('height: 350px')
