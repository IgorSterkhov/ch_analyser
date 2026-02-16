from nicegui import ui

from ch_analyser.config import ConnectionConfig
from ch_analyser.client import CHClient
from ch_analyser.services import AnalysisService
import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import require_auth, is_admin
from ch_analyser.web.components.header import header
from ch_analyser.web.components.connection_dialog import connection_dialog


def _refresh_table(table_container):
    """Rebuild the connections table inside the given container."""
    table_container.clear()
    connections = state.conn_manager.list_connections()

    with table_container:
        if not connections:
            ui.label('No saved connections. Click "Add Connection" to create one.').classes(
                'text-grey-7 q-pa-md'
            )
            return

        columns = [
            {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'host', 'label': 'Host', 'field': 'host', 'align': 'left'},
            {'name': 'port', 'label': 'Port', 'field': 'port', 'align': 'center'},
            {'name': 'database', 'label': 'Database', 'field': 'database', 'align': 'left'},
            {'name': 'actions', 'label': 'Actions', 'field': 'name', 'align': 'center'},
        ]
        rows = [
            {
                'name': c.name,
                'host': c.host,
                'port': c.port,
                'database': c.database,
            }
            for c in connections
        ]

        tbl = ui.table(columns=columns, rows=rows, row_key='name').classes('w-full')

        admin = is_admin()
        admin_buttons = ''
        if admin:
            admin_buttons = '''
                    <q-btn flat dense icon="edit" color="primary"
                           @click="$parent.$emit('edit', props.row)" />
                    <q-btn flat dense icon="delete" color="negative"
                           @click="$parent.$emit('delete', props.row)" />'''

        tbl.add_slot(
            'body',
            f'''
            <q-tr :props="props">
                <q-td key="name" :props="props">{{{{ props.row.name }}}}</q-td>
                <q-td key="host" :props="props">{{{{ props.row.host }}}}</q-td>
                <q-td key="port" :props="props">{{{{ props.row.port }}}}</q-td>
                <q-td key="database" :props="props">{{{{ props.row.database }}}}</q-td>
                <q-td key="actions" :props="props">{admin_buttons}
                    <q-btn flat dense icon="power_settings_new" color="positive"
                           @click="$parent.$emit('connect', props.row)" />
                </q-td>
            </q-tr>
            ''',
        )

        def on_edit(e):
            row = e.args
            cfg = state.conn_manager.get_connection(row['name'])
            if cfg:
                connection_dialog(
                    on_save=lambda new_cfg, old=cfg.name: _handle_edit(old, new_cfg, table_container),
                    existing=cfg,
                )

        def on_delete(e):
            row = e.args
            try:
                state.conn_manager.delete_connection(row['name'])
                # Disconnect if the deleted connection is the active one
                if state.active_connection_name == row['name']:
                    if state.client and state.client.connected:
                        state.client.disconnect()
                    state.client = None
                    state.service = None
                    state.active_connection_name = None
                ui.notify(f'Deleted connection "{row["name"]}"', type='positive')
                _refresh_table(table_container)
            except Exception as ex:
                ui.notify(str(ex), type='negative')

        def on_connect(e):
            row = e.args
            cfg = state.conn_manager.get_connection(row['name'])
            if not cfg:
                ui.notify(f'Connection "{row["name"]}" not found', type='negative')
                return
            try:
                # Disconnect existing client if any
                if state.client and state.client.connected:
                    state.client.disconnect()

                client = CHClient(cfg)
                client.connect()
                service = AnalysisService(client)
                state.client = client
                state.service = service
                state.active_connection_name = cfg.name
                ui.notify(f'Connected to "{cfg.name}"', type='positive')
                ui.navigate.to('/tables')
            except Exception as ex:
                ui.notify(f'Connection failed: {ex}', type='negative')

        tbl.on('edit', on_edit)
        tbl.on('delete', on_delete)
        tbl.on('connect', on_connect)


def _handle_edit(old_name, new_cfg, table_container):
    try:
        state.conn_manager.update_connection(old_name, new_cfg)
        ui.notify(f'Updated connection "{new_cfg.name}"', type='positive')
        _refresh_table(table_container)
    except Exception as ex:
        ui.notify(str(ex), type='negative')


def _handle_add(cfg: ConnectionConfig, table_container):
    try:
        state.conn_manager.add_connection(cfg)
        ui.notify(f'Added connection "{cfg.name}"', type='positive')
        _refresh_table(table_container)
    except Exception as ex:
        ui.notify(str(ex), type='negative')


@ui.page('/')
def connections_page():
    if not require_auth():
        return
    header()

    with ui.column().classes('w-full max-w-4xl mx-auto q-pa-md'):
        ui.label('Connections').classes('text-h5 q-mb-md')

        table_container = ui.column().classes('w-full')

        if is_admin():
            def open_add_dialog():
                connection_dialog(
                    on_save=lambda cfg: _handle_add(cfg, table_container),
                )

            ui.button('Add Connection', icon='add', on_click=open_add_dialog).props('color=primary')

        _refresh_table(table_container)
