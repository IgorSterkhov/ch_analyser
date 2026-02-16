from nicegui import ui, app


def header():
    """Shared header component with navigation and active connection indicator."""
    with ui.header().classes('items-center justify-between'):
        with ui.row().classes('items-center gap-4'):
            ui.label('ClickHouse Analyser').classes('text-h6 text-white')
            ui.link('Connections', '/').classes('text-white no-underline hover:underline')
            ui.link('Tables', '/tables').classes('text-white no-underline hover:underline')

        active_name = app.storage.general.get('active_connection_name')
        if active_name:
            with ui.row().classes('items-center gap-2'):
                ui.icon('link').classes('text-green-300')
                ui.label(f'Connected: {active_name}').classes('text-green-300')
        else:
            ui.label('Not connected').classes('text-grey-400')
