"""Server Details view — tables, columns, query history, flow, text logs, users.

Extracted from main.py. All UI functions accept a ServerDetailsContext dataclass
instead of many individual panel references.
"""

import html
import json
import re
from datetime import datetime
from dataclasses import dataclass, field

from nicegui import app, background_tasks, run, ui

from ch_analyser.client import CHClient
from ch_analyser.services import AnalysisService
from ch_analyser.sql_format import format_clickhouse_sql
import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import is_admin
from ch_analyser.web.pages._shared import (
    copy_to_clipboard, show_refs_dialog,
    flow_to_mermaid, show_fullscreen_mermaid, render_mermaid_scrollable,
    apply_text_filter, export_table_csv, export_table_excel,
    PAGINATION_SLOT, HEADER_CELL_TOOLTIP_SLOT,
)
from ch_analyser.web.pages.query_logs import load_query_logs


@dataclass
class ServerDetailsContext:
    tables_panel: ui.column = None
    columns_panel: ui.column = None
    server_info_bar: ui.card = None
    right_drawer: object = None
    drawer_title: ui.label = None
    text_logs_panel: ui.column = None
    query_logs_panel: ui.column = None
    qmon_panel: ui.element = None
    users_panel: ui.column = None
    main_tabs_loaded: set = field(default_factory=set)
    connection_select: ui.select = None
    _tables_widget: object = None
    active_main_tab: str = 'Tables'


# ── Module-level state for connection flow ──
_connecting_name: str | None = None
_suppress_right_drawer_hide: bool = False


def build_server_details_view(parent, right_drawer, columns_panel, drawer_title=None) -> ServerDetailsContext:
    """Build the 'by Server Details' view inside parent container.

    Returns a ServerDetailsContext with all panel references.
    """
    ctx = ServerDetailsContext()
    ctx.right_drawer = right_drawer
    ctx.columns_panel = columns_panel
    ctx.drawer_title = drawer_title

    with parent:
        # Connection selector (dropdown)
        connections = state.conn_manager.list_connections()
        conn_options = {cfg.name: f'{cfg.name} ({cfg.host}:{cfg.port})' for cfg in connections}

        def _on_connection_selected(e):
            conn_name = e.value
            if conn_name:
                cfg = state.conn_manager.get_connection(conn_name)
                if cfg:
                    _on_connect(cfg, ctx)

        with ui.row().classes('items-center gap-2 w-full q-mb-sm'):
            ui.icon('dns').classes('text-grey-7')
            ctx.connection_select = ui.select(
                options=conn_options,
                value=state.active_connection_name,
                label='Connection',
                on_change=_on_connection_selected,
            ).props('dense outlined').classes('q-ml-xs').style('min-width: 250px').tooltip('Select connection')

        # Server info bar
        ctx.server_info_bar = ui.card().classes('q-pa-sm w-full').props('flat bordered')
        ctx.server_info_bar.set_visibility(False)

        # Main-level tabs
        with ui.tabs().classes('w-full').props('dense') as main_tabs:
            tables_main_tab = ui.tab('Tables', icon='table_chart').tooltip('Table list and sizes')
            users_main_tab = ui.tab('Users', icon='people').tooltip('User activity stats')
            text_logs_main_tab = ui.tab('Text Logs', icon='article').tooltip('Server error logs')
            query_logs_main_tab = ui.tab('Query Logs', icon='manage_search').tooltip('Server-wide query log')
            qmon_main_tab = ui.tab('QMON', icon='monitor').tooltip('Active queries')

        with ui.tab_panels(main_tabs, value=tables_main_tab).classes(
            'w-full q-pt-none flex-grow'
        ):
            with ui.tab_panel(tables_main_tab).classes('q-pa-xs'):
                ctx.tables_panel = ui.column().classes('w-full')
                with ctx.tables_panel:
                    ui.label('Select a connection above.').classes('text-grey-7')
            with ui.tab_panel(users_main_tab).classes('q-pa-xs'):
                ctx.users_panel = ui.column().classes('w-full')
                with ctx.users_panel:
                    ui.label('Select a connection above.').classes('text-grey-7')
            with ui.tab_panel(text_logs_main_tab).classes('q-pa-xs'):
                ctx.text_logs_panel = ui.column().classes('w-full')
                with ctx.text_logs_panel:
                    ui.label('Select a connection above.').classes('text-grey-7')
            with ui.tab_panel(query_logs_main_tab).classes('q-pa-xs'):
                ctx.query_logs_panel = ui.column().classes('w-full')
                with ctx.query_logs_panel:
                    ui.label('Select a connection above.').classes('text-grey-7')
            with ui.tab_panel(qmon_main_tab).classes('q-pa-none').style(
                'position: relative; flex: 1 1 0; min-height: 0'
            ):
                ctx.qmon_panel = ui.element('div').style(
                    'position: absolute; inset: 0'
                )
                with ctx.qmon_panel:
                    ui.label('Select a connection above.').classes('text-grey-7 q-pa-md')

        def _on_main_tab_change(e):
            tab = e.value
            ctx.active_main_tab = tab
            if tab in ('Text Logs', 'Query Logs', 'QMON'):
                if ctx.right_drawer and hasattr(ctx.right_drawer, 'value') and ctx.right_drawer.value:
                    ctx.right_drawer.hide()
                ui.run_javascript(
                    "document.querySelector('.right-drawer-toggle-btn')?.style.setProperty('display','none')"
                )
            else:
                ui.run_javascript(
                    "document.querySelector('.right-drawer-toggle-btn')?.style.setProperty('display','')"
                )
            if tab == 'Users' and 'Users' not in ctx.main_tabs_loaded and state.service:
                ctx.main_tabs_loaded.add('Users')
                background_tasks.create(_load_users(ctx))
            if tab == 'Text Logs' and 'Text Logs' not in ctx.main_tabs_loaded and state.service:
                ctx.main_tabs_loaded.add('Text Logs')
                background_tasks.create(_load_text_logs(ctx))
            if tab == 'Query Logs' and 'Query Logs' not in ctx.main_tabs_loaded and state.service:
                ctx.main_tabs_loaded.add('Query Logs')
                background_tasks.create(load_query_logs(ctx))
            if tab == 'QMON' and 'QMON' not in ctx.main_tabs_loaded and state.active_connection_name:
                ctx.main_tabs_loaded.add('QMON')
                _load_qmon_iframe(ctx)
            ui.timer(0.3, lambda: ui.run_javascript('window.fitStickyTables()'), once=True)

        main_tabs.on_value_change(_on_main_tab_change)

    # If already connected, show data
    if state.service:
        _build_server_info_bar(ctx)
        background_tasks.create(_load_tables(ctx))

    return ctx


def refresh_connection_options(ctx: ServerDetailsContext):
    """Refresh the connection dropdown options (e.g. after settings change)."""
    if ctx.connection_select is None:
        return
    connections = state.conn_manager.list_connections()
    ctx.connection_select.options = {
        cfg.name: f'{cfg.name} ({cfg.host}:{cfg.port})' for cfg in connections
    }
    ctx.connection_select.update()


def select_connection(ctx: ServerDetailsContext, conn_name: str):
    """Programmatically select a connection (e.g. from drill-down)."""
    if ctx.connection_select:
        ctx.connection_select.set_value(conn_name)


# ── Connection handling ──

def _on_connect(cfg, ctx: ServerDetailsContext):
    global _connecting_name
    if state.active_connection_name == cfg.name:
        return
    _connecting_name = cfg.name
    state.active_connection_name = None
    if ctx._tables_widget:
        ctx._tables_widget.props(add='loading')
    background_tasks.create(_on_connect_async(cfg, ctx))


async def _on_connect_async(cfg, ctx: ServerDetailsContext):
    global _connecting_name
    try:
        if state.client and state.client.connected:
            state.client.disconnect()

        cfg.ca_cert = state.conn_manager.ca_cert

        def _do_connect():
            client = CHClient(cfg)
            client.connect()
            return client

        client = await run.io_bound(_do_connect)
        state.client = client
        state.service = AnalysisService(client)
        state.active_connection_name = cfg.name
        _connecting_name = None

        total_disk_bytes = 0
        try:
            disks = await run.io_bound(lambda: state.service.get_disk_info())
            total_disk_bytes = sum(d['used_bytes'] for d in disks) if disks else 0
            _render_server_info_bar(ctx, disks)
        except Exception as ex:
            ctx.server_info_bar.set_visibility(False)
            ui.notify(f'Disk info error: {ex}', type='warning')

        try:
            tables_data = await run.io_bound(lambda: state.service.get_tables(log_days=state.query_log_days))
            try:
                refs_data = await run.io_bound(lambda: state.service.get_table_references())
            except Exception:
                refs_data = {}
            _render_tables(ctx, tables_data, refs_data, total_disk_bytes)
        except Exception as ex:
            ctx.tables_panel.clear()
            with ctx.tables_panel:
                ui.notify(f'Failed to load tables: {ex}', type='negative')

        _clear_columns(ctx)
        ctx.main_tabs_loaded.clear()

        if ctx.active_main_tab == 'Users':
            ctx.main_tabs_loaded.add('Users')
            await _load_users(ctx)
        elif ctx.users_panel:
            ctx.users_panel.clear()
            with ctx.users_panel:
                ui.label('Switch to Users tab to load.').classes('text-grey-7')

        if ctx.active_main_tab == 'Text Logs':
            ctx.main_tabs_loaded.add('Text Logs')
            await _load_text_logs(ctx)
        elif ctx.text_logs_panel:
            ctx.text_logs_panel.clear()
            with ctx.text_logs_panel:
                ui.label('Switch to Text Logs tab to load.').classes('text-grey-7')

        if ctx.active_main_tab == 'Query Logs':
            ctx.main_tabs_loaded.add('Query Logs')
            await load_query_logs(ctx)
        elif ctx.query_logs_panel:
            ctx.query_logs_panel.clear()
            with ctx.query_logs_panel:
                ui.label('Switch to Query Logs tab to load.').classes('text-grey-7')

        if ctx.active_main_tab == 'QMON':
            ctx.main_tabs_loaded.add('QMON')
            _load_qmon_iframe(ctx)
        elif ctx.qmon_panel:
            ctx.qmon_panel.clear()
            with ctx.qmon_panel:
                ui.label('Switch to QMON tab to load.').classes('text-grey-7 q-pa-md')

    except Exception as ex:
        _connecting_name = None
        state.active_connection_name = None
        _build_server_info_bar(ctx)
        ui.notify(f'Connection failed: {ex}', type='negative')


# ── Server info bar ──

def _build_server_info_bar(ctx: ServerDetailsContext):
    service = state.service
    if not service or not state.active_connection_name:
        ctx.server_info_bar.clear()
        ctx.server_info_bar.set_visibility(False)
        return
    try:
        disks = service.get_disk_info()
    except Exception as ex:
        ctx.server_info_bar.clear()
        ctx.server_info_bar.set_visibility(False)
        ui.notify(f'Disk info error: {ex}', type='warning')
        return
    _render_server_info_bar(ctx, disks)


def _render_server_info_bar(ctx: ServerDetailsContext, disks):
    ctx.server_info_bar.clear()
    if not disks:
        ctx.server_info_bar.set_visibility(False)
        return

    ctx.server_info_bar.set_visibility(True)
    with ctx.server_info_bar:
        for disk in disks:
            pct = float(disk['usage_percent'])
            color = 'positive' if pct < 70 else ('warning' if pct < 90 else 'negative')

            with ui.row().classes('items-center gap-4 w-full no-wrap'):
                ui.icon('dns').classes('text-grey-7')
                ui.label(state.active_connection_name).classes('text-weight-bold')
                ui.separator().props('vertical').style('height: 20px')
                ui.label(f'Disk "{disk["name"]}":').classes('text-grey-7')
                ui.label(f'{disk["used"]} / {disk["total"]}')
                ui.linear_progress(
                    value=round(pct / 100.0, 3),
                    color=color,
                ).props('rounded track-color=grey-3').style('max-width: 200px; height: 8px')
                ui.label(f'{pct:.1f}%').classes(f'text-weight-bold text-{color}')
                ui.separator().props('vertical').style('height: 20px')
                ui.label('Query log:').classes('text-grey-7')

                def _on_days_change(e, c=ctx):
                    state.query_log_days = e.value
                    background_tasks.create(_load_tables(c))
                    if 'Users' in c.main_tabs_loaded:
                        background_tasks.create(_load_users(c))

                ui.select(
                    options={7: '7d', 30: '30d', 90: '90d', 365: '1y'},
                    value=state.query_log_days,
                    on_change=_on_days_change,
                ).props('dense outlined').classes('q-ml-none').style('min-width: 70px').tooltip('Query log period')


# ── Tables ──

async def _load_tables(ctx: ServerDetailsContext):
    service = state.service
    if not service:
        ctx.tables_panel.clear()
        with ctx.tables_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    if ctx._tables_widget:
        ctx._tables_widget.props(add='loading')
    else:
        ctx.tables_panel.clear()
        with ctx.tables_panel:
            ui.spinner('dots', size='lg').classes('self-center q-mt-md')

    try:
        data = await run.io_bound(lambda: service.get_tables(log_days=state.query_log_days))
    except Exception as ex:
        ctx.tables_panel.clear()
        with ctx.tables_panel:
            ui.notify(f'Failed to load tables: {ex}', type='negative')
        return

    try:
        refs = await run.io_bound(lambda: service.get_table_references())
    except Exception:
        refs = {}

    try:
        disks = await run.io_bound(lambda: service.get_disk_info())
        total_disk_bytes = sum(d['used_bytes'] for d in disks) if disks else 0
    except Exception:
        total_disk_bytes = 0

    _render_tables(ctx, data, refs, total_disk_bytes)


def _render_tables(ctx: ServerDetailsContext, data, refs, total_disk_bytes=0):
    ctx.tables_panel.clear()
    service = state.service
    with ctx.tables_panel:
        if not data:
            ui.label('No tables found.').classes('text-grey-7')
            return

        columns = [
            {'name': 'name', 'label': 'Table', 'field': 'name', 'align': 'left', 'sortable': True, 'tooltip': 'Full table name'},
            {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes', 'tooltip': 'Disk usage'},
            {'name': 'size_pct', 'label': '%', 'field': 'size_pct', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes', 'tooltip': 'Percent of total disk'},
            {'name': 'replicated', 'label': 'R', 'field': 'replicated', 'align': 'center', 'tooltip': 'Replicated table'},
            {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True, 'tooltip': 'Referencing objects'},
            {'name': 'dist', 'label': '_d', 'field': 'dist_cnt', 'align': 'center', 'sortable': True, 'tooltip': 'Distributed references'},
            {'name': 'last_select', 'label': 'Last SELECT', 'field': 'last_select', 'align': 'center', 'tooltip': 'Last read query'},
            {'name': 'last_insert', 'label': 'Last INSERT', 'field': 'last_insert', 'align': 'center', 'tooltip': 'Last write query'},
            {'name': 'ttl', 'label': 'TTL', 'field': 'ttl', 'align': 'left', 'tooltip': 'Data retention rules'},
        ]
        rows = []
        for t in data:
            all_refs = refs.get(t['name'], [])
            normal_refs = [name for name, engine in all_refs if engine != 'Distributed']
            dist_refs = [name for name, engine in all_refs if engine == 'Distributed']
            pct = (t['size_bytes'] / total_disk_bytes * 100) if total_disk_bytes > 0 else 0
            rows.append({
                'name': t['name'],
                'size': t['size'],
                'size_bytes': t['size_bytes'],
                'size_pct': f'{pct:.1f}%' if pct >= 0.05 else '<0.1%',
                'replicated': t.get('replicated', False),
                'refs_cnt': len(normal_refs),
                'refs_list': normal_refs,
                'dist_cnt': len(dist_refs),
                'dist_list': dist_refs,
                'ttl': t.get('ttl', ''),
                'last_select': t['last_select'],
                'last_insert': t['last_insert'],
            })

        # Schema filter state
        all_schemas = sorted(set(r['name'].split('.')[0] for r in rows))
        active_schemas = set(all_schemas)
        schema_buttons: dict[str, ui.button] = {}
        all_rows = list(rows)
        tbl_ref: list[ui.table | None] = [None]

        def _update_schema_styles():
            for s, btn in schema_buttons.items():
                if s in active_schemas:
                    btn.props('push color=primary text-color=white no-caps size=sm')
                else:
                    btn.props('push color=grey-4 text-color=grey-8 no-caps size=sm')
                btn.update()

        def _apply_schema_filter():
            tbl = tbl_ref[0]
            if not tbl:
                return
            if len(active_schemas) == len(all_schemas):
                tbl.rows = all_rows
            else:
                tbl.rows = [r for r in all_rows if r['name'].split('.')[0] in active_schemas]
            tbl.update()

        def _toggle_schema(schema):
            if schema in active_schemas:
                if len(active_schemas) > 1:
                    active_schemas.discard(schema)
            else:
                active_schemas.add(schema)
            _update_schema_styles()
            _apply_schema_filter()

        def _reset_schemas():
            active_schemas.clear()
            _update_schema_styles()
            _apply_schema_filter()

        def _select_all_schemas():
            active_schemas.update(all_schemas)
            _update_schema_styles()
            _apply_schema_filter()

        with ui.row().classes('w-full items-center gap-1 no-wrap').style('margin-bottom: 2px'):
            ui.label('Schema:').classes('text-caption text-grey-7').style(
                'line-height: 28px; white-space: nowrap')
            ui.button(icon='delete_sweep', on_click=_reset_schemas).props(
                'flat dense size=sm color=grey-7'
            ).tooltip('Clear all')
            ui.button(icon='select_all', on_click=_select_all_schemas).props(
                'flat dense size=sm color=grey-7'
            ).tooltip('Show all')
            with ui.element('div').classes('flex flex-wrap gap-0'):
                for s in all_schemas:
                    btn = ui.button(s, on_click=lambda s=s: _toggle_schema(s))
                    btn.props('push color=primary text-color=white no-caps size=sm')
                    schema_buttons[s] = btn

        filter_input = ui.input(placeholder='Filter by table name...').props(
            'dense clearable'
        ).classes('q-mb-sm').style('max-width: 400px')

        tbl = ui.table(
            columns=columns,
            rows=all_rows,
            row_key='name',
            pagination={'rowsPerPage': 20, 'sortBy': 'size', 'descending': True},
        ).classes('w-full sticky-table')
        tbl_ref[0] = tbl
        ctx._tables_widget = tbl
        tbl.bind_filter_from(filter_input, 'value')
        ui.timer(0.3, lambda: ui.run_javascript('window.fitStickyTables()'), once=True)

        tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)
        tbl.add_slot(
            'body',
            r'''
            <q-tr :props="props" class="cursor-pointer"
                   @click="
                     $event.currentTarget.closest('tbody').querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                     $event.currentTarget.classList.add('table-row-active');
                     $parent.$emit('row-click', props.row)
                   ">
                <q-td key="name" :props="props">{{ props.row.name }}</q-td>
                <q-td key="size" :props="props">{{ props.row.size }}</q-td>
                <q-td key="size_pct" :props="props">{{ props.row.size_pct }}</q-td>
                <q-td key="replicated" :props="props">
                    <q-icon v-if="props.row.replicated" name="add_circle" color="primary" size="xs" />
                    <q-icon v-else name="remove" color="grey-5" size="xs" />
                </q-td>
                <q-td key="refs" :props="props">
                    <q-btn v-if="props.row.refs_cnt > 0" flat dense size="sm"
                           :label="String(props.row.refs_cnt)" color="primary"
                           @click.stop="$parent.$emit('show-refs', props.row)" />
                    <span v-else class="text-grey-5">0</span>
                </q-td>
                <q-td key="dist" :props="props">
                    <q-btn v-if="props.row.dist_cnt > 0" flat dense size="sm"
                           :label="String(props.row.dist_cnt)" color="primary"
                           @click.stop="$parent.$emit('show-dist-refs', props.row)" />
                    <span v-else class="text-grey-5">0</span>
                </q-td>
                <q-td key="last_select" :props="props">{{ props.row.last_select }}</q-td>
                <q-td key="last_insert" :props="props">{{ props.row.last_insert }}</q-td>
                <q-td key="ttl" :props="props">{{ props.row.ttl || '-' }}</q-td>
            </q-tr>
            ''',
        )

        tbl.add_slot('pagination', PAGINATION_SLOT)

        _current_detail_table = [None]

        async def on_row_click(e):
            global _suppress_right_drawer_hide
            _suppress_right_drawer_hide = True
            row = e.args
            table_name = row['name']
            if table_name == _current_detail_table[0] and ctx.right_drawer.value:
                ctx.right_drawer.hide()
                _current_detail_table[0] = None
            else:
                _current_detail_table[0] = table_name
                await _load_columns(ctx, table_name)

        tbl.on('row-click', on_row_click)

        def on_show_refs(e):
            row = e.args
            show_refs_dialog(row['name'], row.get('refs_list', []))

        tbl.on('show-refs', on_show_refs)

        def on_show_dist_refs(e):
            row = e.args
            show_refs_dialog(row['name'], row.get('dist_list', []))

        tbl.on('show-dist-refs', on_show_dist_refs)

        def _show_tables_sql():
            raw_sql = service.get_tables_sql(log_days=state.query_log_days)
            formatted = format_clickhouse_sql(raw_sql)
            escaped = html.escape(formatted)
            with ui.dialog() as sql_dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
                ui.label('Generated Queries (Tables)').classes('text-h6 q-mb-sm')
                ui.html(f'<pre style="white-space:pre-wrap;word-break:break-all;max-height:60vh;overflow:auto">{escaped}</pre>')
                with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                    copy_js = f'() => window.copyToClipboard({json.dumps(formatted)})'
                    ui.button('Copy', icon='content_copy').props('flat').on('click', js_handler=copy_js)
                    ui.button('Close', on_click=sql_dlg.close).props('flat')
            sql_dlg.open()

        def _make_tables_filename(ext):
            conn = re.sub(r'[^\w.\-]', '_', state.active_connection_name or 'export')
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            return f'{conn}_tables_{ts}.{ext}'

        def _get_filtered_tables_rows():
            return apply_text_filter(tbl.rows, columns, filter_input.value)

        with ui.row().classes('q-mt-sm gap-2'):
            ui.button('Refresh', icon='refresh',
                      on_click=lambda: background_tasks.create(_load_tables(ctx))).props(
                'flat dense color=primary'
            ).tooltip('Reload table data')
            ui.button(icon='code', on_click=_show_tables_sql).props(
                'flat dense color=primary'
            ).tooltip('Show generated SQL')
            transforms = {'replicated': lambda v: 'Yes' if v else 'No'}
            ui.button(icon='download', on_click=lambda: export_table_csv(
                _get_filtered_tables_rows(), columns, _make_tables_filename('csv'), transforms,
            )).props('flat dense color=primary').tooltip('Export to CSV')
            ui.button(icon='table_chart', on_click=lambda: export_table_excel(
                _get_filtered_tables_rows(), columns, _make_tables_filename('xlsx'), transforms, 'Tables',
            )).props('flat dense color=primary').tooltip('Export to Excel')


# ── Columns (right drawer) ──

async def _load_columns(ctx: ServerDetailsContext, full_table_name: str):
    ctx.columns_panel.clear()
    service = state.service
    if not service:
        return

    with ctx.columns_panel:
        ui.spinner('dots', size='lg').classes('self-center q-mt-md')

    if ctx.drawer_title:
        ctx.drawer_title.text = 'Table Details'
    safe_name = json.dumps(full_table_name)
    ui.run_javascript(f'window.selectedTableName = {safe_name}')
    ctx.right_drawer.set_value(True)

    ui.run_javascript('''
        setTimeout(function() {
            var name = window.selectedTableName;
            if (!name) return;
            document.querySelectorAll('.table-row-active').forEach(function(r) { r.classList.remove('table-row-active'); });
            document.querySelectorAll('tbody tr td:first-child').forEach(function(td) {
                if (td.textContent.trim() === name) td.closest('tr').classList.add('table-row-active');
            });
        }, 150);
    ''')

    try:
        disks = await run.io_bound(lambda: service.get_disk_info())
        total_disk_bytes = sum(d['used_bytes'] for d in disks) if disks else 0
    except Exception:
        total_disk_bytes = 0

    try:
        columns_data = await run.io_bound(lambda: service.get_columns(full_table_name))
    except Exception as ex:
        ctx.columns_panel.clear()
        with ctx.columns_panel:
            ui.notify(f'Failed to load columns: {ex}', type='negative')
        return

    try:
        col_refs = await run.io_bound(lambda: service.get_column_references(full_table_name))
    except Exception:
        col_refs = {}

    ctx.columns_panel.clear()
    with ctx.columns_panel:
        ui.label(full_table_name).classes(
            'text-subtitle1 text-weight-bold text-center w-full q-pa-xs'
        ).style('border: 1px solid #9e9e9e; border-radius: 4px')

        with ui.tabs().classes('w-full').props('dense') as tabs:
            columns_tab = ui.tab('Columns').tooltip('Column details')
            history_tab = ui.tab('Query History').tooltip('Query history')
            flow_tab = ui.tab('Flow').tooltip('Data flow diagrams')

        loaded_tabs = set()

        with ui.tab_panels(tabs, value=columns_tab).classes('w-full q-pt-none') as tab_panels:
            with ui.tab_panel(columns_tab).classes('q-pa-xs'):
                _render_columns_tab(columns_data, col_refs, full_table_name, total_disk_bytes)
                loaded_tabs.add('Columns')
            with ui.tab_panel(history_tab).classes('q-pa-xs') as history_panel:
                pass
            with ui.tab_panel(flow_tab).classes('q-pa-xs') as flow_panel:
                pass

        async def _on_tab_change(e):
            name = e.value
            if name in loaded_tabs:
                return
            loaded_tabs.add(name)
            if name == 'Query History':
                with history_panel:
                    ui.spinner('dots', size='lg').classes('self-center q-mt-md')
                await _render_query_history_tab_async(service, full_table_name, history_panel)
            elif name == 'Flow':
                with flow_panel:
                    ui.spinner('dots', size='lg').classes('self-center q-mt-md')
                await _render_flow_tab_async(service, full_table_name, flow_panel)

        tabs.on_value_change(lambda e: background_tasks.create(_on_tab_change(e)))


def _clear_columns(ctx: ServerDetailsContext):
    ctx.columns_panel.clear()
    if ctx.right_drawer:
        ctx.right_drawer.hide()
    with ctx.columns_panel:
        ui.label('Select a table.').classes('text-grey-7')


def _render_columns_tab(data, col_refs, full_table_name: str, total_disk_bytes: int = 0):
    if not data:
        ui.label('No columns found.').classes('text-grey-7')
        return

    table_total_bytes = sum(c.get('size_bytes', 0) for c in data)

    columns = [
        {'name': 'name', 'label': 'Column', 'field': 'name', 'align': 'left', 'sortable': True, 'tooltip': 'Column name'},
        {'name': 'type', 'label': 'Type', 'field': 'type', 'align': 'left', 'sortable': True, 'tooltip': 'Data type'},
        {'name': 'codec', 'label': 'Codec', 'field': 'codec', 'align': 'left', 'tooltip': 'Compression codec'},
        {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes', 'tooltip': 'Disk usage'},
        {'name': 'size_pct', 'label': '%', 'field': 'size_pct', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes', 'tooltip': '% of table / server'},
        {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True, 'tooltip': 'Referencing objects'},
        {'name': 'dist', 'label': '_d', 'field': 'dist_cnt', 'align': 'center', 'sortable': True, 'tooltip': 'Distributed references'},
    ]
    rows = []
    for c in data:
        all_refs = col_refs.get(c['name'], [])
        normal_refs = [name for name, engine in all_refs if engine != 'Distributed']
        dist_refs = [name for name, engine in all_refs if engine == 'Distributed']
        col_bytes = c.get('size_bytes', 0)
        tbl_pct = (col_bytes / table_total_bytes * 100) if table_total_bytes > 0 else 0
        srv_pct = (col_bytes / total_disk_bytes * 100) if total_disk_bytes > 0 else 0
        tbl_pct_str = f'{tbl_pct:.1f}' if tbl_pct >= 0.05 else '<0.1'
        srv_pct_str = f'{srv_pct:.1f}' if srv_pct >= 0.05 else '<0.1'
        rows.append({
            'name': c['name'],
            'type': c['type'],
            'codec': c.get('codec', ''),
            'size': c.get('size', '0 B'),
            'size_bytes': col_bytes,
            'size_pct': f'{tbl_pct_str}% / {srv_pct_str}%',
            'refs_cnt': len(normal_refs),
            'refs_list': normal_refs,
            'dist_cnt': len(dist_refs),
            'dist_list': dist_refs,
        })

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='name',
        pagination={'rowsPerPage': 0, 'sortBy': 'size', 'descending': True},
    ).classes('w-full')

    tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)
    tbl.add_slot(
        'body',
        r'''
        <q-tr :props="props">
            <q-td key="name" :props="props">{{ props.row.name }}</q-td>
            <q-td key="type" :props="props">{{ props.row.type }}</q-td>
            <q-td key="codec" :props="props">{{ props.row.codec }}</q-td>
            <q-td key="size" :props="props">{{ props.row.size }}</q-td>
            <q-td key="size_pct" :props="props">{{ props.row.size_pct }}</q-td>
            <q-td key="refs" :props="props">
                <q-btn v-if="props.row.refs_cnt > 0" flat dense size="sm"
                       :label="String(props.row.refs_cnt)" color="primary"
                       @click.stop="$parent.$emit('show-refs', props.row)" />
                <span v-else class="text-grey-5">0</span>
            </q-td>
            <q-td key="dist" :props="props">
                <q-btn v-if="props.row.dist_cnt > 0" flat dense size="sm"
                       :label="String(props.row.dist_cnt)" color="primary"
                       @click.stop="$parent.$emit('show-dist-refs', props.row)" />
                <span v-else class="text-grey-5">0</span>
            </q-td>
        </q-tr>
        ''',
    )

    def on_show_col_refs(e):
        row = e.args
        show_refs_dialog(row['name'], row.get('refs_list', []))

    tbl.on('show-refs', on_show_col_refs)

    def on_show_col_dist_refs(e):
        row = e.args
        show_refs_dialog(row['name'], row.get('dist_list', []))

    tbl.on('show-dist-refs', on_show_col_dist_refs)

    def _make_cols_filename(ext):
        conn = re.sub(r'[^\w.\-]', '_', state.active_connection_name or 'export')
        tname = re.sub(r'[^\w.\-]', '_', full_table_name)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f'{conn}_{tname}_columns_{ts}.{ext}'

    with ui.row().classes('q-mt-xs gap-2'):
        ui.button(icon='download', on_click=lambda: export_table_csv(
            tbl.rows, columns, _make_cols_filename('csv'),
        )).props('flat dense color=primary').tooltip('Export to CSV')
        ui.button(icon='table_chart', on_click=lambda: export_table_excel(
            tbl.rows, columns, _make_cols_filename('xlsx'), sheet_name='Columns',
        )).props('flat dense color=primary').tooltip('Export to Excel')


# ── Query History ──

async def _render_query_history_tab_async(service, full_table_name: str, panel):
    try:
        filters = await run.io_bound(
            lambda: service.get_query_history_filters(full_table_name, log_days=state.query_log_days))
    except Exception as ex:
        panel.clear()
        with panel:
            ui.notify(f'Failed to load query history filters: {ex}', type='negative')
        return
    panel.clear()
    with panel:
        _render_query_history_tab(filters, service, full_table_name)


def _render_query_history_tab(filters, service, full_table_name: str):
    unique_users = filters['users']
    unique_kinds = filters['kinds']
    counts = filters['counts']

    if not unique_users and not unique_kinds:
        ui.label('No query history found.').classes('text-grey-7')
        return

    active_users = set(unique_users)
    active_kinds = set(unique_kinds)
    current_limit = [200]

    user_kind_matrix: dict[str, set[str]] = {}
    kind_user_matrix: dict[str, set[str]] = {}
    for c in counts:
        user_kind_matrix.setdefault(c['user'], set()).add(c['query_kind'])
        kind_user_matrix.setdefault(c['query_kind'], set()).add(c['user'])

    user_buttons: dict[str, ui.button] = {}
    kind_buttons: dict[str, ui.button] = {}

    def _update_button_states():
        if active_users:
            available_kinds = set()
            for u in active_users:
                available_kinds |= user_kind_matrix.get(u, set())
        else:
            available_kinds = set(unique_kinds)

        if active_kinds:
            available_users = set()
            for k in active_kinds:
                available_users |= kind_user_matrix.get(k, set())
        else:
            available_users = set(unique_users)

        for u, btn in user_buttons.items():
            if u not in available_users:
                btn.props('push color=grey-4 text-color=grey-5 disable')
            elif u in active_users:
                btn.props('push color=primary text-color=white')
                btn.props(remove='disable')
            else:
                btn.props('push color=grey-4 text-color=grey-8')
                btn.props(remove='disable')
            btn.update()

        for k, btn in kind_buttons.items():
            if k not in available_kinds:
                btn.props('push color=grey-4 text-color=grey-5 disable')
            elif k in active_kinds:
                btn.props('push color=primary text-color=white')
                btn.props(remove='disable')
            else:
                btn.props('push color=grey-4 text-color=grey-8')
                btn.props(remove='disable')
            btn.update()

    direct_only = [True]

    def _refresh():
        users_param = sorted(active_users) if len(active_users) < len(unique_users) else None
        kinds_param = sorted(active_kinds) if len(active_kinds) < len(unique_kinds) else None
        try:
            data = service.get_query_history(
                full_table_name,
                limit=current_limit[0],
                users=users_param,
                kinds=kinds_param,
                direct_only=direct_only[0],
                log_days=state.query_log_days,
            )
        except Exception as ex:
            ui.notify(f'Failed to load query history: {ex}', type='negative')
            return

        rows = []
        for r in data:
            row = {
                'event_time': r['event_time'],
                'user': r['user'],
                'query_kind': r['query_kind'],
                'query_short': r['query'][:50] + ('...' if len(r['query']) > 50 else ''),
                'query_full': r['query'],
            }
            if not direct_only[0]:
                row['direct'] = '+' if r.get('is_direct') else ''
            rows.append(row)
        _rebuild_table(rows)

    def _rebuild_table(rows):
        table_container.clear()
        with table_container:
            if not rows:
                ui.label('No query history found.').classes('text-grey-7')
                return

            filter_input = ui.input(placeholder='Filter...').props('dense clearable').classes('q-mb-sm w-full')

            columns = [
                {'name': 'event_time', 'label': 'Time', 'field': 'event_time', 'align': 'left', 'sortable': True, 'tooltip': 'Query execution time'},
                {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True, 'tooltip': 'ClickHouse user'},
                {'name': 'query_kind', 'label': 'Kind', 'field': 'query_kind', 'align': 'center', 'sortable': True, 'tooltip': 'Query type'},
                {'name': 'query', 'label': 'Query', 'field': 'query_short', 'align': 'left', 'tooltip': 'Query text (truncated)'},
            ]
            if not direct_only[0]:
                columns.insert(3, {'name': 'direct', 'label': 'Direct', 'field': 'direct', 'align': 'center', 'sortable': True, 'tooltip': 'Direct table reference'})

            body_slot = r'''
                <q-tr :props="props" class="cursor-pointer"
                       @click="$parent.$emit('show-query', props.row)">
                    <q-td key="event_time" :props="props">{{ props.row.event_time }}</q-td>
                    <q-td key="user" :props="props">{{ props.row.user }}</q-td>
                    <q-td key="query_kind" :props="props">{{ props.row.query_kind }}</q-td>'''
            if not direct_only[0]:
                body_slot += r'''
                    <q-td key="direct" :props="props">{{ props.row.direct }}</q-td>'''
            body_slot += r'''
                    <q-td key="query" :props="props" style="max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                        {{ props.row.query_short }}
                    </q-td>
                </q-tr>'''

            tbl = ui.table(
                columns=columns,
                rows=rows,
                row_key='event_time',
                pagination={'rowsPerPage': 20, 'sortBy': 'event_time', 'descending': True},
            ).classes('w-full')

            tbl.bind_filter_from(filter_input, 'value')
            tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)
            tbl.add_slot('body', body_slot)

            def _highlight_table(sql_text, table_name):
                parts = [re.escape(table_name)]
                if '.' in table_name:
                    parts.append(re.escape(table_name.split('.', 1)[1]))
                pattern = '|'.join(parts)
                return re.sub(
                    f'({pattern})',
                    r'<mark style="background:#fff176;padding:1px 3px;border-radius:2px">\1</mark>',
                    sql_text,
                )

            def on_show_query(e):
                row = e.args
                formatted = format_clickhouse_sql(row['query_full'])
                escaped = html.escape(formatted)
                highlighted = _highlight_table(escaped, full_table_name)

                with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
                    ui.label('Query').classes('text-h6 q-mb-sm')

                    sql_container = ui.html(
                        f'<pre style="white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;">{highlighted}</pre>'
                    )

                    def on_highlight_toggle(e_val):
                        content = highlighted if e_val.value else escaped
                        sql_container.content = (
                            f'<pre style="white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;">{content}</pre>'
                        )
                        sql_container.update()

                    with ui.row().classes('w-full items-center justify-between q-mt-md'):
                        ui.switch('Highlight table', value=True, on_change=on_highlight_toggle)
                        with ui.row().classes('gap-2'):
                            copy_js = f'() => window.copyToClipboard({json.dumps(formatted)})'
                            ui.button('Copy', icon='content_copy').props('flat').on('click', js_handler=copy_js)
                            ui.button('Close', on_click=dlg.close).props('flat')
                dlg.open()

            tbl.on('show-query', on_show_query)

    def toggle_user(user):
        if user in active_users:
            active_users.discard(user)
        else:
            active_users.add(user)
        _update_button_states()
        _refresh()

    def toggle_kind(kind):
        if kind in active_kinds:
            active_kinds.discard(kind)
        else:
            active_kinds.add(kind)
        _update_button_states()
        _refresh()

    def reset_users():
        active_users.clear()
        _update_button_states()
        _refresh()

    def select_all_users():
        active_users.update(unique_users)
        _update_button_states()
        _refresh()

    def reset_kinds():
        active_kinds.clear()
        _update_button_states()
        _refresh()

    def select_all_kinds():
        active_kinds.update(unique_kinds)
        _update_button_states()
        _refresh()

    def _show_generated_query():
        raw_sql = service.get_query_history_sql(
            full_table_name,
            limit=current_limit[0],
            users=sorted(active_users) if len(active_users) < len(unique_users) else None,
            kinds=sorted(active_kinds) if len(active_kinds) < len(unique_kinds) else None,
            direct_only=direct_only[0],
            log_days=state.query_log_days,
        )
        formatted = format_clickhouse_sql(raw_sql)
        escaped = html.escape(formatted)
        with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
            ui.label('Generated Query').classes('text-h6 q-mb-sm')
            ui.html(f'<pre style="white-space:pre-wrap;word-break:break-all;max-height:60vh;overflow:auto">{escaped}</pre>')
            with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                copy_js = f'() => window.copyToClipboard({json.dumps(formatted)})'
                ui.button('Copy', icon='content_copy').props('flat').on('click', js_handler=copy_js)
                ui.button('Close', on_click=dlg.close).props('flat')
        dlg.open()

    def _reload_filters_and_refresh():
        nonlocal unique_users, unique_kinds, counts
        try:
            new_filters = service.get_query_history_filters(full_table_name, direct_only=direct_only[0], log_days=state.query_log_days)
        except Exception:
            new_filters = {"users": [], "kinds": [], "counts": []}
        unique_users = new_filters['users']
        unique_kinds = new_filters['kinds']
        counts = new_filters['counts']
        user_kind_matrix.clear()
        kind_user_matrix.clear()
        for c in counts:
            user_kind_matrix.setdefault(c['user'], set()).add(c['query_kind'])
            kind_user_matrix.setdefault(c['query_kind'], set()).add(c['user'])
        active_users.intersection_update(unique_users)
        if not active_users:
            active_users.update(unique_users)
        active_kinds.intersection_update(unique_kinds)
        if not active_kinds:
            active_kinds.update(unique_kinds)
        _rebuild_filter_buttons()
        _refresh()

    def _rebuild_filter_buttons():
        user_buttons.clear()
        kind_buttons.clear()
        user_btn_container.clear()
        kind_btn_container.clear()
        with user_btn_container:
            for u in unique_users:
                btn = ui.button(u, on_click=lambda u=u: toggle_user(u))
                btn.props('push color=primary text-color=white no-caps size=sm')
                user_buttons[u] = btn
        with kind_btn_container:
            for k in unique_kinds:
                btn = ui.button(k, on_click=lambda k=k: toggle_kind(k))
                btn.props('push color=primary text-color=white no-caps size=sm')
                kind_buttons[k] = btn
        _update_button_states()

    # Filter controls
    with ui.row().classes('w-full items-start gap-1 no-wrap').style('margin-bottom: 2px'):
        ui.label('User:').classes('text-caption text-grey-7').style('line-height: 28px; white-space: nowrap')
        ui.button(icon='delete_sweep', on_click=reset_users).props(
            'flat dense size=sm color=grey-7'
        ).tooltip('Clear all')
        ui.button(icon='select_all', on_click=select_all_users).props(
            'flat dense size=sm color=grey-7'
        ).tooltip('Show all')
        with ui.element('div').classes('flex flex-wrap gap-0') as user_btn_container:
            for u in unique_users:
                btn = ui.button(u, on_click=lambda u=u: toggle_user(u))
                btn.props('push color=primary text-color=white no-caps size=sm')
                user_buttons[u] = btn

    with ui.row().classes('w-full items-center gap-1 no-wrap').style('margin-bottom: 2px'):
        ui.label('Kind:').classes('text-caption text-grey-7').style('white-space: nowrap')
        ui.button(icon='delete_sweep', on_click=reset_kinds).props(
            'flat dense size=sm color=grey-7'
        ).tooltip('Clear all')
        ui.button(icon='select_all', on_click=select_all_kinds).props(
            'flat dense size=sm color=grey-7'
        ).tooltip('Show all')
        with ui.element('div').classes('flex flex-wrap gap-0') as kind_btn_container:
            for k in unique_kinds:
                btn = ui.button(k, on_click=lambda k=k: toggle_kind(k))
                btn.props('push color=primary text-color=white no-caps size=sm')
                kind_buttons[k] = btn

    with ui.row().classes('w-full items-center gap-4').style('margin-bottom: 2px'):
        ui.label('Limit:').classes('text-caption text-grey-7')
        ui.select(
            [50, 100, 200, 500, 1000], value=200,
            on_change=lambda e: (current_limit.__setitem__(0, e.value), _refresh()),
        ).props('dense borderless').style('min-width: 80px').tooltip('Results limit')

        ui.switch('Direct', value=True,
                  on_change=lambda e: (direct_only.__setitem__(0, e.value), _reload_filters_and_refresh()),
                  ).tooltip('Show only queries that directly mention the table name')

        ui.button(icon='code', on_click=_show_generated_query).props(
            'flat dense color=primary'
        ).tooltip('Show generated SQL')

        ui.button('Refresh', icon='refresh', on_click=_refresh).props('flat dense color=primary').tooltip('Reload history')

    table_container = ui.column().classes('w-full')
    _refresh()


# ── Flow ──

async def _render_flow_tab_async(service, full_table_name: str, panel):
    try:
        mv_flow = await run.io_bound(lambda: service.get_mv_flow(full_table_name))
    except Exception:
        mv_flow = {'nodes': [], 'edges': []}
    try:
        query_flow = await run.io_bound(
            lambda: service.get_query_flow(full_table_name, log_days=state.query_log_days))
    except Exception:
        query_flow = {'nodes': [], 'edges': []}
    panel.clear()
    with panel:
        _render_flow_tab(mv_flow, query_flow, full_table_name)


def _render_flow_tab(mv_flow, query_flow, full_table_name: str):
    with ui.tabs().classes('w-full').props('dense') as sub_tabs:
        mv_tab = ui.tab('MV Flow').tooltip('Materialized view chains')
        query_tab = ui.tab('Query Flow').tooltip('INSERT…SELECT pipelines')
        full_tab = ui.tab('Full Flow').tooltip('Combined data flow')

    sub_tabs.on_value_change(
        lambda: ui.timer(0.3, lambda: ui.run_javascript('window.initMermaidDrag()'), once=True)
    )

    with ui.tab_panels(sub_tabs, value=mv_tab).classes('w-full'):
        with ui.tab_panel(mv_tab):
            mermaid_text = flow_to_mermaid(mv_flow, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No materialized view flow found.').classes('text-grey-7')

        with ui.tab_panel(query_tab):
            mermaid_text = flow_to_mermaid(query_flow, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No query-based data flow found.').classes('text-grey-7')

        with ui.tab_panel(full_tab):
            all_nodes = {n['id']: n for n in mv_flow['nodes']}
            for n in query_flow['nodes']:
                if n['id'] not in all_nodes:
                    all_nodes[n['id']] = n

            all_edges_set = set()
            all_edges = []
            for e in mv_flow['edges'] + query_flow['edges']:
                key = (e['from'], e['to'])
                if key not in all_edges_set:
                    all_edges_set.add(key)
                    all_edges.append(e)

            merged = {'nodes': list(all_nodes.values()), 'edges': all_edges}
            mermaid_text = flow_to_mermaid(merged, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No data flow found.').classes('text-grey-7')


# ── Text Logs ──

def _load_qmon_iframe(ctx: ServerDetailsContext):
    """Build the QMON iframe inside the qmon panel."""
    if not ctx.qmon_panel:
        return
    ctx.qmon_panel.clear()

    qmon_url = state.app_settings.get('QMON_URL', '').strip().rstrip('/')
    if not qmon_url:
        with ctx.qmon_panel:
            ui.label('QMON URL not configured. Set it in Settings → QMON.'
                     ).classes('text-grey-7 q-pa-md')
        return

    qmon_alias = ''
    if state.active_connection_name:
        cfg = state.conn_manager.get_connection(state.active_connection_name)
        if cfg:
            qmon_alias = cfg.qmon_alias or ''

    iframe_url = qmon_url + (f'?include={qmon_alias}' if qmon_alias else '')

    with ctx.qmon_panel:
        ui.html(
            f'<iframe src="{iframe_url}" '
            f'style="width: 100%; height: 100%; border: none;" '
            f'allow="clipboard-write"></iframe>'
        )


async def _load_text_logs(ctx: ServerDetailsContext):
    ctx.text_logs_panel.clear()
    service = state.service
    if not service:
        with ctx.text_logs_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    with ctx.text_logs_panel:
        ui.spinner('dots', size='lg').classes('self-center q-mt-md')

    try:
        data = await run.io_bound(lambda: service.get_text_log_summary())
    except Exception as ex:
        ctx.text_logs_panel.clear()
        with ctx.text_logs_panel:
            ui.label(f'Failed to load text logs: {ex}').classes('text-negative')
        return

    ctx.text_logs_panel.clear()
    with ctx.text_logs_panel:
        if not data:
            ui.label('No text log entries found (level <= Warning, last 2 weeks).').classes('text-grey-7')
            return

        with ui.splitter(value=100).classes('w-full') as splitter:
            with splitter.before:
                ui.button('Refresh', icon='refresh',
                          on_click=lambda: background_tasks.create(
                              _load_text_logs(ctx))).props('flat dense color=primary').tooltip('Reload logs')

                columns = [
                    {'name': 'thread_name', 'label': 'Thread', 'field': 'thread_name', 'align': 'left', 'sortable': True, 'tooltip': 'Thread name'},
                    {'name': 'level_name', 'label': 'Level', 'field': 'level_name', 'align': 'center', 'sortable': True, 'tooltip': 'Log severity'},
                    {'name': 'max_time', 'label': 'Last Seen', 'field': 'max_time', 'align': 'center', 'sortable': True, 'tooltip': 'Last occurrence'},
                    {'name': 'cnt', 'label': 'Count', 'field': 'cnt', 'align': 'right', 'sortable': True,
                     ':sort': '(a, b) => a - b', 'tooltip': 'Number of entries'},
                    {'name': 'message_example', 'label': 'Message Example', 'field': 'message_example', 'align': 'left', 'tooltip': 'Message preview'},
                ]
                rows = []
                for i, r in enumerate(data):
                    msg = r['message_example']
                    rows.append({
                        '_row_id': i,
                        'thread_name': r['thread_name'],
                        'level': r['level'],
                        'level_name': r['level_name'],
                        'message_example': msg[:100] + ('...' if len(msg) > 100 else ''),
                        'max_time': r['max_time'],
                        'cnt': r['cnt'],
                    })

                tbl = ui.table(
                    columns=columns,
                    rows=rows,
                    row_key='_row_id',
                    pagination={'rowsPerPage': 20, 'sortBy': 'max_time', 'descending': True},
                ).classes('w-full sticky-table')
                ui.timer(0.3, lambda: ui.run_javascript('window.fitStickyTables()'), once=True)

                tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)
                tbl.add_slot('body', r'''
                    <q-tr :props="props">
                        <q-td key="thread_name" :props="props">
                            <q-btn flat dense no-caps size="sm" color="primary"
                                   :label="props.row.thread_name"
                                   @click.stop="$parent.$emit('thread-click', props.row)" />
                        </q-td>
                        <q-td key="level_name" :props="props">
                            <q-badge :color="
                                props.row.level_name === 'Fatal' ? 'black' :
                                props.row.level_name === 'Critical' ? 'deep-purple' :
                                props.row.level_name === 'Error' ? 'negative' :
                                'warning'
                            " :label="props.row.level_name" />
                        </q-td>
                        <q-td key="max_time" :props="props">{{ props.row.max_time }}</q-td>
                        <q-td key="cnt" :props="props">{{ props.row.cnt.toLocaleString() }}</q-td>
                        <q-td key="message_example" :props="props">
                            <span class="text-caption">{{ props.row.message_example }}</span>
                        </q-td>
                    </q-tr>
                ''')

            with splitter.after:
                with ui.row().classes('w-full justify-between items-center q-mb-xs'):
                    ui.label('Details').classes('text-subtitle2')
                    ui.button(icon='close', on_click=lambda: splitter.set_value(100)).props('flat dense size=sm').tooltip('Hide detail panel')
                detail_panel = ui.column().classes('w-full q-pa-sm')
                with detail_panel:
                    ui.label('Click a thread name to see details.').classes('text-grey-7')

        def on_thread_click(e):
            row = e.args
            splitter.set_value(55)
            _load_text_log_detail(detail_panel, row['thread_name'], row.get('level'))

        tbl.on('thread-click', on_thread_click)


def _load_text_log_detail(detail_panel, thread_name: str, level: int | None = None):
    detail_panel.clear()
    service = state.service
    if not service:
        return

    try:
        data = service.get_text_log_detail(thread_name, level)
    except Exception as ex:
        with detail_panel:
            ui.label(f'Failed to load detail: {ex}').classes('text-negative')
        return

    all_columns = ['event_time_microseconds', 'thread_name', 'level_name', 'query_id', 'logger_name', 'message']
    col_labels = {
        'event_time_microseconds': 'Time',
        'thread_name': 'Thread',
        'level_name': 'Level',
        'query_id': 'Query ID',
        'logger_name': 'Logger',
        'message': 'Message',
    }
    saved_visible = app.storage.tab.get('text_log_detail_visible_cols')
    if saved_visible and isinstance(saved_visible, dict):
        visible_cols = {c: saved_visible.get(c, c != 'thread_name') for c in all_columns}
    else:
        visible_cols = {c: (c != 'thread_name') for c in all_columns}

    with detail_panel:
        ui.label(f'Thread: {thread_name}').classes('text-subtitle1 text-weight-bold q-mb-xs')

        if not data:
            ui.label('No entries found.').classes('text-grey-7')
            return

        toggle_buttons: dict = {}
        with ui.row().classes('w-full flex-wrap gap-1 q-mb-sm'):
            for col in all_columns:
                btn = ui.button(col_labels[col])
                if visible_cols[col]:
                    btn.props('push color=primary text-color=white no-caps size=sm')
                else:
                    btn.props('push color=grey-4 text-color=grey-8 no-caps size=sm')
                toggle_buttons[col] = btn

        col_defs = []
        for c in all_columns:
            col_defs.append({
                'name': c, 'label': col_labels[c],
                'field': c, 'align': 'left', 'sortable': True,
            })

        detail_rows = [{c: r.get(c, '') for c in all_columns} for r in data]

        detail_tbl = ui.table(
            columns=col_defs,
            rows=detail_rows,
            row_key='event_time_microseconds',
            pagination={'rowsPerPage': 50, 'sortBy': 'event_time_microseconds', 'descending': True},
        ).classes('w-full sticky-table')
        ui.timer(0.3, lambda: ui.run_javascript('window.fitStickyTables()'), once=True)

        detail_tbl.add_slot('body', r'''
            <q-tr :props="props">
                <q-td key="event_time_microseconds" :props="props">
                    {{ props.row.event_time_microseconds }}
                </q-td>
                <q-td key="thread_name" :props="props">
                    {{ props.row.thread_name }}
                </q-td>
                <q-td key="level_name" :props="props">
                    <q-badge :color="
                        props.row.level_name === 'Fatal' ? 'black' :
                        props.row.level_name === 'Critical' ? 'deep-purple' :
                        props.row.level_name === 'Error' ? 'negative' :
                        props.row.level_name === 'Warning' ? 'warning' :
                        'grey'
                    " :label="props.row.level_name" />
                </q-td>
                <q-td key="query_id" :props="props">
                    {{ props.row.query_id }}
                </q-td>
                <q-td key="logger_name" :props="props">
                    {{ props.row.logger_name }}
                </q-td>
                <q-td key="message" :props="props" style="max-width: 600px">
                    <div class="row items-center no-wrap">
                        <q-btn flat dense round size="sm" icon="visibility" color="primary"
                               @click.stop="$parent.$emit('show-message', props.row)"
                               class="q-mr-xs">
                            <q-tooltip anchor="top middle" self="bottom middle">View full message</q-tooltip>
                        </q-btn>
                        <span class="ellipsis" style="max-width: 550px; display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            {{ props.row.message }}
                        </span>
                    </div>
                </q-td>
            </q-tr>
        ''')

        def on_show_message(e):
            row = e.args
            msg = row.get('message', '')
            escaped_msg = html.escape(msg)
            with ui.dialog() as msg_dlg, ui.card().classes('q-pa-md').style('min-width: 500px; max-width: 80vw'):
                ui.label('Message').classes('text-h6 q-mb-sm')
                ui.html(
                    f'<pre style="white-space: pre-wrap; word-break: break-word; '
                    f'max-height: 60vh; overflow: auto; font-size: 0.85rem; '
                    f'background: #f5f5f5; padding: 12px; border-radius: 4px;">'
                    f'{escaped_msg}</pre>'
                )
                with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                    copy_js = f'() => window.copyToClipboard({json.dumps(msg)})'
                    ui.button('Copy', icon='content_copy').props('flat').on('click', js_handler=copy_js)
                    ui.button('Close', on_click=msg_dlg.close).props('flat')
            msg_dlg.open()

        detail_tbl.on('show-message', on_show_message)

        initial_visible = [c for c in all_columns if visible_cols[c]]
        detail_tbl._props['visible-columns'] = initial_visible
        detail_tbl.update()

        def _toggle_col(col_name):
            visible_cols[col_name] = not visible_cols[col_name]
            btn = toggle_buttons[col_name]
            if visible_cols[col_name]:
                btn.props('push color=primary text-color=white no-caps size=sm')
            else:
                btn.props('push color=grey-4 text-color=grey-8 no-caps size=sm')
            btn.update()
            detail_tbl._props['visible-columns'] = [c for c in all_columns if visible_cols[c]]
            detail_tbl.update()
            app.storage.tab['text_log_detail_visible_cols'] = dict(visible_cols)

        for col in all_columns:
            toggle_buttons[col].on_click(lambda c=col: _toggle_col(c))


# ── Users ──

async def _load_users(ctx: ServerDetailsContext):
    ctx.users_panel.clear()
    service = state.service
    if not service:
        with ctx.users_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    with ctx.users_panel:
        ui.spinner('dots', size='lg').classes('self-center q-mt-md')

    try:
        data = await run.io_bound(lambda: service.get_user_stats(log_days=state.query_log_days))
    except Exception as ex:
        ctx.users_panel.clear()
        with ctx.users_panel:
            ui.label(f'Failed to load user stats: {ex}').classes('text-negative')
        return

    ctx.users_panel.clear()
    with ctx.users_panel:
        if not data:
            ui.label('No user statistics found.').classes('text-grey-7')
            return

        all_users = [r['user'] for r in data]
        active_users = set(all_users)
        user_buttons: dict[str, ui.button] = {}

        all_rows = [
            {
                'user': r['user'],
                'query_count': r['query_count'],
                'last_query_time': r['last_query_time'],
                'total_duration_sec': round(r['total_duration_sec'], 1),
                'total_read': r['total_read'],
                'total_read_bytes': r['total_read_bytes'],
                'total_read_rows': r['total_read_rows'],
                'total_written': r['total_written'],
                'total_written_bytes': r['total_written_bytes'],
                'total_written_rows': r['total_written_rows'],
                'peak_memory': r['peak_memory'],
                'peak_memory_bytes': r['peak_memory_bytes'],
                'selects': r['selects'],
                'inserts': r['inserts'],
                'other_queries': r['other_queries'],
            }
            for r in data
        ]

        columns = [
            {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True, 'tooltip': 'ClickHouse user'},
            {'name': 'query_count', 'label': 'Queries', 'field': 'query_count', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b', 'tooltip': 'Total query count'},
            {'name': 'last_query_time', 'label': 'Last Query', 'field': 'last_query_time', 'align': 'center', 'sortable': True, 'tooltip': 'Most recent query'},
            {'name': 'total_duration_sec', 'label': 'Total Time (s)', 'field': 'total_duration_sec', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b', 'tooltip': 'Cumulative duration'},
            {'name': 'total_read', 'label': 'Read', 'field': 'total_read', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.total_read_bytes - rowB.total_read_bytes', 'tooltip': 'Data read total'},
            {'name': 'total_written', 'label': 'Written', 'field': 'total_written', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.total_written_bytes - rowB.total_written_bytes', 'tooltip': 'Data written total'},
            {'name': 'peak_memory', 'label': 'Peak Mem', 'field': 'peak_memory', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.peak_memory_bytes - rowB.peak_memory_bytes', 'tooltip': 'Max memory usage'},
            {'name': 'selects', 'label': 'SELECTs', 'field': 'selects', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b', 'tooltip': 'Read query count'},
            {'name': 'inserts', 'label': 'INSERTs', 'field': 'inserts', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b', 'tooltip': 'Write query count'},
            {'name': 'other_queries', 'label': 'Other', 'field': 'other_queries', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b', 'tooltip': 'Other query count'},
        ]

        def _update_button_styles():
            for u, btn in user_buttons.items():
                if u in active_users:
                    btn.props('push color=primary text-color=white no-caps size=sm')
                else:
                    btn.props('push color=grey-4 text-color=grey-8 no-caps size=sm')
                btn.update()

        def _apply_filter():
            if len(active_users) == len(all_users):
                tbl.rows = all_rows
            else:
                tbl.rows = [r for r in all_rows if r['user'] in active_users]
            tbl.update()

        def _toggle_user(user):
            if user in active_users:
                if len(active_users) > 1:
                    active_users.discard(user)
            else:
                active_users.add(user)
            _update_button_styles()
            _apply_filter()

        def _reset_users():
            active_users.clear()
            _update_button_styles()
            _apply_filter()

        def _select_all_users():
            active_users.update(all_users)
            _update_button_styles()
            _apply_filter()

        with ui.row().classes('w-full items-center gap-1 no-wrap').style('margin-bottom: 2px'):
            ui.label('User:').classes('text-caption text-grey-7').style('line-height: 28px; white-space: nowrap')
            ui.button(icon='delete_sweep', on_click=_reset_users).props(
                'flat dense size=sm color=grey-7'
            ).tooltip('Clear all')
            ui.button(icon='select_all', on_click=_select_all_users).props(
                'flat dense size=sm color=grey-7'
            ).tooltip('Show all')
            with ui.element('div').classes('flex flex-wrap gap-0'):
                for u in all_users:
                    btn = ui.button(u, on_click=lambda u=u: _toggle_user(u))
                    btn.props('push color=primary text-color=white no-caps size=sm')
                    user_buttons[u] = btn

        ui.button('Refresh', icon='refresh',
                  on_click=lambda: background_tasks.create(
                      _load_users(ctx))).props('flat dense color=primary').tooltip('Reload user stats')

        tbl = ui.table(
            columns=columns,
            rows=all_rows,
            row_key='user',
            pagination={'rowsPerPage': 20, 'sortBy': 'query_count', 'descending': True},
        ).classes('w-full sticky-table')
        ui.timer(0.3, lambda: ui.run_javascript('window.fitStickyTables()'), once=True)

        tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)
        tbl.add_slot('body', r'''
            <q-tr :props="props" class="cursor-pointer"
                   @click="
                     $event.currentTarget.closest('tbody').querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                     $event.currentTarget.classList.add('table-row-active');
                     $parent.$emit('user-click', props.row)
                   ">
                <q-td key="user" :props="props">
                    <span class="text-weight-bold">{{ props.row.user }}</span>
                </q-td>
                <q-td key="query_count" :props="props">{{ props.row.query_count }}</q-td>
                <q-td key="last_query_time" :props="props">{{ props.row.last_query_time }}</q-td>
                <q-td key="total_duration_sec" :props="props">{{ props.row.total_duration_sec }}</q-td>
                <q-td key="total_read" :props="props">{{ props.row.total_read }}</q-td>
                <q-td key="total_written" :props="props">{{ props.row.total_written }}</q-td>
                <q-td key="peak_memory" :props="props">{{ props.row.peak_memory }}</q-td>
                <q-td key="selects" :props="props">{{ props.row.selects }}</q-td>
                <q-td key="inserts" :props="props">{{ props.row.inserts }}</q-td>
                <q-td key="other_queries" :props="props">{{ props.row.other_queries }}</q-td>
            </q-tr>
        ''')

        def _on_user_click(e):
            row = e.args
            _load_user_detail(ctx, row['user'])

        tbl.on('user-click', _on_user_click)

        tbl.add_slot('pagination', PAGINATION_SLOT)


# ── User Drill-Down ──

def _load_user_detail(ctx: ServerDetailsContext, user_name: str):
    """Open right drawer with user query details."""
    ctx.columns_panel.clear()
    service = state.service
    if not service:
        return

    if ctx.drawer_title:
        ctx.drawer_title.text = 'User queries'
    ctx.right_drawer.set_value(True)

    with ctx.columns_panel:
        ui.spinner('dots', size='lg').classes('self-center q-mt-md')

    # State for filters
    mode = ['all']       # 'all' or 'grouped'
    status = [None]      # None, 'ok', 'error'
    kind = [None]        # None, 'Select', 'Insert', 'Create', 'Other'

    def _rebuild():
        ctx.columns_panel.clear()
        with ctx.columns_panel:
            # Header
            with ui.row().classes('items-center justify-between w-full'):
                ui.label(f'User: {user_name}').classes('text-subtitle1 text-weight-bold')

            # Mode toggle
            with ui.row().classes('items-center gap-1 q-mt-xs'):
                ui.label('Mode:').classes('text-caption text-grey-7')
                mode_all_btn = ui.button('All queries', on_click=lambda: _set_mode('all')).props(
                    'dense no-caps size=sm'
                ).tooltip('Individual queries')
                mode_grp_btn = ui.button('Grouped', on_click=lambda: _set_mode('grouped')).props(
                    'dense no-caps size=sm'
                ).tooltip('Group by query hash')
                if mode[0] == 'all':
                    mode_all_btn.props('push color=primary')
                    mode_grp_btn.props('push color=grey-4 text-color=grey-8')
                else:
                    mode_all_btn.props('push color=grey-4 text-color=grey-8')
                    mode_grp_btn.props('push color=primary')

            # Status filter
            with ui.row().classes('items-center gap-1 q-mt-xs'):
                ui.label('Status:').classes('text-caption text-grey-7')
                for val, label in [(None, 'All'), ('ok', 'OK'), ('error', 'Errors')]:
                    btn = ui.button(label, on_click=lambda v=val: _set_status(v)).props('dense no-caps size=sm')
                    if status[0] == val:
                        btn.props('push color=primary')
                    else:
                        btn.props('push color=grey-4 text-color=grey-8')

            # Kind filter
            with ui.row().classes('items-center gap-1 q-mt-xs'):
                ui.label('Kind:').classes('text-caption text-grey-7')
                for val, label in [(None, 'All'), ('Select', 'SELECT'), ('Insert', 'INSERT'), ('Create', 'CREATE'), ('Other', 'Other')]:
                    btn = ui.button(label, on_click=lambda v=val: _set_kind(v)).props('dense no-caps size=sm')
                    if kind[0] == val:
                        btn.props('push color=primary')
                    else:
                        btn.props('push color=grey-4 text-color=grey-8')

            # Data table
            try:
                if mode[0] == 'all':
                    _render_user_queries_all(service, user_name, status[0], kind[0])
                else:
                    _render_user_queries_grouped(service, user_name, status[0], kind[0])
            except Exception as ex:
                ui.label(f'Error: {ex}').classes('text-negative')

    def _set_mode(m):
        mode[0] = m
        _rebuild()

    def _set_status(s):
        status[0] = s
        _rebuild()

    def _set_kind(k):
        kind[0] = k
        _rebuild()

    _rebuild()


def _render_user_queries_all(service, user_name, status, kind):
    """Render individual queries table in user drill-down."""
    data = service.get_user_queries(
        user=user_name,
        log_days=state.query_log_days,
        status=status,
        kind=kind,
    )

    if not data:
        ui.label('No queries found.').classes('text-grey-7 q-mt-sm')
        return

    rows = []
    for r in data:
        is_error = r['exception_code'] != 0
        query_short = r['query'][:120] + '...' if len(r['query']) > 120 else r['query']
        rows.append({
            'event_time': r['event_time'],
            'query_kind': r['query_kind'],
            'duration_ms': r['query_duration_ms'],
            'status': 'error' if is_error else 'ok',
            'query_short': query_short,
            'query_full': r['query'],
            'exception': r['exception'] or '',
        })

    columns = [
        {'name': 'event_time', 'label': 'Time', 'field': 'event_time', 'align': 'left', 'sortable': True, 'tooltip': 'Execution time'},
        {'name': 'query_kind', 'label': 'Kind', 'field': 'query_kind', 'align': 'center', 'tooltip': 'Query type'},
        {'name': 'duration_ms', 'label': 'Duration (ms)', 'field': 'duration_ms', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Execution duration'},
        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center', 'tooltip': 'Query result'},
        {'name': 'query_short', 'label': 'Query', 'field': 'query_short', 'align': 'left', 'tooltip': 'Query text'},
    ]

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='event_time',
        pagination={'rowsPerPage': 50, 'sortBy': 'event_time', 'descending': True},
    ).classes('w-full q-mt-sm')

    tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)
    tbl.add_slot('body', r'''
        <q-tr :props="props" class="cursor-pointer"
               @click="$parent.$emit('query-click', props.row)">
            <q-td key="event_time" :props="props" style="white-space: nowrap">
                {{ props.row.event_time }}
            </q-td>
            <q-td key="query_kind" :props="props">
                <q-badge :color="
                    props.row.query_kind === 'Select' ? 'blue-4' :
                    props.row.query_kind === 'Insert' ? 'green-4' :
                    props.row.query_kind === 'Create' ? 'purple-4' :
                    'grey-6'
                " :label="props.row.query_kind" />
            </q-td>
            <q-td key="duration_ms" :props="props">{{ props.row.duration_ms }}</q-td>
            <q-td key="status" :props="props">
                <q-icon v-if="props.row.status === 'error'" name="cancel" color="negative" size="xs">
                    <q-tooltip anchor="top middle" self="bottom middle">Query failed</q-tooltip>
                </q-icon>
                <q-icon v-else name="check_circle" color="positive" size="xs">
                    <q-tooltip anchor="top middle" self="bottom middle">Query succeeded</q-tooltip>
                </q-icon>
            </q-td>
            <q-td key="query_short" :props="props" style="max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ props.row.query_short }}
            </q-td>
        </q-tr>
    ''')

    tbl.add_slot('pagination', PAGINATION_SLOT)

    def _on_query_click(e):
        row = e.args
        _show_query_dialog(row['query_full'], row.get('exception', ''))

    tbl.on('query-click', _on_query_click)


def _render_user_queries_grouped(service, user_name, status, kind):
    """Render queries grouped by normalized_query_hash in user drill-down."""
    data = service.get_user_queries_grouped(
        user=user_name,
        log_days=state.query_log_days,
        status=status,
        kind=kind,
    )

    if not data:
        ui.label('No queries found.').classes('text-grey-7 q-mt-sm')
        return

    rows = []
    for r in data:
        query_short = r['sample_query'][:120] + '...' if len(r['sample_query']) > 120 else r['sample_query']
        rows.append({
            'hash': str(r['normalized_query_hash']),
            'sample_query': query_short,
            'sample_query_full': r['sample_query'],
            'query_count': r['query_count'],
            'error_count': r['error_count'],
            'last_time': r['last_time'],
            'total_duration_ms': r['total_duration_ms'],
            'last_exception': r['last_exception'] or '',
        })

    columns = [
        {'name': 'sample_query', 'label': 'Query', 'field': 'sample_query', 'align': 'left', 'tooltip': 'Normalized query'},
        {'name': 'query_count', 'label': 'Count', 'field': 'query_count', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Execution count'},
        {'name': 'error_count', 'label': 'Errors', 'field': 'error_count', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Error count'},
        {'name': 'last_time', 'label': 'Last', 'field': 'last_time', 'align': 'center', 'sortable': True, 'tooltip': 'Last execution'},
        {'name': 'total_duration_ms', 'label': 'Total (ms)', 'field': 'total_duration_ms', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Total duration'},
    ]

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='hash',
        pagination={'rowsPerPage': 50, 'sortBy': 'query_count', 'descending': True},
    ).classes('w-full q-mt-sm')
    tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)

    tbl.add_slot('body', r'''
        <q-tr :props="props" class="cursor-pointer"
               @click="$parent.$emit('group-click', props.row)">
            <q-td key="sample_query" :props="props" style="max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ props.row.sample_query }}
            </q-td>
            <q-td key="query_count" :props="props">{{ props.row.query_count }}</q-td>
            <q-td key="error_count" :props="props">
                <span :class="props.row.error_count > 0 ? 'text-negative text-weight-bold' : 'text-grey-5'">
                    {{ props.row.error_count }}
                </span>
            </q-td>
            <q-td key="last_time" :props="props" style="white-space: nowrap">{{ props.row.last_time }}</q-td>
            <q-td key="total_duration_ms" :props="props">{{ props.row.total_duration_ms }}</q-td>
        </q-tr>
    ''')

    tbl.add_slot('pagination', PAGINATION_SLOT)

    def _on_group_click(e):
        row = e.args
        _show_query_dialog(row['sample_query_full'], row.get('last_exception', ''))

    tbl.on('group-click', _on_group_click)


def _show_query_dialog(query: str, exception: str = ''):
    """Show a dialog with the full query text and optional exception."""
    formatted = format_clickhouse_sql(query)
    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 600px; max-width: 80vw'):
        ui.label('Query').classes('text-h6 q-mb-sm')
        ui.html(
            f'<pre style="white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;">'
            f'{html.escape(formatted)}</pre>'
        )
        if exception:
            ui.label('Exception').classes('text-subtitle2 text-negative q-mt-md q-mb-xs')
            ui.code(exception).classes('w-full text-negative').style('max-height: 150px; overflow: auto')
        with ui.row().classes('w-full justify-end q-mt-md gap-2'):
            copy_js = f'() => window.copyToClipboard({json.dumps(formatted)})'
            ui.button('Copy SQL', icon='content_copy').props('flat').on('click', js_handler=copy_js)
            ui.button('Close', on_click=dlg.close).props('flat')
    dlg.open()
