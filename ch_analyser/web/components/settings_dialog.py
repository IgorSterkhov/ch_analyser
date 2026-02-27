"""Settings dialog with tabs: General, Connections (admin), Monitoring (admin)."""

from nicegui import ui, app

import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import is_admin
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

    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 500px; max-width: 600px'):
        ui.label('Settings').classes('text-h6 q-mb-sm')

        with ui.tabs().classes('w-full').props('dense') as tabs:
            general_tab = ui.tab('General', icon='tune')
            if admin:
                connections_tab = ui.tab('Connections', icon='dns')
                monitoring_tab = ui.tab('Monitoring', icon='monitor_heart')

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

        with ui.row().classes('w-full justify-end q-mt-md'):
            ui.button('Close', on_click=dlg.close).props('flat')

    dlg.open()


def _build_connections_list(container, dlg, on_connections_changed=None):
    """Render connection cards inside the Connections tab."""
    container.clear()
    connections = state.conn_manager.list_connections()
    active_name = state.active_connection_name or ''

    with container:
        if not connections:
            ui.label('No connections configured.').classes('text-grey-7')
            return

        for cfg in connections:
            is_active = cfg.name == active_name
            bg = 'bg-blue-1' if is_active else ''

            with ui.card().classes(f'w-full q-pa-xs {bg}').props('flat bordered'):
                with ui.row().classes('items-center w-full justify-between no-wrap'):
                    with ui.column().classes('gap-0'):
                        ui.label(cfg.name).classes('text-weight-bold' if is_active else '')
                        ui.label(f'{cfg.host}:{cfg.port}').classes('text-caption text-grey-7')
                        if is_active:
                            ui.label('Connected').classes('text-caption text-green')

                    with ui.row().classes('gap-1'):
                        ui.button(icon='edit', on_click=lambda c=cfg: _on_edit_conn(
                            c, container, dlg, on_connections_changed
                        )).props('flat dense size=sm')
                        ui.button(icon='delete', on_click=lambda c=cfg: _on_delete_conn(
                            c, container, dlg, on_connections_changed
                        )).props('flat dense size=sm color=negative')


def _on_edit_conn(cfg, container, dlg, on_connections_changed):
    def save(new_cfg, old_name=cfg.name):
        try:
            state.conn_manager.update_connection(old_name, new_cfg)
            ui.notify(f'Updated "{new_cfg.name}"', type='positive')
            _build_connections_list(container, dlg, on_connections_changed)
            if on_connections_changed:
                on_connections_changed()
        except Exception as ex:
            ui.notify(str(ex), type='negative')
    connection_dialog(on_save=save, existing=cfg)


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
