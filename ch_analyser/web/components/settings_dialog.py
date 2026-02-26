"""Settings dialog for per-user preferences."""

from nicegui import ui, app

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


def _save_setting(key: str, value):
    """Persist a single setting key."""
    settings = app.storage.user.get('settings', {})
    settings[key] = value
    app.storage.user['settings'] = settings


def show_settings_dialog():
    """Open the settings dialog."""
    settings = get_settings()

    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 350px'):
        ui.label('Settings').classes('text-h6 q-mb-md')

        ui.label('Table Row Density').classes('text-subtitle2 q-mb-xs')

        def _on_density_change(e):
            _save_setting('table_density', e.value)
            _apply_density(e.value)

        ui.select(
            DENSITY_OPTIONS,
            value=settings['table_density'],
            on_change=_on_density_change,
        ).classes('w-full q-mb-md')

        with ui.row().classes('w-full justify-end q-mt-md'):
            ui.button('Close', on_click=dlg.close).props('flat')

    dlg.open()


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
