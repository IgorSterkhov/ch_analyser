"""Server Details view — tables, columns, query history, flow, text logs, users.

Extracted from main.py. All UI functions accept a ServerDetailsContext dataclass
instead of many individual panel references.
"""

import html
import json
import re
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
    PAGINATION_SLOT,
)


@dataclass
class ServerDetailsContext:
    tables_panel: ui.column = None
    columns_panel: ui.column = None
    server_info_bar: ui.card = None
    right_drawer: object = None
    text_logs_panel: ui.column = None
    users_panel: ui.column = None
    main_tabs_loaded: set = field(default_factory=set)
    connection_select: ui.select = None


# ── Module-level state for connection flow ──
_connecting_name: str | None = None
_suppress_right_drawer_hide: bool = False


def build_server_details_view(parent, right_drawer, columns_panel) -> ServerDetailsContext:
    """Build the 'by Server Details' view inside parent container.

    Returns a ServerDetailsContext with all panel references.
    """
    ctx = ServerDetailsContext()
    ctx.right_drawer = right_drawer
    ctx.columns_panel = columns_panel

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
            ).props('dense outlined').classes('q-ml-xs').style('min-width: 250px')

        # Server info bar
        ctx.server_info_bar = ui.card().classes('q-pa-sm w-full').props('flat bordered')
        ctx.server_info_bar.set_visibility(False)

        # Main-level tabs
        with ui.tabs().classes('w-full').props('dense') as main_tabs:
            tables_main_tab = ui.tab('Tables', icon='table_chart')
            users_main_tab = ui.tab('Users', icon='people')
            text_logs_main_tab = ui.tab('Text Logs', icon='article')

        with ui.tab_panels(main_tabs, value=tables_main_tab).classes(
            'w-full q-pt-none flex-grow'
        ).style('max-height: calc(100vh - 200px); overflow: auto'):
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

        _active_main_tab = ['Tables']

        def _on_main_tab_change(e):
            tab = e.value
            _active_main_tab[0] = tab
            if tab != 'Tables':
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
                _load_users(ctx)
            if tab == 'Text Logs' and 'Text Logs' not in ctx.main_tabs_loaded and state.service:
                ctx.main_tabs_loaded.add('Text Logs')
                _load_text_logs(ctx)

        main_tabs.on_value_change(_on_main_tab_change)

    # If already connected, show data
    if state.service:
        _build_server_info_bar(ctx)
        _load_tables(ctx)

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

        if ctx.text_logs_panel:
            ctx.text_logs_panel.clear()
            with ctx.text_logs_panel:
                ui.label('Switch to Text Logs tab to load.').classes('text-grey-7')
        if ctx.users_panel:
            ctx.users_panel.clear()
            with ctx.users_panel:
                ui.label('Switch to Users tab to load.').classes('text-grey-7')

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
                    _load_tables(c)

                ui.select(
                    options={7: '7d', 30: '30d', 90: '90d', 365: '1y'},
                    value=state.query_log_days,
                    on_change=_on_days_change,
                ).props('dense outlined').classes('q-ml-none').style('min-width: 70px')


# ── Tables ──

def _load_tables(ctx: ServerDetailsContext):
    ctx.tables_panel.clear()
    service = state.service
    if not service:
        with ctx.tables_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    try:
        data = service.get_tables(log_days=state.query_log_days)
    except Exception as ex:
        with ctx.tables_panel:
            ui.notify(f'Failed to load tables: {ex}', type='negative')
        return

    try:
        refs = service.get_table_references()
    except Exception:
        refs = {}

    try:
        disks = service.get_disk_info()
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
            {'name': 'name', 'label': 'Table', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
            {'name': 'size_pct', 'label': '%', 'field': 'size_pct', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
            {'name': 'replicated', 'label': 'R', 'field': 'replicated', 'align': 'center'},
            {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True},
            {'name': 'dist', 'label': '_d', 'field': 'dist_cnt', 'align': 'center', 'sortable': True},
            {'name': 'last_select', 'label': 'Last SELECT', 'field': 'last_select', 'align': 'center'},
            {'name': 'last_insert', 'label': 'Last INSERT', 'field': 'last_insert', 'align': 'center'},
            {'name': 'ttl', 'label': 'TTL', 'field': 'ttl', 'align': 'left'},
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

        filter_input = ui.input(placeholder='Filter by table name...').props(
            'dense clearable'
        ).classes('q-mb-sm').style('max-width: 400px')

        tbl = ui.table(
            columns=columns,
            rows=rows,
            row_key='name',
            pagination={'rowsPerPage': 20, 'sortBy': 'size', 'descending': True},
        ).classes('w-full')
        tbl.bind_filter_from(filter_input, 'value')

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
                    <q-icon v-if="props.row.replicated" name="sync" color="primary" size="xs" />
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

        def on_row_click(e):
            global _suppress_right_drawer_hide
            _suppress_right_drawer_hide = True
            row = e.args
            table_name = row['name']
            if table_name == _current_detail_table[0] and ctx.right_drawer.value:
                ctx.right_drawer.hide()
                _current_detail_table[0] = None
            else:
                _current_detail_table[0] = table_name
                _load_columns(ctx, table_name)

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

        with ui.row().classes('q-mt-sm gap-2'):
            ui.button('Refresh', icon='refresh', on_click=lambda: _load_tables(ctx)).props(
                'flat dense color=primary'
            )
            ui.button(icon='code', on_click=_show_tables_sql).props(
                'flat dense color=primary'
            ).tooltip('Show generated SQL')


# ── Columns (right drawer) ──

def _load_columns(ctx: ServerDetailsContext, full_table_name: str):
    ctx.columns_panel.clear()
    service = state.service
    if not service:
        return

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

    with ctx.columns_panel:
        ui.label(full_table_name).classes(
            'text-subtitle1 text-weight-bold text-center w-full q-pa-xs'
        ).style('border: 1px solid #9e9e9e; border-radius: 4px')

        with ui.tabs().classes('w-full').props('dense') as tabs:
            columns_tab = ui.tab('Columns')
            history_tab = ui.tab('Query History')
            flow_tab = ui.tab('Flow')

        loaded_tabs = set()

        try:
            disks = service.get_disk_info()
            total_disk_bytes = sum(d['used_bytes'] for d in disks) if disks else 0
        except Exception:
            total_disk_bytes = 0

        with ui.tab_panels(tabs, value=columns_tab).classes('w-full q-pt-none') as tab_panels:
            with ui.tab_panel(columns_tab).classes('q-pa-xs'):
                _render_columns_tab(service, full_table_name, total_disk_bytes)
                loaded_tabs.add('Columns')
            with ui.tab_panel(history_tab).classes('q-pa-xs') as history_panel:
                pass
            with ui.tab_panel(flow_tab).classes('q-pa-xs') as flow_panel:
                pass

        def _on_tab_change(e):
            name = e.value
            if name in loaded_tabs:
                return
            loaded_tabs.add(name)
            if name == 'Query History':
                with history_panel:
                    _render_query_history_tab(service, full_table_name)
            elif name == 'Flow':
                with flow_panel:
                    _render_flow_tab(service, full_table_name)

        tabs.on_value_change(_on_tab_change)


def _clear_columns(ctx: ServerDetailsContext):
    ctx.columns_panel.clear()
    if ctx.right_drawer:
        ctx.right_drawer.hide()
    with ctx.columns_panel:
        ui.label('Select a table.').classes('text-grey-7')


def _render_columns_tab(service, full_table_name: str, total_disk_bytes: int = 0):
    try:
        data = service.get_columns(full_table_name)
    except Exception as ex:
        ui.notify(f'Failed to load columns: {ex}', type='negative')
        return

    if not data:
        ui.label('No columns found.').classes('text-grey-7')
        return

    try:
        col_refs = service.get_column_references(full_table_name)
    except Exception:
        col_refs = {}

    table_total_bytes = sum(c.get('size_bytes', 0) for c in data)

    columns = [
        {'name': 'name', 'label': 'Column', 'field': 'name', 'align': 'left', 'sortable': True},
        {'name': 'type', 'label': 'Type', 'field': 'type', 'align': 'left', 'sortable': True},
        {'name': 'codec', 'label': 'Codec', 'field': 'codec', 'align': 'left'},
        {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
        {'name': 'size_pct', 'label': '%', 'field': 'size_pct', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
        {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True},
        {'name': 'dist', 'label': '_d', 'field': 'dist_cnt', 'align': 'center', 'sortable': True},
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


# ── Query History ──

def _render_query_history_tab(service, full_table_name: str):
    try:
        filters = service.get_query_history_filters(full_table_name, log_days=state.query_log_days)
    except Exception as ex:
        ui.notify(f'Failed to load query history filters: {ex}', type='negative')
        return

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
                {'name': 'event_time', 'label': 'Time', 'field': 'event_time', 'align': 'left', 'sortable': True},
                {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True},
                {'name': 'query_kind', 'label': 'Kind', 'field': 'query_kind', 'align': 'center', 'sortable': True},
                {'name': 'query', 'label': 'Query', 'field': 'query_short', 'align': 'left'},
            ]
            if not direct_only[0]:
                columns.insert(3, {'name': 'direct', 'label': 'Direct', 'field': 'direct', 'align': 'center', 'sortable': True})

            body_slot = r'''
                <q-tr :props="props">
                    <q-td key="event_time" :props="props">{{ props.row.event_time }}</q-td>
                    <q-td key="user" :props="props">{{ props.row.user }}</q-td>
                    <q-td key="query_kind" :props="props">{{ props.row.query_kind }}</q-td>'''
            if not direct_only[0]:
                body_slot += r'''
                    <q-td key="direct" :props="props">{{ props.row.direct }}</q-td>'''
            body_slot += r'''
                    <q-td key="query" :props="props">
                        <q-btn flat dense size="sm" icon="visibility" color="primary"
                               @click.stop="$parent.$emit('show-query', props.row)"
                               class="q-mr-xs" />
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

    def reset_kinds():
        active_kinds.clear()
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
        ).props('dense borderless').style('min-width: 80px')

        ui.switch('Direct', value=True,
                  on_change=lambda e: (direct_only.__setitem__(0, e.value), _reload_filters_and_refresh()),
                  ).tooltip('Show only queries that directly mention the table name')

        ui.button(icon='code', on_click=_show_generated_query).props(
            'flat dense color=primary'
        ).tooltip('Show generated SQL')

        ui.button('Refresh', icon='refresh', on_click=_refresh).props('flat dense color=primary')

    table_container = ui.column().classes('w-full')
    _refresh()


# ── Flow ──

def _render_flow_tab(service, full_table_name: str):
    with ui.tabs().classes('w-full').props('dense') as sub_tabs:
        mv_tab = ui.tab('MV Flow')
        query_tab = ui.tab('Query Flow')
        full_tab = ui.tab('Full Flow')

    with ui.tab_panels(sub_tabs, value=mv_tab).classes('w-full'):
        with ui.tab_panel(mv_tab):
            try:
                flow = service.get_mv_flow(full_table_name)
            except Exception as ex:
                ui.notify(f'Failed to load MV flow: {ex}', type='negative')
                flow = {'nodes': [], 'edges': []}

            mermaid_text = flow_to_mermaid(flow, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No materialized view flow found.').classes('text-grey-7')

        with ui.tab_panel(query_tab):
            try:
                flow = service.get_query_flow(full_table_name, log_days=state.query_log_days)
            except Exception as ex:
                ui.notify(f'Failed to load query flow: {ex}', type='negative')
                flow = {'nodes': [], 'edges': []}

            mermaid_text = flow_to_mermaid(flow, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No query-based data flow found.').classes('text-grey-7')

        with ui.tab_panel(full_tab):
            try:
                mv_flow = service.get_mv_flow(full_table_name)
                query_flow = service.get_query_flow(full_table_name, log_days=state.query_log_days)
            except Exception as ex:
                ui.notify(f'Failed to load flow: {ex}', type='negative')
                mv_flow = {'nodes': [], 'edges': []}
                query_flow = {'nodes': [], 'edges': []}

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

def _load_text_logs(ctx: ServerDetailsContext):
    ctx.text_logs_panel.clear()
    service = state.service
    if not service:
        with ctx.text_logs_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    try:
        data = service.get_text_log_summary()
    except Exception as ex:
        with ctx.text_logs_panel:
            ui.label(f'Failed to load text logs: {ex}').classes('text-negative')
        return

    with ctx.text_logs_panel:
        if not data:
            ui.label('No text log entries found (level <= Warning, last 2 weeks).').classes('text-grey-7')
            return

        with ui.splitter(value=100).classes('w-full').style(
            'height: calc(100vh - 220px)'
        ) as splitter:
            with splitter.before:
                ui.button('Refresh', icon='refresh',
                          on_click=lambda: _load_text_logs(ctx)).props('flat dense color=primary')

                columns = [
                    {'name': 'thread_name', 'label': 'Thread', 'field': 'thread_name', 'align': 'left', 'sortable': True},
                    {'name': 'level_name', 'label': 'Level', 'field': 'level_name', 'align': 'center', 'sortable': True},
                    {'name': 'max_time', 'label': 'Last Seen', 'field': 'max_time', 'align': 'center', 'sortable': True},
                    {'name': 'cnt', 'label': 'Count', 'field': 'cnt', 'align': 'right', 'sortable': True,
                     ':sort': '(a, b) => a - b'},
                    {'name': 'message_example', 'label': 'Message Example', 'field': 'message_example', 'align': 'left'},
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
                ).classes('w-full')

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
                    ui.button(icon='close', on_click=lambda: splitter.set_value(100)).props('flat dense size=sm')
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
        ).classes('w-full')

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
                               class="q-mr-xs" />
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

def _load_users(ctx: ServerDetailsContext):
    ctx.users_panel.clear()
    service = state.service
    if not service:
        with ctx.users_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    try:
        data = service.get_user_stats(log_days=state.query_log_days)
    except Exception as ex:
        with ctx.users_panel:
            ui.label(f'Failed to load user stats: {ex}').classes('text-negative')
        return

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
                'total_read_rows': r['total_read_rows'],
                'total_written': r['total_written'],
                'total_written_rows': r['total_written_rows'],
                'peak_memory': r['peak_memory'],
                'selects': r['selects'],
                'inserts': r['inserts'],
                'other_queries': r['other_queries'],
            }
            for r in data
        ]

        columns = [
            {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True},
            {'name': 'query_count', 'label': 'Queries', 'field': 'query_count', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b'},
            {'name': 'last_query_time', 'label': 'Last Query', 'field': 'last_query_time', 'align': 'center', 'sortable': True},
            {'name': 'total_duration_sec', 'label': 'Total Time (s)', 'field': 'total_duration_sec', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b'},
            {'name': 'total_read', 'label': 'Read', 'field': 'total_read', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.total_read_rows - rowB.total_read_rows'},
            {'name': 'total_written', 'label': 'Written', 'field': 'total_written', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.total_written_rows - rowB.total_written_rows'},
            {'name': 'peak_memory', 'label': 'Peak Mem', 'field': 'peak_memory', 'align': 'right'},
            {'name': 'selects', 'label': 'SELECTs', 'field': 'selects', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b'},
            {'name': 'inserts', 'label': 'INSERTs', 'field': 'inserts', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b'},
            {'name': 'other_queries', 'label': 'Other', 'field': 'other_queries', 'align': 'right', 'sortable': True,
             ':sort': '(a, b) => a - b'},
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
            active_users.update(all_users)
            _update_button_styles()
            _apply_filter()

        with ui.row().classes('w-full items-center gap-1 no-wrap').style('margin-bottom: 2px'):
            ui.label('User:').classes('text-caption text-grey-7').style('line-height: 28px; white-space: nowrap')
            ui.button(icon='delete_sweep', on_click=_reset_users).props(
                'flat dense size=sm color=grey-7'
            ).tooltip('Show all')
            with ui.element('div').classes('flex flex-wrap gap-0'):
                for u in all_users:
                    btn = ui.button(u, on_click=lambda u=u: _toggle_user(u))
                    btn.props('push color=primary text-color=white no-caps size=sm')
                    user_buttons[u] = btn

        ui.button('Refresh', icon='refresh',
                  on_click=lambda: _load_users(ctx)).props('flat dense color=primary')

        tbl = ui.table(
            columns=columns,
            rows=all_rows,
            row_key='user',
            pagination={'rowsPerPage': 20, 'sortBy': 'query_count', 'descending': True},
        ).classes('w-full')

        tbl.add_slot('pagination', PAGINATION_SLOT)
