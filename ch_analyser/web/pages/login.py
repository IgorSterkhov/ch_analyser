"""Login page for the web interface."""

from nicegui import ui, app

import ch_analyser.web.state as state


@ui.page('/login')
def login_page():
    def try_login():
        user = state.user_manager.authenticate(username.value, password.value)
        if user:
            app.storage.user['authenticated'] = True
            app.storage.user['username'] = user.name
            app.storage.user['role'] = user.role
            ui.navigate.to('/')
        else:
            ui.notify('Invalid username or password', type='negative')

    with ui.column().classes('absolute-center items-center'):
        ui.label('ClickHouse Analyser').classes('text-h4 q-mb-lg')
        with ui.card().classes('q-pa-md'):
            ui.label('Login').classes('text-h6 q-mb-md')
            username = ui.input('Username').on('keydown.enter', try_login)
            password = ui.input('Password', password=True, password_toggle_button=True).on(
                'keydown.enter', try_login
            )
            ui.button('Login', on_click=try_login).classes('q-mt-md full-width')
