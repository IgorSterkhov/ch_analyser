"""Settings dialog with tabs: General, Connections (admin), Monitoring (admin)."""

from nicegui import ui, app

import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import is_admin
from ch_analyser.config import ConnectionConfig
from ch_analyser.web.components.connection_dialog import connection_dialog

DEFAULT_SETTINGS = {
    'table_density': 'default',  # 'compact' | 'default' | 'comfortable'
}

DENSITY_OPTIONS = {
    'compact': 'Compact',
    'default': 'Default',
    'comfortable': 'Comfortable',
}


def get_settings() -> dict:
    """Return current user settings with defaults applied."""
    saved = app.storage.user.get('settings', {})
    return {**DEFAULT_SETTINGS, **saved}


def get_admin_settings() -> dict:
    """Read admin settings (thresholds) from AppSettingsManager."""
    return {
        'disk_warning_pct': state.app_settings.get_int('DISK_WARNING_PCT', 80),
        'disk_critical_pct': state.app_settings.get_int('DISK_CRITICAL_PCT', 90),
    }


def _save_setting(key: str, value):
    """Persist a single setting key."""
    settings = app.storage.user.get('settings', {})
    settings[key] = value
    app.storage.user['settings'] = settings


def show_settings_dialog(on_connections_changed=None):
    """Open the settings dialog with tabs."""
    settings = get_settings()
    admin = is_admin()

    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 700px; max-width: 900px'):
        ui.label('Settings').classes('text-h6 q-mb-sm')

        with ui.tabs().classes('w-full').props('dense') as tabs:
            general_tab = ui.tab('General', icon='tune').tooltip('UI preferences')
            if admin:
                connections_tab = ui.tab('Connections', icon='dns').tooltip('Server connections')
                monitoring_tab = ui.tab('Monitoring', icon='monitor_heart').tooltip('Alert thresholds')
                qmon_tab = ui.tab('QMON', icon='monitor').tooltip('QMON integration')

        with ui.tab_panels(tabs, value=general_tab).classes('w-full'):
            # ── General tab ──
            with ui.tab_panel(general_tab):
                ui.label('Table Row Density').classes('text-subtitle2 q-mb-xs')

                def _on_density_change(e):
                    _save_setting('table_density', e.value)
                    _apply_density(e.value)

                ui.select(
                    DENSITY_OPTIONS,
                    value=settings['table_density'],
                    on_change=_on_density_change,
                ).classes('w-full q-mb-md')

            # ── Connections tab (admin only) ──
            if admin:
                with ui.tab_panel(connections_tab):
                    conn_list_container = ui.column().classes('w-full gap-1')
                    _build_connections_list(conn_list_container, dlg, on_connections_changed)

                    def _on_add():
                        def save(cfg):
                            try:
                                state.conn_manager.add_connection(cfg)
                                ui.notify(f'Added "{cfg.name}"', type='positive')
                                _build_connections_list(conn_list_container, dlg, on_connections_changed)
                                if on_connections_changed:
                                    on_connections_changed()
                            except Exception as ex:
                                ui.notify(str(ex), type='negative')
                        connection_dialog(on_save=save)

                    ui.button('Add Connection', icon='add', on_click=_on_add).props(
                        'color=primary dense'
                    ).classes('q-mt-sm')

            # ── Monitoring tab (admin only) ──
            if admin:
                with ui.tab_panel(monitoring_tab):
                    admin_cfg = get_admin_settings()

                    ui.label('Disk Usage Thresholds').classes('text-subtitle2 q-mb-xs')

                    warning_input = ui.number(
                        'Warning threshold (%)',
                        value=admin_cfg['disk_warning_pct'],
                        min=0, max=100,
                        format='%d',
                    ).classes('w-full')

                    critical_input = ui.number(
                        'Critical threshold (%)',
                        value=admin_cfg['disk_critical_pct'],
                        min=0, max=100,
                        format='%d',
                    ).classes('w-full')

                    def _save_monitoring():
                        state.app_settings.set('DISK_WARNING_PCT', str(int(warning_input.value)))
                        state.app_settings.set('DISK_CRITICAL_PCT', str(int(critical_input.value)))
                        ui.notify('Monitoring settings saved', type='positive')

                    ui.button('Save', on_click=_save_monitoring).props('color=primary dense').classes('q-mt-sm')

                    ui.separator().classes('q-my-md')
                    ui.label('Service').classes('text-subtitle2 q-mb-xs')

                    def _confirm_shutdown():
                        with ui.dialog() as confirm_dlg, ui.card().classes('q-pa-md'):
                            ui.label('Stop the service?').classes('text-h6')
                            ui.label('The application will shut down and must be restarted manually.').classes('text-body2 q-mb-md')
                            with ui.row().classes('w-full justify-end gap-2'):
                                ui.button('Cancel', on_click=confirm_dlg.close).props('flat')
                                ui.button('Stop', on_click=lambda: app.shutdown()).props('color=negative')
                        confirm_dlg.open()

                    ui.button('Stop Service', icon='power_settings_new', on_click=_confirm_shutdown).props(
                        'color=negative outline dense'
                    ).tooltip('Stop application')

            # ── QMON tab (admin only) ──
            if admin:
                with ui.tab_panel(qmon_tab):
                    ui.label('QMON Integration').classes('text-subtitle2 q-mb-xs')

                    qmon_url_input = ui.input(
                        'QMON Base URL',
                        value=state.app_settings.get('QMON_URL', ''),
                        placeholder='http://host/qmon',
                    ).classes('w-full').tooltip('Base URL of the QMON web application')

                    def _save_qmon():
                        state.app_settings.set('QMON_URL', qmon_url_input.value.strip().rstrip('/'))
                        ui.notify('QMON settings saved', type='positive')

                    ui.button('Save', on_click=_save_qmon).props('color=primary dense').classes('q-mt-sm')

        with ui.row().classes('w-full justify-end q-mt-md'):
            ui.button('Close', on_click=dlg.close).props('flat')

    dlg.open()


def _build_connections_list(container, dlg, on_connections_changed=None):
    """Render connections table inside the Connections tab."""
    container.clear()
    connections = state.conn_manager.list_connections()
    active_name = state.active_connection_name or ''

    with container:
        if not connections:
            ui.label('No connections configured.').classes('text-grey-7')
            return

        rows = []
        for cfg in connections:
            proto = 'HTTPS' if cfg.secure else cfg.protocol.upper()
            rows.append({
                'name': cfg.name,
                'host_port': f'{cfg.host}:{cfg.port}',
                'protocol': proto,
                'status': 'Connected' if cfg.name == active_name else '',
            })

        columns = [
            {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'host_port', 'label': 'Host', 'field': 'host_port', 'align': 'left', 'sortable': True},
            {'name': 'protocol', 'label': 'Protocol', 'field': 'protocol', 'align': 'left', 'sortable': True},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center'},
            {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'right'},
        ]

        tbl = ui.table(
            columns=columns,
            rows=rows,
            row_key='name',
            pagination={'rowsPerPage': 0, 'sortBy': 'name'},
        ).classes('w-full').props('dense flat')

        tbl.add_slot('body', r'''
            <q-tr :props="props">
                <q-td key="name" :props="props">
                    <span :class="props.row.status ? 'text-weight-bold' : ''">
                        {{ props.row.name }}
                    </span>
                </q-td>
                <q-td key="host_port" :props="props">{{ props.row.host_port }}</q-td>
                <q-td key="protocol" :props="props">{{ props.row.protocol }}</q-td>
                <q-td key="status" :props="props">
                    <q-badge v-if="props.row.status" color="positive" :label="props.row.status" />
                </q-td>
                <q-td key="actions" :props="props">
                    <q-btn flat dense size="sm" icon="edit"
                           @click.stop="$parent.$emit('edit', props.row)">
                        <q-tooltip anchor="top middle" self="bottom middle">Edit connection</q-tooltip>
                    </q-btn>
                    <q-btn flat dense size="sm" icon="content_copy"
                           @click.stop="$parent.$emit('copy', props.row)">
                        <q-tooltip anchor="top middle" self="bottom middle">Copy connection</q-tooltip>
                    </q-btn>
                    <q-btn flat dense size="sm" icon="delete" color="negative"
                           @click.stop="$parent.$emit('delete', props.row)">
                        <q-tooltip anchor="top middle" self="bottom middle">Delete connection</q-tooltip>
                    </q-btn>
                </q-td>
            </q-tr>
        ''')

        def _on_edit(e):
            cfg = state.conn_manager.get_connection(e.args['name'])
            if cfg:
                _on_edit_conn(cfg, container, dlg, on_connections_changed)

        def _on_copy(e):
            cfg = state.conn_manager.get_connection(e.args['name'])
            if cfg:
                _on_copy_conn(cfg, container, dlg, on_connections_changed)

        def _on_delete(e):
            cfg = state.conn_manager.get_connection(e.args['name'])
            if cfg:
                _on_delete_conn(cfg, container, dlg, on_connections_changed)

        tbl.on('edit', _on_edit)
        tbl.on('copy', _on_copy)
        tbl.on('delete', _on_delete)


def _on_edit_conn(cfg, container, dlg, on_connections_changed):
    def save(new_cfg, old_name=cfg.name):
        try:
            state.conn_manager.update_connection(old_name, new_cfg)
            if old_name != new_cfg.name and state.monitoring_store:
                state.monitoring_store.rename_server(old_name, new_cfg.name)
            ui.notify(f'Updated "{new_cfg.name}"', type='positive')
            _build_connections_list(container, dlg, on_connections_changed)
            if on_connections_changed:
                on_connections_changed()
        except Exception as ex:
            ui.notify(str(ex), type='negative')
    connection_dialog(on_save=save, existing=cfg)


def _on_copy_conn(cfg, container, dlg, on_connections_changed):
    """Open connection dialog pre-filled with a copy (name + ' copy', password cleared)."""
    copy_cfg = ConnectionConfig(
        name=f'{cfg.name} copy',
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password='',
        protocol=cfg.protocol,
        secure=cfg.secure,
        ca_cert=cfg.ca_cert,
        qmon_alias=cfg.qmon_alias,
    )

    def save(new_cfg):
        try:
            state.conn_manager.add_connection(new_cfg)
            ui.notify(f'Added "{new_cfg.name}"', type='positive')
            _build_connections_list(container, dlg, on_connections_changed)
            if on_connections_changed:
                on_connections_changed()
        except Exception as ex:
            ui.notify(str(ex), type='negative')

    connection_dialog(on_save=save, existing=copy_cfg, title='New Connection')


def _on_delete_conn(cfg, container, dlg, on_connections_changed):
    try:
        state.conn_manager.delete_connection(cfg.name)
        if state.active_connection_name == cfg.name:
            if state.client and state.client.connected:
                state.client.disconnect()
            state.client = None
            state.service = None
            state.active_connection_name = None
        ui.notify(f'Deleted "{cfg.name}"', type='positive')
        _build_connections_list(container, dlg, on_connections_changed)
        if on_connections_changed:
            on_connections_changed()
    except Exception as ex:
        ui.notify(str(ex), type='negative')


def _apply_density(density: str):
    """Apply density CSS class to the page body via JS."""
    ui.run_javascript(
        "document.body.classList.remove('density-compact', 'density-default', 'density-comfortable');"
        f"document.body.classList.add('density-{density}');"
    )


def apply_saved_density():
    """Apply the user's saved density setting on page load."""
    settings = get_settings()
    _apply_density(settings['table_density'])
