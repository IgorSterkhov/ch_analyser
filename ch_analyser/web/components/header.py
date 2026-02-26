from nicegui import ui, app

from ch_analyser.web.components.docs_viewer import show_docs_dialog
from ch_analyser.web.components.settings_dialog import show_settings_dialog


def header(drawer=None):
    """Shared header with app title, user info, and logout."""
    with ui.header().classes('items-center justify-between'):
        with ui.row().classes('items-center gap-2'):
            if drawer:
                ui.button(icon='menu', on_click=drawer.toggle).props('flat dense color=white')
            ui.label('ClickHouse Analyser').classes('text-h6 text-white')

        with ui.row().classes('items-center gap-4'):
            ui.button(icon='settings', on_click=show_settings_dialog).props('flat dense color=white')
            ui.button(icon='help_outline', on_click=show_docs_dialog).props('flat dense color=white')
            username = app.storage.user.get('username', '')
            role = app.storage.user.get('role', '')
            if username:
                ui.label(f'{username} ({role})').classes('text-white')
                ui.button(icon='logout', on_click=_logout).props('flat dense color=white')


def _logout():
    app.storage.user.clear()
    ui.navigate.to('/login')
