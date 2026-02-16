"""Single-page 3-panel layout: Connections | Tables | Columns."""

from nicegui import ui

from ch_analyser.client import CHClient
from ch_analyser.config import ConnectionConfig
from ch_analyser.services import AnalysisService
import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import require_auth, is_admin
from ch_analyser.web.components.header import header
from ch_analyser.web.components.connection_dialog import connection_dialog


def _build_connections_panel(conn_container, tables_panel, columns_panel):
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
            bg = 'bg-blue-1' if is_active else ''
            with ui.card().classes(f'w-full q-pa-xs q-mb-xs cursor-pointer {bg}').props('flat bordered'):
                with ui.row().classes('items-center w-full justify-between no-wrap'):
                    with ui.column().classes('gap-0'):
                        ui.label(cfg.name).classes('text-weight-bold' if is_active else '')
                        ui.label(f'{cfg.host}:{cfg.port}').classes('text-caption text-grey-7')

                    with ui.row().classes('gap-0'):
                        if admin:
                            ui.button(
                                icon='edit', on_click=lambda c=cfg: _on_edit(c, conn_container, tables_panel, columns_panel)
                            ).props('flat dense size=sm color=primary')
                            ui.button(
                                icon='delete', on_click=lambda c=cfg: _on_delete(c, conn_container, tables_panel, columns_panel)
                            ).props('flat dense size=sm color=negative')
                        ui.button(
                            icon='power_settings_new',
                            on_click=lambda c=cfg: _on_connect(c, conn_container, tables_panel, columns_panel),
                        ).props('flat dense size=sm color=positive')


def _on_connect(cfg, conn_container, tables_panel, columns_panel):
    try:
        if state.client and state.client.connected:
            state.client.disconnect()

        client = CHClient(cfg)
        client.connect()
        state.client = client
        state.service = AnalysisService(client)
        state.active_connection_name = cfg.name
        ui.notify(f'Connected to "{cfg.name}"', type='positive')

        _build_connections_panel(conn_container, tables_panel, columns_panel)
        _load_tables(tables_panel, columns_panel)
        _clear_columns(columns_panel)
    except Exception as ex:
        ui.notify(f'Connection failed: {ex}', type='negative')


def _on_edit(cfg, conn_container, tables_panel, columns_panel):
    def save(new_cfg, old_name=cfg.name):
        try:
            state.conn_manager.update_connection(old_name, new_cfg)
            ui.notify(f'Updated "{new_cfg.name}"', type='positive')
            _build_connections_panel(conn_container, tables_panel, columns_panel)
        except Exception as ex:
            ui.notify(str(ex), type='negative')

    connection_dialog(on_save=save, existing=cfg)


def _on_delete(cfg, conn_container, tables_panel, columns_panel):
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
        ui.notify(f'Deleted "{cfg.name}"', type='positive')
        _build_connections_panel(conn_container, tables_panel, columns_panel)
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
    """Fetch and render columns into the right panel."""
    columns_panel.clear()
    service = state.service
    if not service:
        return

    with columns_panel:
        ui.label(full_table_name).classes('text-subtitle1 text-weight-bold q-mb-sm')

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


def _clear_tables(tables_panel):
    tables_panel.clear()
    with tables_panel:
        ui.label('Select a connection.').classes('text-grey-7')


def _clear_columns(columns_panel):
    columns_panel.clear()
    with columns_panel:
        ui.label('Select a table.').classes('text-grey-7')


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

            # Placeholder panels — will be populated after layout
            tables_panel = None
            columns_panel = None

        # CENTER: Tables
        with ui.card().classes('q-pa-sm overflow-auto').style('width: 40%'):
            ui.label('Tables').classes('text-h6 q-mb-sm')
            tables_panel = ui.column().classes('w-full')
            with tables_panel:
                ui.label('Select a connection.').classes('text-grey-7')

        # RIGHT: Columns
        with ui.card().classes('q-pa-sm overflow-auto flex-grow'):
            ui.label('Columns').classes('text-h6 q-mb-sm')
            columns_panel = ui.column().classes('w-full')
            with columns_panel:
                ui.label('Select a table.').classes('text-grey-7')

    # Now build connections panel (needs tables_panel and columns_panel refs)
    _build_connections_panel(conn_container, tables_panel, columns_panel)

    # Add button for admin (after conn_container is built)
    if is_admin():
        def open_add_dialog():
            def save(cfg):
                try:
                    state.conn_manager.add_connection(cfg)
                    ui.notify(f'Added "{cfg.name}"', type='positive')
                    _build_connections_panel(conn_container, tables_panel, columns_panel)
                except Exception as ex:
                    ui.notify(str(ex), type='negative')
            connection_dialog(on_save=save)

        # Insert the add button into the connections card
        with conn_container:
            ui.button('Add', icon='add', on_click=open_add_dialog).props(
                'color=primary dense'
            ).classes('q-mt-sm w-full')

    # If already connected, show tables
    if state.service:
        _load_tables(tables_panel, columns_panel)
