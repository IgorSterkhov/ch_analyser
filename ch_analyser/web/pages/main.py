"""Single-page layout: Connections drawer | Server Info + Tables + Table Details."""

import html
import json
import re

from nicegui import ui

from ch_analyser.client import CHClient
from ch_analyser.config import ConnectionConfig
from ch_analyser.services import AnalysisService
from ch_analyser.sql_format import format_clickhouse_sql
import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import require_auth, is_admin
from ch_analyser.web.components.header import header
from ch_analyser.web.components.connection_dialog import connection_dialog

# Name of the connection currently in "connecting" state (for UI feedback)
_connecting_name: str | None = None


def _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer):
    """Render the list of connections into conn_container."""
    conn_container.clear()
    connections = state.conn_manager.list_connections()

    with conn_container:
        if not connections:
            ui.label('No connections yet.').classes('text-grey-7')
            return

        admin = is_admin()
        active_name = state.active_connection_name or ''

        for cfg in connections:
            is_active = cfg.name == active_name
            is_connecting = cfg.name == _connecting_name
            bg = 'bg-blue-1' if is_active else ''

            card = ui.card().classes(f'w-full q-pa-xs q-mb-xs cursor-pointer {bg}').props('flat bordered')
            card.on('click', lambda c=cfg: _on_connect(c, conn_container, tables_panel, columns_panel, server_info_bar, drawer))

            with card:
                with ui.row().classes('items-center w-full justify-between no-wrap'):
                    with ui.column().classes('gap-0'):
                        ui.label(cfg.name).classes('text-weight-bold' if is_active else '')
                        ui.label(f'{cfg.host}:{cfg.port}').classes('text-caption text-grey-7')
                        if is_connecting:
                            ui.label('Connecting...').classes('text-caption text-orange')
                        elif is_active:
                            ui.label('Connected').classes('text-caption text-green')

                    if admin:
                        with ui.button(icon='more_vert').props('flat dense size=sm').classes('self-start').on('click', js_handler='(e) => e.stopPropagation()'):
                            with ui.menu():
                                ui.menu_item(
                                    'Edit',
                                    on_click=lambda c=cfg: _on_edit(c, conn_container, tables_panel, columns_panel, server_info_bar, drawer),
                                )
                                ui.menu_item(
                                    'Delete',
                                    on_click=lambda c=cfg: _on_delete(c, conn_container, tables_panel, columns_panel, server_info_bar, drawer),
                                )


def _on_connect(cfg, conn_container, tables_panel, columns_panel, server_info_bar, drawer):
    global _connecting_name

    # Don't reconnect if already connected to this one
    if state.active_connection_name == cfg.name:
        return

    try:
        # Show "Connecting..." state
        _connecting_name = cfg.name
        state.active_connection_name = None
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer)

        if state.client and state.client.connected:
            state.client.disconnect()

        # Inject global CA cert
        cfg.ca_cert = state.conn_manager.ca_cert

        client = CHClient(cfg)
        client.connect()
        state.client = client
        state.service = AnalysisService(client)
        state.active_connection_name = cfg.name
        _connecting_name = None

        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer)
        _build_server_info_bar(server_info_bar)
        _load_tables(tables_panel, columns_panel)
        _clear_columns(columns_panel)

        # Auto-hide connections drawer after successful connect
        drawer.hide()
    except Exception as ex:
        _connecting_name = None
        state.active_connection_name = None
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer)
        _build_server_info_bar(server_info_bar)
        ui.notify(f'Connection failed: {ex}', type='negative')


def _on_edit(cfg, conn_container, tables_panel, columns_panel, server_info_bar, drawer):
    def save(new_cfg, old_name=cfg.name):
        try:
            state.conn_manager.update_connection(old_name, new_cfg)
            ui.notify(f'Updated "{new_cfg.name}"', type='positive')
            _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer)
        except Exception as ex:
            ui.notify(str(ex), type='negative')

    connection_dialog(on_save=save, existing=cfg)


def _on_delete(cfg, conn_container, tables_panel, columns_panel, server_info_bar, drawer):
    try:
        state.conn_manager.delete_connection(cfg.name)
        if state.active_connection_name == cfg.name:
            if state.client and state.client.connected:
                state.client.disconnect()
            state.client = None
            state.service = None
            state.active_connection_name = None
            _clear_tables(tables_panel)
            _clear_columns(columns_panel)
            _build_server_info_bar(server_info_bar)
        ui.notify(f'Deleted "{cfg.name}"', type='positive')
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer)
    except Exception as ex:
        ui.notify(str(ex), type='negative')


def _show_refs_dialog(title: str, refs_list: list[str]):
    """Show a dialog with a list of referencing entities and a Copy button."""
    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 400px'):
        ui.label(f'References: {title}').classes('text-h6 q-mb-sm')
        text = '\n'.join(refs_list)
        for ref in refs_list:
            ui.label(ref).classes('text-body2')
        with ui.row().classes('w-full justify-end q-mt-md gap-2'):
            ui.button('Copy', icon='content_copy',
                      on_click=lambda: ui.run_javascript(
                          f'navigator.clipboard.writeText({json.dumps(text)})'
                      )).props('flat')
            ui.button('Close', on_click=dlg.close).props('flat')
    dlg.open()


def _load_tables(tables_panel, columns_panel):
    """Fetch and render tables into the center panel."""
    tables_panel.clear()
    service = state.service
    if not service:
        with tables_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    try:
        data = service.get_tables()
    except Exception as ex:
        with tables_panel:
            ui.notify(f'Failed to load tables: {ex}', type='negative')
        return

    # Get references for all tables
    try:
        refs = service.get_table_references()
    except Exception:
        refs = {}

    with tables_panel:
        if not data:
            ui.label('No tables found.').classes('text-grey-7')
            return

        columns = [
            {'name': 'name', 'label': 'Table', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
            {'name': 'replicated', 'label': 'R', 'field': 'replicated', 'align': 'center'},
            {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True},
            {'name': 'ttl', 'label': 'TTL', 'field': 'ttl', 'align': 'left'},
            {'name': 'last_select', 'label': 'Last SELECT', 'field': 'last_select', 'align': 'center'},
            {'name': 'last_insert', 'label': 'Last INSERT', 'field': 'last_insert', 'align': 'center'},
        ]
        rows = [
            {
                'name': t['name'],
                'size': t['size'],
                'size_bytes': t['size_bytes'],
                'replicated': t.get('replicated', False),
                'refs_cnt': len(refs.get(t['name'], [])),
                'refs_list': refs.get(t['name'], []),
                'ttl': t.get('ttl', ''),
                'last_select': t['last_select'],
                'last_insert': t['last_insert'],
            }
            for t in data
        ]

        tbl = ui.table(
            columns=columns,
            rows=rows,
            row_key='name',
            pagination={'rowsPerPage': 20, 'sortBy': 'size', 'descending': True},
        ).classes('w-full')

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
                <q-td key="replicated" :props="props">
                    <q-icon v-if="props.row.replicated" name="sync" color="primary" size="xs" />
                </q-td>
                <q-td key="refs" :props="props">
                    <q-btn v-if="props.row.refs_cnt > 0" flat dense size="sm"
                           :label="String(props.row.refs_cnt)" color="primary"
                           @click.stop="$parent.$emit('show-refs', props.row)" />
                    <span v-else class="text-grey-5">0</span>
                </q-td>
                <q-td key="ttl" :props="props">{{ props.row.ttl || '-' }}</q-td>
                <q-td key="last_select" :props="props">{{ props.row.last_select }}</q-td>
                <q-td key="last_insert" :props="props">{{ props.row.last_insert }}</q-td>
            </q-tr>
            ''',
        )

        tbl.add_slot(
            'pagination',
            r'''
            <span class="q-mr-sm">Rows per page:</span>
            <q-select
                v-model="props.pagination.rowsPerPage"
                :options="[20, 50, 100, 200, 0]"
                :option-label="opt => opt === 0 ? 'All' : opt"
                dense borderless
                style="min-width: 80px"
                @update:model-value="val => props.pagination.rowsPerPage = val"
            />
            <q-space />
            <span v-if="props.pagination.rowsPerPage > 0" class="q-mx-sm">
                {{ ((props.pagination.page - 1) * props.pagination.rowsPerPage) + 1 }}-{{ Math.min(props.pagination.page * props.pagination.rowsPerPage, props.pagination.rowsNumber) }}
                of {{ props.pagination.rowsNumber }}
            </span>
            <span v-else class="q-mx-sm">{{ props.pagination.rowsNumber }} total</span>
            <q-btn v-if="props.pagination.rowsPerPage > 0"
                icon="chevron_left" dense flat
                :disable="props.pagination.page <= 1"
                @click="props.pagination.page--" />
            <q-btn v-if="props.pagination.rowsPerPage > 0"
                icon="chevron_right" dense flat
                :disable="props.pagination.page >= Math.ceil(props.pagination.rowsNumber / props.pagination.rowsPerPage)"
                @click="props.pagination.page++" />
            ''',
        )

        def on_row_click(e):
            row = e.args
            _load_columns(columns_panel, row['name'])

        tbl.on('row-click', on_row_click)

        def on_show_refs(e):
            row = e.args
            _show_refs_dialog(row['name'], row.get('refs_list', []))

        tbl.on('show-refs', on_show_refs)

        # --- Show generated SQL button ---
        def _show_tables_sql():
            raw_sql = service.get_tables_sql()
            formatted = format_clickhouse_sql(raw_sql)
            escaped = html.escape(formatted)
            with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
                ui.label('Generated Queries (Tables)').classes('text-h6 q-mb-sm')
                ui.html(f'<pre style="white-space:pre-wrap;word-break:break-all;max-height:60vh;overflow:auto">{escaped}</pre>')
                with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                    ui.button('Copy', icon='content_copy',
                              on_click=lambda: ui.run_javascript(
                                  f'navigator.clipboard.writeText({json.dumps(formatted)})'
                              )).props('flat')
                    ui.button('Close', on_click=dlg.close).props('flat')
            dlg.open()

        with ui.row().classes('q-mt-sm gap-2'):
            ui.button('Refresh', icon='refresh', on_click=lambda: _load_tables(tables_panel, columns_panel)).props(
                'flat dense color=primary'
            )
            ui.button(icon='code', on_click=_show_tables_sql).props(
                'flat dense color=primary'
            ).tooltip('Show generated SQL')


def _load_columns(columns_panel, full_table_name: str):
    """Fetch and render columns + query history tabs into the right panel."""
    columns_panel.clear()
    service = state.service
    if not service:
        return

    with columns_panel:
        ui.label(full_table_name).classes('text-subtitle1 text-weight-bold q-mb-sm')

        with ui.tabs().classes('w-full') as tabs:
            columns_tab = ui.tab('Columns')
            history_tab = ui.tab('Query History')

        with ui.tab_panels(tabs, value=columns_tab).classes('w-full'):
            with ui.tab_panel(columns_tab):
                _render_columns_tab(service, full_table_name)
            with ui.tab_panel(history_tab):
                _render_query_history_tab(service, full_table_name)


def _render_columns_tab(service, full_table_name: str):
    """Render the columns table inside a tab panel."""
    try:
        data = service.get_columns(full_table_name)
    except Exception as ex:
        ui.notify(f'Failed to load columns: {ex}', type='negative')
        return

    if not data:
        ui.label('No columns found.').classes('text-grey-7')
        return

    # Get column-level references
    try:
        col_refs = service.get_column_references(full_table_name)
    except Exception:
        col_refs = {}

    columns = [
        {'name': 'name', 'label': 'Column', 'field': 'name', 'align': 'left', 'sortable': True},
        {'name': 'type', 'label': 'Type', 'field': 'type', 'align': 'left', 'sortable': True},
        {'name': 'codec', 'label': 'Codec', 'field': 'codec', 'align': 'left'},
        {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
        {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True},
    ]
    rows = [
        {
            'name': c['name'],
            'type': c['type'],
            'codec': c.get('codec', ''),
            'size': c.get('size', '0 B'),
            'size_bytes': c.get('size_bytes', 0),
            'refs_cnt': len(col_refs.get(c['name'], [])),
            'refs_list': col_refs.get(c['name'], []),
        }
        for c in data
    ]

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
            <q-td key="refs" :props="props">
                <q-btn v-if="props.row.refs_cnt > 0" flat dense size="sm"
                       :label="String(props.row.refs_cnt)" color="primary"
                       @click.stop="$parent.$emit('show-refs', props.row)" />
                <span v-else class="text-grey-5">0</span>
            </q-td>
        </q-tr>
        ''',
    )

    def on_show_col_refs(e):
        row = e.args
        _show_refs_dialog(row['name'], row.get('refs_list', []))

    tbl.on('show-refs', on_show_col_refs)


def _render_query_history_tab(service, full_table_name: str):
    """Render query history table inside a tab panel."""
    try:
        data = service.get_query_history(full_table_name)
    except Exception as ex:
        ui.notify(f'Failed to load query history: {ex}', type='negative')
        return

    if not data:
        ui.label('No query history found.').classes('text-grey-7')
        return

    # Search/filter input
    filter_input = ui.input(placeholder='Filter...').props('dense clearable').classes('q-mb-sm w-full')

    # --- Toggle filters ---
    unique_users = sorted(set(r['user'] for r in data))
    unique_kinds = sorted(set(r['query_kind'] for r in data))

    active_users = set(unique_users)
    active_kinds = set(unique_kinds)

    all_rows = [
        {
            'event_time': r['event_time'],
            'user': r['user'],
            'query_kind': r['query_kind'],
            'query_short': r['query'][:50] + ('...' if len(r['query']) > 50 else ''),
            'query_full': r['query'],
        }
        for r in data
    ]

    user_buttons: dict[str, ui.button] = {}
    kind_buttons: dict[str, ui.button] = {}

    # Will be set after table creation
    tbl_ref: list[ui.table] = []

    def _update_buttons_and_table():
        """Recalculate dependent filters and update table from cached data."""
        available_kinds = set(r['query_kind'] for r in all_rows if r['user'] in active_users)
        available_users = set(r['user'] for r in all_rows if r['query_kind'] in active_kinds)

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

        effective_users = active_users & available_users
        effective_kinds = active_kinds & available_kinds
        tbl_ref[0].rows = [
            r for r in all_rows
            if r['user'] in effective_users and r['query_kind'] in effective_kinds
        ]
        tbl_ref[0].update()

    def toggle_user(user):
        if user in active_users:
            active_users.discard(user)
        else:
            active_users.add(user)
        _update_buttons_and_table()

    def toggle_kind(kind):
        if kind in active_kinds:
            active_kinds.discard(kind)
        else:
            active_kinds.add(kind)
        _update_buttons_and_table()

    with ui.row().classes('w-full items-center gap-4 q-mb-sm'):
        ui.label('User:').classes('text-caption text-grey-7')
        with ui.element('q-btn-group').props('push'):
            for u in unique_users:
                btn = ui.button(u, on_click=lambda u=u: toggle_user(u))
                btn.props('push color=primary text-color=white no-caps')
                user_buttons[u] = btn

        ui.label('Kind:').classes('text-caption text-grey-7')
        with ui.element('q-btn-group').props('push'):
            for k in unique_kinds:
                btn = ui.button(k, on_click=lambda k=k: toggle_kind(k))
                btn.props('push color=primary text-color=white no-caps')
                kind_buttons[k] = btn

    # --- Show generated query button ---
    def _show_generated_query():
        raw_sql = service.get_query_history_sql(
            full_table_name,
            users=sorted(active_users) if len(active_users) < len(unique_users) else None,
            kinds=sorted(active_kinds) if len(active_kinds) < len(unique_kinds) else None,
        )
        formatted = format_clickhouse_sql(raw_sql)
        escaped = html.escape(formatted)
        with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
            ui.label('Generated Query').classes('text-h6 q-mb-sm')
            ui.html(f'<pre style="white-space:pre-wrap;word-break:break-all;max-height:60vh;overflow:auto">{escaped}</pre>')
            with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                ui.button('Copy', icon='content_copy',
                          on_click=lambda: ui.run_javascript(
                              f'navigator.clipboard.writeText({json.dumps(formatted)})'
                          )).props('flat')
                ui.button('Close', on_click=dlg.close).props('flat')
        dlg.open()

    ui.button(icon='code', on_click=_show_generated_query).props(
        'flat dense color=primary'
    ).tooltip('Show generated SQL')

    # --- Table ---
    columns = [
        {'name': 'event_time', 'label': 'Time', 'field': 'event_time', 'align': 'left', 'sortable': True},
        {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True},
        {'name': 'query_kind', 'label': 'Kind', 'field': 'query_kind', 'align': 'center', 'sortable': True},
        {'name': 'query', 'label': 'Query', 'field': 'query_short', 'align': 'left'},
    ]

    tbl = ui.table(
        columns=columns,
        rows=list(all_rows),
        row_key='event_time',
        pagination={'rowsPerPage': 20, 'sortBy': 'event_time', 'descending': True},
    ).classes('w-full')
    tbl_ref.append(tbl)

    # Bind filter input to table's built-in filter
    tbl.bind_filter_from(filter_input, 'value')

    tbl.add_slot(
        'body',
        r'''
        <q-tr :props="props">
            <q-td key="event_time" :props="props">{{ props.row.event_time }}</q-td>
            <q-td key="user" :props="props">{{ props.row.user }}</q-td>
            <q-td key="query_kind" :props="props">{{ props.row.query_kind }}</q-td>
            <q-td key="query" :props="props">
                <q-btn flat dense size="sm" icon="visibility" color="primary"
                       @click.stop="$parent.$emit('show-query', props.row)"
                       class="q-mr-xs" />
                {{ props.row.query_short }}
            </q-td>
        </q-tr>
        ''',
    )

    def _highlight_table(sql_text, table_name):
        """Highlight table name occurrences in already-escaped HTML."""
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
                ui.button('Close', on_click=dlg.close).props('flat')
        dlg.open()

    tbl.on('show-query', on_show_query)


def _clear_tables(tables_panel):
    tables_panel.clear()
    with tables_panel:
        ui.label('Select a connection.').classes('text-grey-7')


def _clear_columns(columns_panel):
    columns_panel.clear()
    with columns_panel:
        ui.label('Select a table.').classes('text-grey-7')


def _build_server_info_bar(bar_container):
    """Render server disk info into the bar container (a ui.card)."""
    bar_container.clear()
    service = state.service
    if not service or not state.active_connection_name:
        bar_container.set_visibility(False)
        return

    try:
        disks = service.get_disk_info()
    except Exception as ex:
        bar_container.set_visibility(False)
        ui.notify(f'Disk info error: {ex}', type='warning')
        return

    if not disks:
        bar_container.set_visibility(False)
        return

    bar_container.set_visibility(True)
    with bar_container:
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
                    value=pct / 100.0,
                    color=color,
                ).props('rounded track-color=grey-3').style('max-width: 200px; height: 8px')
                ui.label(f'{pct}%').classes(f'text-weight-bold text-{color}')


@ui.page('/')
def main_page():
    if not require_auth():
        return

    # CSS for selected table row highlight, drawer toggle button, and scroll fix
    ui.add_css('''
        .q-table__middle {
            max-height: none !important;
        }
        .table-row-active {
            background-color: #1976d2 !important;
        }
        .table-row-active td {
            color: white !important;
        }
        .drawer-toggle-btn {
            position: fixed !important;
            left: 300px;
            top: 50% !important;
            transform: translateY(-50%) !important;
            width: 24px !important;
            min-width: 24px !important;
            height: 80px !important;
            padding: 0 !important;
            border-radius: 0 8px 8px 0 !important;
            z-index: 1000 !important;
            transition: left 0.3s ease !important;
        }
        .drawer-toggle-btn.drawer-closed {
            left: 0 !important;
        }
        .drawer-toggle-btn .q-icon {
            transition: transform 0.3s ease;
        }
        .drawer-toggle-btn.drawer-closed .q-icon {
            transform: rotate(180deg);
        }
    ''')

    # Collapsible connections drawer
    with ui.left_drawer(elevated=True, value=True).classes('q-pa-sm') as drawer:
        with ui.row().classes('items-center justify-between w-full q-mb-sm'):
            ui.label('Connections').classes('text-h6')

        conn_container = ui.column().classes('w-full gap-1')

        # Placeholder — will be set after main panels are created
        tables_panel = None
        columns_panel = None
        server_info_bar = None

        # Add button for admin — placed outside conn_container so it survives rebuilds
        add_btn_container = ui.column().classes('w-full')

    # Sync toggle button state whenever drawer opens/closes
    def _on_drawer_change(e):
        if e.value:
            ui.run_javascript("document.querySelector('.drawer-toggle-btn')?.classList.remove('drawer-closed')")
        else:
            ui.run_javascript("document.querySelector('.drawer-toggle-btn')?.classList.add('drawer-closed')")

    drawer.on_value_change(_on_drawer_change)

    header(drawer=drawer)

    # Toggle button — OUTSIDE drawer, fixed-position, always visible
    ui.button(icon='chevron_left', on_click=lambda: drawer.set_value(not drawer.value)).props(
        'color=primary dense unelevated'
    ).classes('drawer-toggle-btn')

    # Main content area
    main_content = ui.column().classes('w-full q-pa-sm gap-2').style('height: calc(100vh - 64px)')

    with main_content:
        # Server info bar
        server_info_bar = ui.card().classes('q-pa-sm w-full').props('flat bordered')
        server_info_bar.set_visibility(False)

        # Tables + Table Details row
        with ui.row().classes('w-full flex-nowrap gap-2 flex-grow overflow-hidden'):
            # CENTER: Tables
            with ui.card().classes('q-pa-sm overflow-auto').style('width: 45%; max-height: calc(100vh - 150px)'):
                ui.label('Tables').classes('text-h6 q-mb-sm')
                tables_panel = ui.column().classes('w-full')
                with tables_panel:
                    ui.label('Select a connection.').classes('text-grey-7')

            # RIGHT: Table Details
            with ui.card().classes('q-pa-sm overflow-auto flex-grow').style('max-height: calc(100vh - 150px)'):
                ui.label('Table Details').classes('text-h6 q-mb-sm')
                columns_panel = ui.column().classes('w-full')
                with columns_panel:
                    ui.label('Select a table.').classes('text-grey-7')

    # Auto-hide drawer when clicking on main content
    main_content.on('click', lambda: drawer.hide() if drawer.value else None)

    # Build connections list
    _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer)

    # Add button — outside conn_container, won't be cleared on rebuild
    if is_admin():
        def open_add_dialog():
            def save(cfg):
                try:
                    state.conn_manager.add_connection(cfg)
                    ui.notify(f'Added "{cfg.name}"', type='positive')
                    _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer)
                except Exception as ex:
                    ui.notify(str(ex), type='negative')
            connection_dialog(on_save=save)

        with add_btn_container:
            ui.button('Add', icon='add', on_click=open_add_dialog).props(
                'color=primary dense'
            ).classes('q-mt-sm w-full')

    # If already connected, show tables and server info
    if state.service:
        _build_server_info_bar(server_info_bar)
        _load_tables(tables_panel, columns_panel)
