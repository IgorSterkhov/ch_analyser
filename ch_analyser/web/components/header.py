from nicegui import ui, app

from ch_analyser.web.components.docs_viewer import show_docs_dialog
from ch_analyser.web.components.settings_dialog import show_settings_dialog


def header(on_nav_change=None, active_view='all_servers', on_connections_changed=None):
    """Shared header with navigation, settings, and user info.

    Args:
        on_nav_change: callback(view_name) when nav button is clicked.
        active_view: initial active view name ('all_servers' or 'server_details').
        on_connections_changed: callback when connections are added/edited/deleted in settings.

    Returns:
        update_nav(view_name) function to update button highlighting.
    """
    nav_buttons: dict[str, ui.button] = {}

    def _update_nav(view_name: str):
        for name, btn in nav_buttons.items():
            if name == view_name:
                btn.props('flat dense color=white no-caps').classes('bg-white-3', remove='')
            else:
                btn.props('flat dense color=white no-caps').classes(remove='bg-white-3')
            btn.update()

    def _on_click(view_name: str):
        _update_nav(view_name)
        if on_nav_change:
            on_nav_change(view_name)

    with ui.header().classes('items-center justify-between'):
        with ui.row().classes('items-center gap-2'):
            ui.label('ClickHouse Analyser').classes('text-h6 text-white')
            ui.separator().props('vertical').classes('q-mx-sm').style('height: 24px; opacity: 0.5')

            btn_all = ui.button(
                'All Servers',
                on_click=lambda: _on_click('all_servers'),
            ).props('flat dense color=white no-caps')
            nav_buttons['all_servers'] = btn_all

            btn_details = ui.button(
                'by Server Details',
                on_click=lambda: _on_click('server_details'),
            ).props('flat dense color=white no-caps')
            nav_buttons['server_details'] = btn_details

        with ui.row().classes('items-center gap-4'):
            ui.button(
                icon='settings',
                on_click=lambda: show_settings_dialog(on_connections_changed=on_connections_changed),
            ).props('flat dense color=white')
            ui.button(icon='help_outline', on_click=show_docs_dialog).props('flat dense color=white')
            username = app.storage.user.get('username', '')
            role = app.storage.user.get('role', '')
            if username:
                ui.label(f'{username} ({role})').classes('text-white')
                ui.button(icon='logout', on_click=_logout).props('flat dense color=white')

    _update_nav(active_view)
    return _update_nav


def _logout():
    app.storage.user.clear()
    ui.navigate.to('/login')
