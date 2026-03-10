"""All Servers dashboard — disk usage overview with tables and ECharts."""

import json
from datetime import datetime

from nicegui import ui

import ch_analyser.web.state as state
from ch_analyser.web.components.settings_dialog import get_admin_settings
from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


def _js_str(value: str) -> str:
    """Escape a Python string for safe inline use in JavaScript."""
    return json.dumps(value)


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

    # Mutable container for chart reference (rebuilt on days change)
    server_chart_ref = [None]  # [0] = (chart_el, server_names) or None

    with ui.row().classes('w-full gap-4 items-start'):
        # Left: table (40%)
        with ui.column().classes('q-pa-xs').style('width: 40%; min-width: 300px'):
            server_tbl = _build_server_disk_table(store, warn_pct, crit_pct, on_drill_down)

        # Right: chart (60%) with days selector
        with ui.column().classes('q-pa-xs').style('width: 58%; min-width: 400px'):
            server_chart_container = ui.column().classes('w-full')

            def _rebuild_server_chart():
                server_chart_container.clear()
                with server_chart_container:
                    server_chart_ref[0] = _build_server_disk_chart(store, warn_pct, crit_pct, days=days_select.value)

            with ui.row().classes('items-center gap-2 q-mb-xs'):
                days_select = ui.select(
                    options=[30, 60, 90, 180, 365],
                    value=30,
                    label='Days',
                ).props('dense outlined').style('min-width: 100px')
                days_select.on_value_change(lambda _: _rebuild_server_chart())

            _rebuild_server_chart()

    # Wire server table row click → chart legend filtering + row highlighting (toggle)
    if server_tbl:
        selected_server = [None]

        def _on_server_row_click(e):
            clicked_name = e.args[1]['server_name']
            ref = server_chart_ref[0]

            if clicked_name == selected_server[0]:
                # Deselect: show all series, remove highlight
                selected_server[0] = None
                if ref:
                    chart_el, _ = ref
                    chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
                ui.run_javascript('''
                    var tbl = document.querySelector('.server-disk-tbl');
                    if (tbl) tbl.querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                ''')
            else:
                # Select: filter to this server, highlight row
                selected_server[0] = clicked_name
                if ref:
                    chart_el, _ = ref
                    chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
                    chart_el.run_chart_method('dispatchAction', {'type': 'legendInverseSelect'})
                    chart_el.run_chart_method('dispatchAction', {
                        'type': 'legendSelect', 'name': clicked_name,
                    })
                ui.run_javascript(f'''
                    var tbl = document.querySelector('.server-disk-tbl');
                    if (tbl) {{
                        tbl.querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                        tbl.querySelectorAll('tbody tr td:first-child span').forEach(function(span) {{
                            if (span.textContent.trim() === {_js_str(clicked_name)})
                                span.closest('tr').classList.add('table-row-active');
                        }});
                    }}
                ''')

        server_tbl.on('row-click', _on_server_row_click)

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
                    tbl = _build_table_disk_table(store, srv, topn, on_drill_down)

                with ui.column().classes('q-pa-xs').style('width: 58%; min-width: 400px'):
                    chart_result = _build_table_disk_chart(store, srv, topn)

            # Wire table row click → chart legend filtering + row highlighting (toggle)
            if tbl and chart_result:
                chart_el, table_names = chart_result
                selected_table = [None]

                def _on_row_click(e):
                    clicked_name = e.args[1]['table_name']

                    if clicked_name == selected_table[0]:
                        # Deselect: show all series, remove highlight
                        selected_table[0] = None
                        chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
                        ui.run_javascript('''
                            var tbl = document.querySelector('.tables-disk-tbl');
                            if (tbl) tbl.querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                        ''')
                    else:
                        # Select: filter to this table, highlight row
                        selected_table[0] = clicked_name
                        chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
                        chart_el.run_chart_method('dispatchAction', {'type': 'legendInverseSelect'})
                        chart_el.run_chart_method('dispatchAction', {
                            'type': 'legendSelect', 'name': clicked_name,
                        })
                        ui.run_javascript(f'''
                            var tbl = document.querySelector('.tables-disk-tbl');
                            if (tbl) {{
                                tbl.querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                                tbl.querySelectorAll('tbody tr td:first-child').forEach(function(td) {{
                                    if (td.textContent.trim() === {_js_str(clicked_name)})
                                        td.closest('tr').classList.add('table-row-active');
                                }});
                            }}
                        ''')

                tbl.on('row-click', _on_row_click)

    table_server_select.on_value_change(lambda _: _reload_tables())
    table_topn_select.on_value_change(lambda _: _reload_tables())

    _reload_tables()


def _build_server_disk_table(store, warn_pct, crit_pct, on_drill_down=None):
    """Render the server disk usage table. Returns ui.table or None."""
    data = store.get_server_disk_latest()

    if not data:
        ui.label('No monitoring data yet. Data appears after the first collection cycle.').classes('text-grey-7')
        return None

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
    ).classes('w-full server-disk-tbl')

    tbl.add_slot('body', r'''
        <q-tr :props="props" @click="$parent.$emit('row-click', $event, props.row)" style="cursor: pointer">
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

    return tbl


def _build_server_disk_chart(store, warn_pct, crit_pct, days=30):
    """Render the server disk usage chart. Returns (echart, server_names) or None."""
    history = store.get_server_disk_history(days=days)

    if not history:
        ui.label('No historical data yet.').classes('text-grey-7')
        return None

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

    server_names = list(servers.keys())

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
            'confine': True,
        },
        'legend': {
            'data': server_names,
            'type': 'scroll',
            'orient': 'vertical',
            'right': 0,
            'top': 20,
            'bottom': 20,
        },
        'grid': {
            'left': '3%',
            'right': '20%',
            'bottom': '3%',
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

    # Show all / Hide all buttons
    with ui.row().classes('items-center gap-1 q-mb-xs'):
        def _show_all():
            chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})

        def _hide_all():
            chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
            chart_el.run_chart_method('dispatchAction', {'type': 'legendInverseSelect'})

        ui.button('Show all', on_click=_show_all).props('flat dense size=sm no-caps')
        ui.button('Hide all', on_click=_hide_all).props('flat dense size=sm no-caps')

    chart_el = ui.echart(options).classes('w-full').style('height: 350px')

    return chart_el, server_names


def _build_table_disk_table(store, server_name: str, top_n: int, on_drill_down=None):
    """Render the table-level disk usage table. Returns the ui.table element or None."""
    data = store.get_table_disk_latest(server_name)

    if not data:
        ui.label('No table data for this server.').classes('text-grey-7')
        return None

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
    ).classes('w-full tables-disk-tbl')

    return tbl


def _build_table_disk_chart(store, server_name: str, top_n: int):
    """Render the table-level disk usage chart. Returns (echart, table_names) or None."""
    history = store.get_table_disk_history(server_name, days=30, top_n=top_n)

    if not history:
        ui.label('No historical table data.').classes('text-grey-7')
        return None

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

    table_names = list(tables.keys())

    options = {
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'cross'},
            'confine': True,
            'enterable': True,
            'extraCssText': 'max-height: 300px; overflow-y: auto;',
        },
        'legend': {
            'data': table_names,
            'type': 'scroll',
            'orient': 'vertical',
            'right': 0,
            'top': 20,
            'bottom': 20,
            'width': '23%',
        },
        'grid': {
            'left': '3%',
            'right': '25%',
            'bottom': '10%',
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

    # Show all / Hide all buttons
    with ui.row().classes('items-center gap-1 q-mb-xs'):
        def _show_all():
            chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})

        def _hide_all():
            chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
            chart_el.run_chart_method('dispatchAction', {'type': 'legendInverseSelect'})

        ui.button('Show all', on_click=_show_all).props('flat dense size=sm no-caps')
        ui.button('Hide all', on_click=_hide_all).props('flat dense size=sm no-caps')

    chart_el = ui.echart(options).classes('w-full').style('height: 350px')

    return chart_el, table_names
