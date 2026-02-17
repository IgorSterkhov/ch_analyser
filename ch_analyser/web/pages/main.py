"""Single-page layout: Connections | Server Info + Tables + Table Details."""

from nicegui import ui

from ch_analyser.client import CHClient
from ch_analyser.config import ConnectionConfig
from ch_analyser.services import AnalysisService
import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import require_auth, is_admin
from ch_analyser.web.components.header import header
from ch_analyser.web.components.connection_dialog import connection_dialog

# Name of the connection currently in "connecting" state (for UI feedback)
_connecting_name: str | None = None


def _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar):
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
            card.on('click', lambda c=cfg: _on_connect(c, conn_container, tables_panel, columns_panel, server_info_bar))

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
                        with ui.button(icon='more_vert').props('flat dense size=sm').classes('self-start'):
                            with ui.menu():
                                ui.menu_item(
                                    'Edit',
                                    on_click=lambda c=cfg: _on_edit(c, conn_container, tables_panel, columns_panel, server_info_bar),
                                )
                                ui.menu_item(
                                    'Delete',
                                    on_click=lambda c=cfg: _on_delete(c, conn_container, tables_panel, columns_panel, server_info_bar),
                                )


def _on_connect(cfg, conn_container, tables_panel, columns_panel, server_info_bar):
    global _connecting_name

    # Don't reconnect if already connected to this one
    if state.active_connection_name == cfg.name:
        return

    try:
        # Show "Connecting..." state
        _connecting_name = cfg.name
        state.active_connection_name = None
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar)

        if state.client and state.client.connected:
            state.client.disconnect()

        client = CHClient(cfg)
        client.connect()
        state.client = client
        state.service = AnalysisService(client)
        state.active_connection_name = cfg.name
        _connecting_name = None

        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar)
        _build_server_info_bar(server_info_bar)
        _load_tables(tables_panel, columns_panel)
        _clear_columns(columns_panel)
    except Exception as ex:
        _connecting_name = None
        state.active_connection_name = None
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar)
        _build_server_info_bar(server_info_bar)
        ui.notify(f'Connection failed: {ex}', type='negative')


def _on_edit(cfg, conn_container, tables_panel, columns_panel, server_info_bar):
    def save(new_cfg, old_name=cfg.name):
        try:
            state.conn_manager.update_connection(old_name, new_cfg)
            ui.notify(f'Updated "{new_cfg.name}"', type='positive')
            _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar)
        except Exception as ex:
            ui.notify(str(ex), type='negative')

    connection_dialog(on_save=save, existing=cfg)


def _on_delete(cfg, conn_container, tables_panel, columns_panel, server_info_bar):
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
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar)
    except Exception as ex:
        ui.notify(str(ex), type='negative')


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

    with tables_panel:
        if not data:
            ui.label('No tables found.').classes('text-grey-7')
            return

        columns = [
            {'name': 'name', 'label': 'Table', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
            {'name': 'last_select', 'label': 'Last SELECT', 'field': 'last_select', 'align': 'center'},
            {'name': 'last_insert', 'label': 'Last INSERT', 'field': 'last_insert', 'align': 'center'},
        ]
        rows = [
            {
                'name': t['name'],
                'size': t['size'],
                'size_bytes': t['size_bytes'],
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
                   @click="$parent.$emit('row-click', props.row)">
                <q-td key="name" :props="props">{{ props.row.name }}</q-td>
                <q-td key="size" :props="props">{{ props.row.size }}</q-td>
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

        ui.button('Refresh', icon='refresh', on_click=lambda: _load_tables(tables_panel, columns_panel)).props(
            'flat dense color=primary'
        ).classes('q-mt-sm')


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

    columns = [
        {'name': 'name', 'label': 'Column', 'field': 'name', 'align': 'left', 'sortable': True},
        {'name': 'type', 'label': 'Type', 'field': 'type', 'align': 'left', 'sortable': True},
        {'name': 'codec', 'label': 'Codec', 'field': 'codec', 'align': 'left'},
        {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
    ]
    rows = [
        {
            'name': c['name'],
            'type': c['type'],
            'codec': c.get('codec', ''),
            'size': c.get('size', '0 B'),
            'size_bytes': c.get('size_bytes', 0),
        }
        for c in data
    ]

    ui.table(
        columns=columns,
        rows=rows,
        row_key='name',
        pagination={'rowsPerPage': 0, 'sortBy': 'size', 'descending': True},
    ).classes('w-full')


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

    columns = [
        {'name': 'event_time', 'label': 'Time', 'field': 'event_time', 'align': 'left', 'sortable': True},
        {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True},
        {'name': 'query_kind', 'label': 'Kind', 'field': 'query_kind', 'align': 'center', 'sortable': True},
        {'name': 'query', 'label': 'Query', 'field': 'query_short', 'align': 'left'},
    ]
    rows = [
        {
            'event_time': r['event_time'],
            'user': r['user'],
            'query_kind': r['query_kind'],
            'query_short': r['query'][:50] + ('...' if len(r['query']) > 50 else ''),
            'query_full': r['query'],
        }
        for r in data
    ]

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='event_time',
        pagination={'rowsPerPage': 20, 'sortBy': 'event_time', 'descending': True},
    ).classes('w-full')

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
                {{ props.row.query_short }}
                <q-btn flat dense size="sm" icon="visibility" color="primary"
                       @click.stop="$parent.$emit('show-query', props.row)" />
            </q-td>
        </q-tr>
        ''',
    )

    def on_show_query(e):
        row = e.args
        with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
            ui.label('Query').classes('text-h6 q-mb-sm')
            ui.html(f'<pre style="white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;">{row["query_full"]}</pre>')
            with ui.row().classes('w-full justify-end q-mt-md'):
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
    """Render server disk info into the bar container."""
    bar_container.clear()
    service = state.service
    if not service or not state.active_connection_name:
        return

    try:
        disks = service.get_disk_info()
    except Exception:
        return

    if not disks:
        return

    with bar_container:
        for disk in disks:
            pct = disk['usage_percent']
            color = 'positive' if pct < 70 else ('warning' if pct < 90 else 'negative')

            with ui.row().classes('items-center gap-4 w-full no-wrap'):
                ui.icon('dns').classes('text-grey-7')
                ui.label(state.active_connection_name).classes('text-weight-bold')
                ui.separator().props('vertical')
                ui.label(f'Disk "{disk["name"]}":').classes('text-grey-7')
                ui.label(f'{disk["used"]} / {disk["total"]}')
                ui.linear_progress(
                    value=pct / 100,
                    color=color,
                    track_color='grey-3',
                ).props('rounded').classes('flex-grow').style('max-width: 200px; height: 8px')
                ui.label(f'{pct}%').classes(f'text-weight-bold text-{color}')


@ui.page('/')
def main_page():
    if not require_auth():
        return
    header()

    with ui.row().classes('w-full flex-nowrap q-pa-sm gap-2').style('height: calc(100vh - 64px)'):
        # LEFT: Connections
        with ui.card().classes('q-pa-sm overflow-auto').style('width: 22%; min-width: 200px'):
            with ui.row().classes('items-center justify-between w-full q-mb-sm'):
                ui.label('Connections').classes('text-h6')

            conn_container = ui.column().classes('w-full gap-1')

            # Placeholder — will be set after center/right panels are created
            tables_panel = None
            columns_panel = None
            server_info_bar = None

            # Add button for admin — placed outside conn_container so it survives rebuilds
            add_btn_container = ui.column().classes('w-full')

        # RIGHT SIDE: server info bar + Tables + Table Details
        with ui.column().classes('flex-grow gap-2 overflow-hidden'):
            # Server info bar
            with ui.card().classes('q-pa-sm w-full').props('flat bordered'):
                server_info_bar = ui.row().classes('w-full')

            # Tables + Table Details row
            with ui.row().classes('w-full flex-nowrap gap-2 flex-grow overflow-hidden'):
                # CENTER: Tables
                with ui.card().classes('q-pa-sm overflow-auto').style('width: 45%'):
                    ui.label('Tables').classes('text-h6 q-mb-sm')
                    tables_panel = ui.column().classes('w-full')
                    with tables_panel:
                        ui.label('Select a connection.').classes('text-grey-7')

                # RIGHT: Table Details
                with ui.card().classes('q-pa-sm overflow-auto flex-grow'):
                    ui.label('Table Details').classes('text-h6 q-mb-sm')
                    columns_panel = ui.column().classes('w-full')
                    with columns_panel:
                        ui.label('Select a table.').classes('text-grey-7')

    # Build connections list
    _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar)

    # Add button — outside conn_container, won't be cleared on rebuild
    if is_admin():
        def open_add_dialog():
            def save(cfg):
                try:
                    state.conn_manager.add_connection(cfg)
                    ui.notify(f'Added "{cfg.name}"', type='positive')
                    _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar)
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
