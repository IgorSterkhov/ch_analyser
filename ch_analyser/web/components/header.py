from nicegui import ui, app

import ch_analyser.web.state as state


def header():
    """Shared header component with navigation, active connection indicator, and user info."""
    with ui.header().classes('items-center justify-between'):
        with ui.row().classes('items-center gap-4'):
            ui.label('ClickHouse Analyser').classes('text-h6 text-white')
            ui.link('Connections', '/').classes('text-white no-underline hover:underline')
            ui.link('Tables', '/tables').classes('text-white no-underline hover:underline')

        with ui.row().classes('items-center gap-4'):
            active_name = state.active_connection_name
            if active_name:
                with ui.row().classes('items-center gap-2'):
                    ui.icon('link').classes('text-green-300')
                    ui.label(f'Connected: {active_name}').classes('text-green-300')
            else:
                ui.label('Not connected').classes('text-grey-400')

            username = app.storage.user.get('username', '')
            role = app.storage.user.get('role', '')
            if username:
                ui.label(f'{username} ({role})').classes('text-white')
                ui.button(icon='logout', on_click=_logout).props('flat dense color=white')


def _logout():
    app.storage.user.clear()
    ui.navigate.to('/login')
