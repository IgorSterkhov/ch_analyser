"""All Servers dashboard — disk usage overview with tables and ECharts."""

import json
from datetime import datetime

from nicegui import app, ui

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


def _resizable_chart_wrapper(storage_key: str, default_height: int = 350):
    """Create a resizable wrapper div for a chart. Returns the wrapper element as context manager."""
    height = app.storage.user.get(storage_key, default_height)
    wrapper = ui.element('div').style(
        f'height: {height}px; position: relative; width: 100%'
    )
    dom_id = f'chart-resize-{storage_key}'
    wrapper.props(f'id="{dom_id}"')

    async def _save_height(e):
        try:
            h = await ui.run_javascript(f'document.getElementById("{dom_id}").offsetHeight')
            if h and isinstance(h, (int, float)) and h >= 200:
                app.storage.user[storage_key] = int(h)
        except Exception:
            pass

    wrapper.on('resize-done', _save_height)
    ui.timer(0.3, lambda: ui.run_javascript(f'window.initChartResize("{dom_id}")'), once=True)
    return wrapper


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

    def _show_all_servers():
        ref = server_chart_ref[0]
        if ref:
            ref[0].run_chart_method('dispatchAction', {'type': 'legendAllSelect'})

    def _hide_all_servers():
        ref = server_chart_ref[0]
        if ref:
            ref[0].run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
            ref[0].run_chart_method('dispatchAction', {'type': 'legendInverseSelect'})

    # Controls row
    with ui.row().classes('w-full gap-4 items-end'):
        ui.element('div').style('width: 40%; min-width: 300px')
        with ui.row().classes('items-center gap-2 q-mb-xs').style('width: 58%; min-width: 400px'):
            days_select = ui.select(
                options=[30, 60, 90, 180, 365],
                value=30,
                label='Days',
            ).props('dense outlined').style('min-width: 100px')
            ui.button('Show all', on_click=_show_all_servers).props('dense flat no-caps color=dark').style('border: 1px solid rgba(0,0,0,0.24); border-radius: 4px; padding: 4px 12px')
            ui.button('Hide all', on_click=_hide_all_servers).props('dense flat no-caps color=dark').style('border: 1px solid rgba(0,0,0,0.24); border-radius: 4px; padding: 4px 12px')

    # Mutable ref for table_server_select (defined later in Block 2)
    table_server_ref = [None]

    def _on_show_tables(server_name):
        if table_server_ref[0]:
            table_server_ref[0].set_value(server_name)
        ui.run_javascript('document.getElementById("tables-section").scrollIntoView({behavior: "smooth"})')

    # Table + Chart row (aligned top edges)
    with ui.row().classes('w-full gap-4 items-start'):
        with ui.column().classes('q-pa-xs').style('width: 40%; min-width: 300px'):
            server_tbl = _build_server_disk_table(store, warn_pct, crit_pct, on_drill_down, _on_show_tables)

        server_chart_container = ui.column().classes('q-pa-xs').style('width: 58%; min-width: 400px')

    def _rebuild_server_chart():
        server_chart_container.clear()
        with server_chart_container:
            with _resizable_chart_wrapper('chart_server_disk_h'):
                server_chart_ref[0] = _build_server_disk_chart(store, warn_pct, crit_pct, days=days_select.value)

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
    ui.label('Disk usage by tables').classes('text-h6 q-mb-sm').props('id="tables-section"')

    connections = state.conn_manager.list_connections()
    server_names = [c.name for c in connections]

    table_chart_ref = [None]  # [0] = (chart_el, table_names) or None

    def _show_all_tables():
        ref = table_chart_ref[0]
        if ref:
            ref[0].run_chart_method('dispatchAction', {'type': 'legendAllSelect'})

    def _hide_all_tables():
        ref = table_chart_ref[0]
        if ref:
            ref[0].run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
            ref[0].run_chart_method('dispatchAction', {'type': 'legendInverseSelect'})

    # Controls row — selects left, show/hide right
    with ui.row().classes('w-full gap-4 items-end'):
        with ui.row().classes('items-center gap-2').style('width: 40%; min-width: 300px'):
            table_server_select = ui.select(
                options=server_names,
                value=server_names[0] if server_names else None,
                label='Server',
            ).props('dense outlined').style('min-width: 200px')
            table_server_ref[0] = table_server_select

            table_topn_select = ui.select(
                options=[30, 50, 100],
                value=30,
                label='Top N',
            ).props('dense outlined').style('min-width: 100px')

        with ui.row().classes('items-center gap-2 q-mb-xs').style('width: 58%; min-width: 400px'):
            ui.button('Show all', on_click=_show_all_tables).props('dense flat no-caps color=dark').style('border: 1px solid rgba(0,0,0,0.24); border-radius: 4px; padding: 4px 12px')
            ui.button('Hide all', on_click=_hide_all_tables).props('dense flat no-caps color=dark').style('border: 1px solid rgba(0,0,0,0.24); border-radius: 4px; padding: 4px 12px')

    # Table + Chart row
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
                    with _resizable_chart_wrapper('chart_table_disk_h'):
                        chart_result = _build_table_disk_chart(store, srv, topn)

            table_chart_ref[0] = chart_result

            # Wire table row click → chart legend filtering + row highlighting (toggle)
            if tbl and chart_result:
                chart_el, table_names = chart_result
                selected_table = [None]

                def _on_row_click(e):
                    clicked_name = e.args[1]['table_name']

                    if clicked_name == selected_table[0]:
                        selected_table[0] = None
                        chart_el.run_chart_method('dispatchAction', {'type': 'legendAllSelect'})
                        ui.run_javascript('''
                            var tbl = document.querySelector('.tables-disk-tbl');
                            if (tbl) tbl.querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                        ''')
                    else:
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


def _build_server_disk_table(store, warn_pct, crit_pct, on_drill_down=None, on_show_tables=None):
    """Render the server disk usage table. Returns ui.table or None."""
    data = store.get_server_disk_latest() if store else []
    connections = state.conn_manager.list_connections()

    if not data and not connections:
        ui.label('No monitoring data yet. Data appears after the first collection cycle.').classes('text-grey-7')
        return None

    rows = []
    monitored_names = set()
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
        monitored_names.add(d['server_name'])

    # Add connections without monitoring data
    for conn in connections:
        if conn.name not in monitored_names:
            rows.append({
                'server_name': conn.name,
                'used': '\u2014',
                'total': '\u2014',
                'pct': -1,
                'status': 'no_data',
            })

    rows.sort(key=lambda r: r['pct'], reverse=True)

    columns = [
        {'name': 'server_name', 'label': 'Server', 'field': 'server_name', 'align': 'left', 'sortable': True},
        {'name': 'used', 'label': 'Used', 'field': 'used', 'align': 'right'},
        {'name': 'pct', 'label': '%', 'field': 'pct', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b'},
        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center'},
        {'name': 'tables', 'label': '', 'field': 'tables', 'align': 'center'},
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
                <q-badge v-if="props.row.status !== 'no_data'" :color="
                    props.row.status === 'critical' ? 'negative' :
                    props.row.status === 'warning' ? 'warning' :
                    'positive'
                " :label="props.row.pct + '%'" />
                <span v-else class="text-grey-5">&mdash;</span>
            </q-td>
            <q-td key="status" :props="props">
                <q-icon v-if="props.row.status === 'critical'" name="error" color="negative" size="sm" />
                <q-icon v-else-if="props.row.status === 'warning'" name="warning" color="warning" size="sm" />
                <q-icon v-else-if="props.row.status === 'no_data'" name="hourglass_empty" color="grey-5" size="sm" />
                <q-icon v-else name="check_circle" color="positive" size="sm" />
            </q-td>
            <q-td key="tables" :props="props">
                <q-btn flat dense size="sm" icon="table_chart" color="grey-7"
                       @click.stop="$parent.$emit('show-tables', props.row)" />
            </q-td>
            <q-td key="actions" :props="props">
                <q-btn flat dense size="sm" icon="open_in_new" color="primary"
                       @click.stop="$parent.$emit('drill-down', props.row)" />
            </q-td>
        </q-tr>
    ''')

    if on_show_tables:
        def _on_show_tables(e):
            on_show_tables(e.args['server_name'])
        tbl.on('show-tables', _on_show_tables)

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
            'type': 'time',
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

    chart_el = ui.echart(options).classes('w-full').style('height: 100%')

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
            'bottom': '3%',
            'containLabel': True,
        },
        'xAxis': {
            'type': 'time',
        },
        'yAxis': {
            'type': 'value',
            'name': 'Size (GiB)',
        },
        'series': series,
    }

    chart_el = ui.echart(options).classes('w-full').style('height: 100%')

    return chart_el, table_names
