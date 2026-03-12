from nicegui import run, ui

from ch_analyser.client import CHClient
from ch_analyser.config import ConnectionConfig
import ch_analyser.web.state as state

PORT_DEFAULTS = {
    ("native", False): 9000,
    ("native", True): 9440,
    ("http", False): 8123,
    ("http", True): 8443,
}


def _show_test_result(success: bool, error: str = ''):
    with ui.dialog() as result_dialog, ui.card().classes('w-96'):
        ui.label('Test Result').classes('text-h6 q-mb-sm')
        if success:
            ui.label('Connection successful').classes('text-positive text-bold')
        else:
            ui.label('Connection failed').classes('text-negative text-bold q-mb-sm')
            ui.label(error).classes('text-negative').style(
                'white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto'
            )
        with ui.row().classes('w-full justify-end q-mt-md'):
            ui.button('Close', on_click=result_dialog.close).props('flat')
    result_dialog.open()


def connection_dialog(on_save, existing: ConnectionConfig | None = None, title: str | None = None):
    """Open a dialog to create or edit a connection configuration.

    Args:
        on_save: Callback receiving the new ConnectionConfig.
        existing: If provided, pre-fill the form for editing.
        title: Custom dialog title. Defaults to 'Edit'/'New' based on *existing*.
    """
    with ui.dialog() as dialog, ui.card().classes('w-96'):
        title = title or ('Edit Connection' if existing else 'New Connection')
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

        protocol_select = ui.select(
            {'native': 'Native (TCP)', 'http': 'HTTP'},
            value=existing.protocol if existing else 'native',
            label='Protocol',
        ).classes('w-full')

        ssl_switch = ui.switch(
            'SSL / TLS',
            value=existing.secure if existing else False,
        )

        # CA Certificate path — visible only when SSL is on
        ca_cert_input = ui.input(
            'CA Certificate Path',
            value=existing.ca_cert if existing else '',
        ).classes('w-full')
        ca_cert_input.set_visibility(existing.secure if existing else False)

        def _update_port():
            key = (protocol_select.value, ssl_switch.value)
            port_input.value = PORT_DEFAULTS.get(key, 9000)

        def _on_protocol_change(_):
            _update_port()

        def _on_ssl_change(e):
            _update_port()
            ca_cert_input.set_visibility(e.value)

        protocol_select.on_value_change(_on_protocol_change)
        ssl_switch.on_value_change(_on_ssl_change)

        def _build_config():
            return ConnectionConfig(
                name=name_input.value.strip() or 'test',
                host=host_input.value.strip(),
                port=int(port_input.value or 9000),
                user=user_input.value.strip() or 'default',
                password=password_input.value or '',
                protocol=protocol_select.value,
                secure=ssl_switch.value,
                ca_cert=(ca_cert_input.value or '').strip(),
            )

        with ui.row().classes('w-full justify-end q-mt-md gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat').tooltip('Discard changes')

            async def handle_test():
                if not host_input.value:
                    ui.notify('Host is required', type='warning')
                    return
                cfg = _build_config()
                if state.conn_manager:
                    cfg.ca_cert = cfg.ca_cert or state.conn_manager.ca_cert
                client = CHClient(cfg)
                try:
                    await run.io_bound(client.connect)
                    _show_test_result(success=True)
                except Exception as e:
                    _show_test_result(success=False, error=str(e))
                finally:
                    try:
                        client.disconnect()
                    except Exception:
                        pass

            ui.button('Test', on_click=handle_test).props('flat color=positive').tooltip('Test connection')

            def handle_save():
                if not name_input.value or not host_input.value:
                    ui.notify('Name and Host are required', type='warning')
                    return
                cfg = _build_config()
                dialog.close()
                on_save(cfg)

            ui.button('Save', on_click=handle_save).props('color=primary').tooltip('Save connection')

    dialog.open()
