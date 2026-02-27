"""Main page orchestrator — view switching between All Servers and Server Details."""

import json

from nicegui import ui

import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import require_auth
from ch_analyser.web.components.header import header
from ch_analyser.web.components.settings_dialog import apply_saved_density
from ch_analyser.web.pages._shared import CLIPBOARD_JS, DRAWER_JS, SHARED_CSS
from ch_analyser.web.pages.all_servers import build_all_servers_view
from ch_analyser.web.pages.server_details import (
    build_server_details_view, refresh_connection_options, select_connection,
)


@ui.page('/')
def main_page():
    if not require_auth():
        return

    # CSS/JS
    ui.add_head_html(CLIPBOARD_JS)
    ui.add_head_html(DRAWER_JS)
    ui.add_css(SHARED_CSS)

    # Apply user's saved table density
    apply_saved_density()

    # Right drawer (page-level, for Table Details)
    with ui.right_drawer(elevated=True, value=False).classes('q-pa-sm').props('overlay') as right_drawer:
        resize_handle = ui.element('div').classes('drawer-resize-handle')
        with ui.row().classes('items-center justify-between w-full q-mb-sm'):
            ui.label('Table Details').classes('text-h6')
            ui.button(icon='close', on_click=right_drawer.hide).props('flat dense')
        columns_panel = ui.column().classes('w-full')
        with columns_panel:
            ui.label('Select a table.').classes('text-grey-7')

    # Initialize resize handle
    ui.timer(0.5, lambda: ui.run_javascript(
        'var h = document.querySelector(".drawer-resize-handle"); if (h) window.initDrawerResize(h);'
    ), once=True)

    # Sync right drawer toggle button state + dynamic width
    def _on_right_drawer_change(e):
        if e.value:
            ui.run_javascript("""
                var w = window.rightDrawerWidth || Math.round(window.innerWidth * 0.5);
                var btn = document.querySelector('.right-drawer-toggle-btn');
                if (btn) { btn.classList.remove('drawer-closed'); btn.style.right = w + 'px'; }
                var drawerEl = document.querySelector('.q-drawer--right');
                if (drawerEl) drawerEl.style.setProperty('width', w + 'px', 'important');
            """)
        else:
            ui.run_javascript("""
                var btn = document.querySelector('.right-drawer-toggle-btn');
                if (btn) { btn.classList.add('drawer-closed'); btn.style.right = '0'; }
            """)

    right_drawer.on_value_change(_on_right_drawer_change)

    # Right drawer toggle button
    ui.button(icon='chevron_right', on_click=lambda: right_drawer.set_value(not right_drawer.value)).props(
        'color=primary dense unelevated'
    ).classes('right-drawer-toggle-btn drawer-closed')

    # View containers (created before header so drill_down can reference ctx)
    all_view = None
    details_view = None
    ctx = None
    all_view_container = None

    def switch_view(view_name):
        if all_view_container:
            all_view_container.set_visibility(view_name == 'all_servers')
        if details_view:
            details_view.set_visibility(view_name == 'server_details')
        update_nav(view_name)
        # Hide right drawer & toggle when on All Servers
        if view_name == 'all_servers':
            if right_drawer.value:
                right_drawer.hide()
            ui.run_javascript(
                "document.querySelector('.right-drawer-toggle-btn')?.style.setProperty('display','none')"
            )
        else:
            ui.run_javascript(
                "document.querySelector('.right-drawer-toggle-btn')?.style.setProperty('display','')"
            )

    def drill_down(server_name, table_name=None):
        switch_view('server_details')
        if ctx:
            select_connection(ctx, server_name)

    def _on_connections_changed():
        """Called when connections are modified in settings dialog."""
        if ctx:
            refresh_connection_options(ctx)
        # Rebuild all_servers view
        if all_view_container:
            all_view_container.clear()
            with all_view_container:
                build_all_servers_view(all_view_container, on_drill_down=drill_down)

    # Header with navigation
    update_nav = header(
        on_nav_change=switch_view,
        active_view='all_servers',
        on_connections_changed=_on_connections_changed,
    )

    # Main content area
    with ui.column().classes('w-full q-pa-sm').style('height: calc(100vh - 64px); overflow: auto'):
        # All Servers view
        all_view_container = ui.column().classes('w-full')
        with all_view_container:
            build_all_servers_view(all_view_container, on_drill_down=drill_down)

        # Server Details view (hidden by default)
        details_view = ui.column().classes('w-full')
        details_view.set_visibility(False)
        ctx = build_server_details_view(details_view, right_drawer, columns_panel)

    # Hide right drawer toggle initially (All Servers view)
    ui.run_javascript(
        "document.querySelector('.right-drawer-toggle-btn')?.style.setProperty('display','none')"
    )
