from nicegui import ui

from ch_analyser.config import ConnectionConfig


def connection_dialog(on_save, existing: ConnectionConfig | None = None):
    """Open a dialog to create or edit a connection configuration.

    Args:
        on_save: Callback receiving the new ConnectionConfig.
        existing: If provided, pre-fill the form for editing.
    """
    with ui.dialog() as dialog, ui.card().classes('w-96'):
        title = 'Edit Connection' if existing else 'New Connection'
        ui.label(title).classes('text-h6 q-mb-sm')

        name_input = ui.input(
            'Connection Name',
            value=existing.name if existing else '',
        ).classes('w-full')
        host_input = ui.input(
            'Host',
            value=existing.host if existing else 'localhost',
        ).classes('w-full')
        port_input = ui.number(
            'Port',
            value=existing.port if existing else 9000,
            format='%d',
        ).classes('w-full')
        user_input = ui.input(
            'User',
            value=existing.user if existing else 'default',
        ).classes('w-full')
        password_input = ui.input(
            'Password',
            value=existing.password if existing else '',
            password=True,
            password_toggle_button=True,
        ).classes('w-full')

        with ui.row().classes('w-full justify-end q-mt-md gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            def handle_save():
                if not name_input.value or not host_input.value:
                    ui.notify('Name and Host are required', type='warning')
                    return
                cfg = ConnectionConfig(
                    name=name_input.value.strip(),
                    host=host_input.value.strip(),
                    port=int(port_input.value or 9000),
                    user=user_input.value.strip() or 'default',
                    password=password_input.value or '',
                )
                dialog.close()
                on_save(cfg)

            ui.button('Save', on_click=handle_save).props('color=primary')

    dialog.open()
