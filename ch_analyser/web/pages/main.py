"""Single-page layout: Connections drawer | Server Info + Tables + Table Details."""

import html
import json
import re

from nicegui import ui

from ch_analyser.client import CHClient
from ch_analyser.config import ConnectionConfig
from ch_analyser.services import AnalysisService
from ch_analyser.sql_format import format_clickhouse_sql
import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import require_auth, is_admin
from ch_analyser.web.components.header import header
from ch_analyser.web.components.connection_dialog import connection_dialog

# Name of the connection currently in "connecting" state (for UI feedback)
_connecting_name: str | None = None

# Flag to suppress right-drawer hide when a table row click bubbles to main_content
_suppress_right_drawer_hide: bool = False

# Clipboard JS fallback for non-HTTPS contexts (remote servers)
_CLIPBOARD_JS = '''
<script>
window.copyToClipboard = function(text) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
    } else {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try { document.execCommand('copy'); } catch(e) {}
        document.body.removeChild(ta);
    }
}
</script>
'''

# Right drawer resize JS — dynamic width + drag handle + sessionStorage
_DRAWER_JS = '''
<script>
window.rightDrawerWidth = parseInt(sessionStorage.getItem('rightDrawerWidth')) || Math.round(window.innerWidth * 0.5);

window.initDrawerResize = function(handleEl) {
    var startX, startWidth;
    handleEl.addEventListener('mousedown', function(e) {
        startX = e.clientX;
        startWidth = window.rightDrawerWidth;
        e.preventDefault();
        document.body.style.userSelect = 'none';

        function onMouseMove(e) {
            var newWidth = startWidth + (startX - e.clientX);
            newWidth = Math.max(300, Math.min(newWidth, Math.round(window.innerWidth * 0.85)));
            window.rightDrawerWidth = newWidth;
            var drawerEl = document.querySelector('.q-drawer--right');
            if (drawerEl) drawerEl.style.setProperty('width', newWidth + 'px', 'important');
            var toggleBtn = document.querySelector('.right-drawer-toggle-btn');
            if (toggleBtn && !toggleBtn.classList.contains('drawer-closed')) {
                toggleBtn.style.right = newWidth + 'px';
            }
        }
        function onMouseUp() {
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            document.body.style.userSelect = '';
            sessionStorage.setItem('rightDrawerWidth', window.rightDrawerWidth);
        }
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

window.selectedTableName = '';

window.mermaidZoom = parseFloat(sessionStorage.getItem('mermaidZoom')) || 1.0;

window.applyMermaidZoom = function() {
    document.querySelectorAll('.mermaid-flow').forEach(function(el) {
        el.style.transform = 'scale(' + window.mermaidZoom + ')';
    });
    document.querySelectorAll('.mermaid-zoom-label').forEach(function(el) {
        el.textContent = Math.round(window.mermaidZoom * 100) + '%';
    });
}

window.mermaidZoomIn = function() {
    window.mermaidZoom = Math.min(window.mermaidZoom + 0.1, 3.0);
    sessionStorage.setItem('mermaidZoom', window.mermaidZoom);
    window.applyMermaidZoom();
}

window.mermaidZoomOut = function() {
    window.mermaidZoom = Math.max(window.mermaidZoom - 0.1, 0.3);
    sessionStorage.setItem('mermaidZoom', window.mermaidZoom);
    window.applyMermaidZoom();
}

// Fullscreen diagram zoom (separate from panel zoom)
window.mermaidFsZoom = 1.0;

window.applyMermaidFsZoom = function() {
    document.querySelectorAll('.mermaid-fs-flow').forEach(function(el) {
        el.style.transform = 'scale(' + window.mermaidFsZoom + ')';
    });
    document.querySelectorAll('.mermaid-fs-zoom-label').forEach(function(el) {
        el.textContent = Math.round(window.mermaidFsZoom * 100) + '%';
    });
}

window.mermaidFsZoomIn = function() {
    window.mermaidFsZoom = Math.min(window.mermaidFsZoom + 0.1, 5.0);
    window.applyMermaidFsZoom();
}

window.mermaidFsZoomOut = function() {
    window.mermaidFsZoom = Math.max(window.mermaidFsZoom - 0.1, 0.2);
    window.applyMermaidFsZoom();
}

window.mermaidFsAutoFit = function() {
    var container = document.querySelector('.mermaid-fs-scroll');
    var svg = document.querySelector('.mermaid-fs-flow svg');
    if (!container || !svg) return;
    // Reset scale to measure natural size
    var flow = document.querySelector('.mermaid-fs-flow');
    flow.style.transform = 'scale(1)';
    var svgW = svg.getBoundingClientRect().width;
    var svgH = svg.getBoundingClientRect().height;
    var cW = container.clientWidth - 20;
    var cH = container.clientHeight - 20;
    if (svgW <= 0 || svgH <= 0) return;
    var scale = Math.min(cW / svgW, cH / svgH, 1.5);
    scale = Math.max(scale, 0.2);
    window.mermaidFsZoom = Math.round(scale * 10) / 10;
    window.applyMermaidFsZoom();
}

window.mermaidFsWheel = function(e) {
    if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        if (e.deltaY < 0) { window.mermaidFsZoomIn(); }
        else { window.mermaidFsZoomOut(); }
    }
}

// Drag-to-pan in fullscreen mode
window.initMermaidFsDrag = function() {
    var sc = document.querySelector('.mermaid-fs-scroll');
    if (!sc) return;
    var dragging = false, startX, startY, scrollL, scrollT;
    sc.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return;
        dragging = true;
        startX = e.clientX; startY = e.clientY;
        scrollL = sc.scrollLeft; scrollT = sc.scrollTop;
        sc.style.cursor = 'grabbing';
        e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        sc.scrollLeft = scrollL - (e.clientX - startX);
        sc.scrollTop = scrollT - (e.clientY - startY);
    });
    document.addEventListener('mouseup', function() {
        if (!dragging) return;
        dragging = false;
        sc.style.cursor = 'grab';
    });
    sc.style.cursor = 'grab';
}
</script>
'''


def _copy_to_clipboard(text: str):
    """Copy text to clipboard with fallback for non-HTTPS contexts."""
    ui.run_javascript(f'window.copyToClipboard({json.dumps(text)})')


def _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer):
    """Render the list of connections into conn_container."""
    conn_container.clear()
    connections = state.conn_manager.list_connections()

    with conn_container:
        if not connections:
            ui.label('No connections yet.').classes('text-grey-7')
            return

        admin = is_admin()
        active_name = state.active_connection_name or ''

        for cfg in connections:
            is_active = cfg.name == active_name
            is_connecting = cfg.name == _connecting_name
            bg = 'bg-blue-1' if is_active else ''

            card = ui.card().classes(f'w-full q-pa-xs q-mb-xs cursor-pointer {bg}').props('flat bordered')
            card.on('click', lambda c=cfg: _on_connect(c, conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer))

            with card:
                with ui.row().classes('items-center w-full justify-between no-wrap'):
                    with ui.column().classes('gap-0'):
                        ui.label(cfg.name).classes('text-weight-bold' if is_active else '')
                        ui.label(f'{cfg.host}:{cfg.port}').classes('text-caption text-grey-7')
                        if is_connecting:
                            ui.label('Connecting...').classes('text-caption text-orange')
                        elif is_active:
                            ui.label('Connected').classes('text-caption text-green')

                    if admin:
                        with ui.button(icon='more_vert').props('flat dense size=sm').classes('self-start').on('click', js_handler='(e) => e.stopPropagation()'):
                            with ui.menu():
                                ui.menu_item(
                                    'Edit',
                                    on_click=lambda c=cfg: _on_edit(c, conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer),
                                )
                                ui.menu_item(
                                    'Delete',
                                    on_click=lambda c=cfg: _on_delete(c, conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer),
                                )


def _on_connect(cfg, conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer):
    global _connecting_name

    # Don't reconnect if already connected to this one
    if state.active_connection_name == cfg.name:
        return

    try:
        # Show "Connecting..." state
        _connecting_name = cfg.name
        state.active_connection_name = None
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer)

        if state.client and state.client.connected:
            state.client.disconnect()

        # Inject global CA cert
        cfg.ca_cert = state.conn_manager.ca_cert

        client = CHClient(cfg)
        client.connect()
        state.client = client
        state.service = AnalysisService(client)
        state.active_connection_name = cfg.name
        _connecting_name = None

        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer)
        _build_server_info_bar(server_info_bar)
        _load_tables(tables_panel, columns_panel, right_drawer)
        _clear_columns(columns_panel, right_drawer)

        # Auto-hide connections drawer after successful connect
        drawer.hide()
    except Exception as ex:
        _connecting_name = None
        state.active_connection_name = None
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer)
        _build_server_info_bar(server_info_bar)
        ui.notify(f'Connection failed: {ex}', type='negative')


def _on_edit(cfg, conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer):
    def save(new_cfg, old_name=cfg.name):
        try:
            state.conn_manager.update_connection(old_name, new_cfg)
            ui.notify(f'Updated "{new_cfg.name}"', type='positive')
            _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer)
        except Exception as ex:
            ui.notify(str(ex), type='negative')

    connection_dialog(on_save=save, existing=cfg)


def _on_delete(cfg, conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer):
    try:
        state.conn_manager.delete_connection(cfg.name)
        if state.active_connection_name == cfg.name:
            if state.client and state.client.connected:
                state.client.disconnect()
            state.client = None
            state.service = None
            state.active_connection_name = None
            _clear_tables(tables_panel)
            _clear_columns(columns_panel, right_drawer)
            _build_server_info_bar(server_info_bar)
        ui.notify(f'Deleted "{cfg.name}"', type='positive')
        _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer)
    except Exception as ex:
        ui.notify(str(ex), type='negative')


def _show_refs_dialog(title: str, refs_list: list[str]):
    """Show a dialog with a list of referencing entities and a Copy button."""
    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 400px'):
        ui.label(f'References: {title}').classes('text-h6 q-mb-sm')
        text = '\n'.join(refs_list)
        for ref in refs_list:
            ui.label(ref).classes('text-body2')
        with ui.row().classes('w-full justify-end q-mt-md gap-2'):
            ui.button('Copy', icon='content_copy',
                      on_click=lambda: _copy_to_clipboard(text)).props('flat')
            ui.button('Close', on_click=dlg.close).props('flat')
    dlg.open()


def _load_tables(tables_panel, columns_panel, right_drawer):
    """Fetch and render tables into the center panel."""
    tables_panel.clear()
    service = state.service
    if not service:
        with tables_panel:
            ui.label('Select a connection.').classes('text-grey-7')
        return

    try:
        data = service.get_tables()
    except Exception as ex:
        with tables_panel:
            ui.notify(f'Failed to load tables: {ex}', type='negative')
        return

    # Get references for all tables
    try:
        refs = service.get_table_references()
    except Exception:
        refs = {}

    with tables_panel:
        if not data:
            ui.label('No tables found.').classes('text-grey-7')
            return

        columns = [
            {'name': 'name', 'label': 'Table', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
             ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
            {'name': 'replicated', 'label': 'R', 'field': 'replicated', 'align': 'center'},
            {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True},
            {'name': 'last_select', 'label': 'Last SELECT', 'field': 'last_select', 'align': 'center'},
            {'name': 'last_insert', 'label': 'Last INSERT', 'field': 'last_insert', 'align': 'center'},
            {'name': 'ttl', 'label': 'TTL', 'field': 'ttl', 'align': 'left'},
        ]
        rows = [
            {
                'name': t['name'],
                'size': t['size'],
                'size_bytes': t['size_bytes'],
                'replicated': t.get('replicated', False),
                'refs_cnt': len(refs.get(t['name'], [])),
                'refs_list': refs.get(t['name'], []),
                'ttl': t.get('ttl', ''),
                'last_select': t['last_select'],
                'last_insert': t['last_insert'],
            }
            for t in data
        ]

        tbl = ui.table(
            columns=columns,
            rows=rows,
            row_key='name',
            pagination={'rowsPerPage': 20, 'sortBy': 'size', 'descending': True},
        ).classes('w-full')

        tbl.add_slot(
            'body',
            r'''
            <q-tr :props="props" class="cursor-pointer"
                   @click="
                     $event.currentTarget.closest('tbody').querySelectorAll('.table-row-active').forEach(r => r.classList.remove('table-row-active'));
                     $event.currentTarget.classList.add('table-row-active');
                     $parent.$emit('row-click', props.row)
                   ">
                <q-td key="name" :props="props">{{ props.row.name }}</q-td>
                <q-td key="size" :props="props">{{ props.row.size }}</q-td>
                <q-td key="replicated" :props="props">
                    <q-icon v-if="props.row.replicated" name="sync" color="primary" size="xs" />
                </q-td>
                <q-td key="refs" :props="props">
                    <q-btn v-if="props.row.refs_cnt > 0" flat dense size="sm"
                           :label="String(props.row.refs_cnt)" color="primary"
                           @click.stop="$parent.$emit('show-refs', props.row)" />
                    <span v-else class="text-grey-5">0</span>
                </q-td>
                <q-td key="last_select" :props="props">{{ props.row.last_select }}</q-td>
                <q-td key="last_insert" :props="props">{{ props.row.last_insert }}</q-td>
                <q-td key="ttl" :props="props">{{ props.row.ttl || '-' }}</q-td>
            </q-tr>
            ''',
        )

        tbl.add_slot(
            'pagination',
            r'''
            <span class="q-mr-sm">Rows per page:</span>
            <q-select
                v-model="props.pagination.rowsPerPage"
                :options="[20, 50, 100, 200, 0]"
                :option-label="opt => opt === 0 ? 'All' : opt"
                dense borderless
                style="min-width: 80px"
                @update:model-value="val => props.pagination.rowsPerPage = val"
            />
            <q-space />
            <span v-if="props.pagination.rowsPerPage > 0" class="q-mx-sm">
                {{ ((props.pagination.page - 1) * props.pagination.rowsPerPage) + 1 }}-{{ Math.min(props.pagination.page * props.pagination.rowsPerPage, props.pagination.rowsNumber) }}
                of {{ props.pagination.rowsNumber }}
            </span>
            <span v-else class="q-mx-sm">{{ props.pagination.rowsNumber }} total</span>
            <q-btn v-if="props.pagination.rowsPerPage > 0"
                icon="chevron_left" dense flat
                :disable="props.pagination.page <= 1"
                @click="props.pagination.page--" />
            <q-btn v-if="props.pagination.rowsPerPage > 0"
                icon="chevron_right" dense flat
                :disable="props.pagination.page >= Math.ceil(props.pagination.rowsNumber / props.pagination.rowsPerPage)"
                @click="props.pagination.page++" />
            ''',
        )

        # Track currently selected table for toggle behavior
        _current_detail_table = [None]

        def on_row_click(e):
            global _suppress_right_drawer_hide
            _suppress_right_drawer_hide = True
            row = e.args
            table_name = row['name']
            if table_name == _current_detail_table[0] and right_drawer.value:
                # Same table clicked again while drawer open -> collapse
                right_drawer.hide()
                _current_detail_table[0] = None
            else:
                _current_detail_table[0] = table_name
                _load_columns(columns_panel, table_name, right_drawer)

        tbl.on('row-click', on_row_click)

        def on_show_refs(e):
            row = e.args
            _show_refs_dialog(row['name'], row.get('refs_list', []))

        tbl.on('show-refs', on_show_refs)

        # --- Show generated SQL button ---
        def _show_tables_sql():
            raw_sql = service.get_tables_sql()
            formatted = format_clickhouse_sql(raw_sql)
            escaped = html.escape(formatted)
            with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
                ui.label('Generated Queries (Tables)').classes('text-h6 q-mb-sm')
                ui.html(f'<pre style="white-space:pre-wrap;word-break:break-all;max-height:60vh;overflow:auto">{escaped}</pre>')
                with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                    ui.button('Copy', icon='content_copy',
                              on_click=lambda: _copy_to_clipboard(formatted)).props('flat')
                    ui.button('Close', on_click=dlg.close).props('flat')
            dlg.open()

        with ui.row().classes('q-mt-sm gap-2'):
            ui.button('Refresh', icon='refresh', on_click=lambda: _load_tables(tables_panel, columns_panel, right_drawer)).props(
                'flat dense color=primary'
            )
            ui.button(icon='code', on_click=_show_tables_sql).props(
                'flat dense color=primary'
            ).tooltip('Show generated SQL')


def _load_columns(columns_panel, full_table_name: str, right_drawer):
    """Fetch and render columns + query history + flow tabs into the right drawer."""
    columns_panel.clear()
    service = state.service
    if not service:
        return

    # Open the right drawer and re-apply row highlight after Vue re-render
    safe_name = json.dumps(full_table_name)
    ui.run_javascript(f'window.selectedTableName = {safe_name}')
    right_drawer.set_value(True)

    ui.run_javascript('''
        setTimeout(function() {
            var name = window.selectedTableName;
            if (!name) return;
            document.querySelectorAll('.table-row-active').forEach(function(r) { r.classList.remove('table-row-active'); });
            document.querySelectorAll('tbody tr td:first-child').forEach(function(td) {
                if (td.textContent.trim() === name) td.closest('tr').classList.add('table-row-active');
            });
        }, 150);
    ''')

    with columns_panel:
        ui.label(full_table_name).classes(
            'text-subtitle1 text-weight-bold text-center w-full q-pa-xs'
        ).style('border: 1px solid #9e9e9e; border-radius: 4px')

        with ui.tabs().classes('w-full').props('dense') as tabs:
            columns_tab = ui.tab('Columns')
            history_tab = ui.tab('Query History')
            flow_tab = ui.tab('Flow')

        loaded_tabs = set()

        with ui.tab_panels(tabs, value=columns_tab).classes('w-full q-pt-none') as tab_panels:
            with ui.tab_panel(columns_tab).classes('q-pa-xs'):
                _render_columns_tab(service, full_table_name)
                loaded_tabs.add('Columns')
            with ui.tab_panel(history_tab).classes('q-pa-xs') as history_panel:
                pass
            with ui.tab_panel(flow_tab).classes('q-pa-xs') as flow_panel:
                pass

        def _on_tab_change(e):
            name = e.value
            if name in loaded_tabs:
                return
            loaded_tabs.add(name)
            if name == 'Query History':
                with history_panel:
                    _render_query_history_tab(service, full_table_name)
            elif name == 'Flow':
                with flow_panel:
                    _render_flow_tab(service, full_table_name)

        tabs.on_value_change(_on_tab_change)


def _render_columns_tab(service, full_table_name: str):
    """Render the columns table inside a tab panel."""
    try:
        data = service.get_columns(full_table_name)
    except Exception as ex:
        ui.notify(f'Failed to load columns: {ex}', type='negative')
        return

    if not data:
        ui.label('No columns found.').classes('text-grey-7')
        return

    # Get column-level references
    try:
        col_refs = service.get_column_references(full_table_name)
    except Exception:
        col_refs = {}

    columns = [
        {'name': 'name', 'label': 'Column', 'field': 'name', 'align': 'left', 'sortable': True},
        {'name': 'type', 'label': 'Type', 'field': 'type', 'align': 'left', 'sortable': True},
        {'name': 'codec', 'label': 'Codec', 'field': 'codec', 'align': 'left'},
        {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
         ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
        {'name': 'refs', 'label': 'Refs', 'field': 'refs_cnt', 'align': 'center', 'sortable': True},
    ]
    rows = [
        {
            'name': c['name'],
            'type': c['type'],
            'codec': c.get('codec', ''),
            'size': c.get('size', '0 B'),
            'size_bytes': c.get('size_bytes', 0),
            'refs_cnt': len(col_refs.get(c['name'], [])),
            'refs_list': col_refs.get(c['name'], []),
        }
        for c in data
    ]

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='name',
        pagination={'rowsPerPage': 0, 'sortBy': 'size', 'descending': True},
    ).classes('w-full')

    tbl.add_slot(
        'body',
        r'''
        <q-tr :props="props">
            <q-td key="name" :props="props">{{ props.row.name }}</q-td>
            <q-td key="type" :props="props">{{ props.row.type }}</q-td>
            <q-td key="codec" :props="props">{{ props.row.codec }}</q-td>
            <q-td key="size" :props="props">{{ props.row.size }}</q-td>
            <q-td key="refs" :props="props">
                <q-btn v-if="props.row.refs_cnt > 0" flat dense size="sm"
                       :label="String(props.row.refs_cnt)" color="primary"
                       @click.stop="$parent.$emit('show-refs', props.row)" />
                <span v-else class="text-grey-5">0</span>
            </q-td>
        </q-tr>
        ''',
    )

    def on_show_col_refs(e):
        row = e.args
        _show_refs_dialog(row['name'], row.get('refs_list', []))

    tbl.on('show-refs', on_show_col_refs)


def _render_query_history_tab(service, full_table_name: str):
    """Render query history table with server-side filtering."""
    # Get filter options from server (GROUP BY query)
    try:
        filters = service.get_query_history_filters(full_table_name)
    except Exception as ex:
        ui.notify(f'Failed to load query history filters: {ex}', type='negative')
        return

    unique_users = filters['users']
    unique_kinds = filters['kinds']
    counts = filters['counts']

    if not unique_users and not unique_kinds:
        ui.label('No query history found.').classes('text-grey-7')
        return

    # State
    active_users = set(unique_users)
    active_kinds = set(unique_kinds)
    current_limit = [200]

    # Cross-filtering matrix from counts
    user_kind_matrix: dict[str, set[str]] = {}
    kind_user_matrix: dict[str, set[str]] = {}
    for c in counts:
        user_kind_matrix.setdefault(c['user'], set()).add(c['query_kind'])
        kind_user_matrix.setdefault(c['query_kind'], set()).add(c['user'])

    user_buttons: dict[str, ui.button] = {}
    kind_buttons: dict[str, ui.button] = {}

    def _update_button_states():
        """Update button visuals based on cross-filtering matrix."""
        if active_users:
            available_kinds = set()
            for u in active_users:
                available_kinds |= user_kind_matrix.get(u, set())
        else:
            available_kinds = set(unique_kinds)

        if active_kinds:
            available_users = set()
            for k in active_kinds:
                available_users |= kind_user_matrix.get(k, set())
        else:
            available_users = set(unique_users)

        for u, btn in user_buttons.items():
            if u not in available_users:
                btn.props('push color=grey-4 text-color=grey-5 disable')
            elif u in active_users:
                btn.props('push color=primary text-color=white')
                btn.props(remove='disable')
            else:
                btn.props('push color=grey-4 text-color=grey-8')
                btn.props(remove='disable')
            btn.update()

        for k, btn in kind_buttons.items():
            if k not in available_kinds:
                btn.props('push color=grey-4 text-color=grey-5 disable')
            elif k in active_kinds:
                btn.props('push color=primary text-color=white')
                btn.props(remove='disable')
            else:
                btn.props('push color=grey-4 text-color=grey-8')
                btn.props(remove='disable')
            btn.update()

    # Direct queries switch state
    direct_only = [True]

    def _refresh():
        """Re-query the server with current filters and rebuild table."""
        users_param = sorted(active_users) if len(active_users) < len(unique_users) else None
        kinds_param = sorted(active_kinds) if len(active_kinds) < len(unique_kinds) else None
        try:
            data = service.get_query_history(
                full_table_name,
                limit=current_limit[0],
                users=users_param,
                kinds=kinds_param,
                direct_only=direct_only[0],
            )
        except Exception as ex:
            ui.notify(f'Failed to load query history: {ex}', type='negative')
            return

        rows = []
        for r in data:
            row = {
                'event_time': r['event_time'],
                'user': r['user'],
                'query_kind': r['query_kind'],
                'query_short': r['query'][:50] + ('...' if len(r['query']) > 50 else ''),
                'query_full': r['query'],
            }
            if not direct_only[0]:
                row['direct'] = '+' if r.get('is_direct') else ''
            rows.append(row)
        _rebuild_table(rows)

    def _rebuild_table(rows):
        """Rebuild the query history table with new data."""
        table_container.clear()
        with table_container:
            if not rows:
                ui.label('No query history found.').classes('text-grey-7')
                return

            filter_input = ui.input(placeholder='Filter...').props('dense clearable').classes('q-mb-sm w-full')

            columns = [
                {'name': 'event_time', 'label': 'Time', 'field': 'event_time', 'align': 'left', 'sortable': True},
                {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True},
                {'name': 'query_kind', 'label': 'Kind', 'field': 'query_kind', 'align': 'center', 'sortable': True},
                {'name': 'query', 'label': 'Query', 'field': 'query_short', 'align': 'left'},
            ]
            if not direct_only[0]:
                columns.insert(3, {'name': 'direct', 'label': 'Direct', 'field': 'direct', 'align': 'center', 'sortable': True})

            body_slot = r'''
                <q-tr :props="props">
                    <q-td key="event_time" :props="props">{{ props.row.event_time }}</q-td>
                    <q-td key="user" :props="props">{{ props.row.user }}</q-td>
                    <q-td key="query_kind" :props="props">{{ props.row.query_kind }}</q-td>'''
            if not direct_only[0]:
                body_slot += r'''
                    <q-td key="direct" :props="props">{{ props.row.direct }}</q-td>'''
            body_slot += r'''
                    <q-td key="query" :props="props">
                        <q-btn flat dense size="sm" icon="visibility" color="primary"
                               @click.stop="$parent.$emit('show-query', props.row)"
                               class="q-mr-xs" />
                        {{ props.row.query_short }}
                    </q-td>
                </q-tr>'''

            tbl = ui.table(
                columns=columns,
                rows=rows,
                row_key='event_time',
                pagination={'rowsPerPage': 20, 'sortBy': 'event_time', 'descending': True},
            ).classes('w-full')

            tbl.bind_filter_from(filter_input, 'value')
            tbl.add_slot('body', body_slot)

            def _highlight_table(sql_text, table_name):
                """Highlight table name occurrences in already-escaped HTML."""
                parts = [re.escape(table_name)]
                if '.' in table_name:
                    parts.append(re.escape(table_name.split('.', 1)[1]))
                pattern = '|'.join(parts)
                return re.sub(
                    f'({pattern})',
                    r'<mark style="background:#fff176;padding:1px 3px;border-radius:2px">\1</mark>',
                    sql_text,
                )

            def on_show_query(e):
                row = e.args
                formatted = format_clickhouse_sql(row['query_full'])
                escaped = html.escape(formatted)
                highlighted = _highlight_table(escaped, full_table_name)

                with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
                    ui.label('Query').classes('text-h6 q-mb-sm')

                    sql_container = ui.html(
                        f'<pre style="white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;">{highlighted}</pre>'
                    )

                    def on_highlight_toggle(e_val):
                        content = highlighted if e_val.value else escaped
                        sql_container.content = (
                            f'<pre style="white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;">{content}</pre>'
                        )
                        sql_container.update()

                    with ui.row().classes('w-full items-center justify-between q-mt-md'):
                        ui.switch('Highlight table', value=True, on_change=on_highlight_toggle)
                        with ui.row().classes('gap-2'):
                            ui.button('Copy', icon='content_copy',
                                      on_click=lambda: _copy_to_clipboard(formatted)).props('flat')
                            ui.button('Close', on_click=dlg.close).props('flat')
                dlg.open()

            tbl.on('show-query', on_show_query)

    def toggle_user(user):
        if user in active_users:
            active_users.discard(user)
        else:
            active_users.add(user)
        _update_button_states()
        _refresh()

    def toggle_kind(kind):
        if kind in active_kinds:
            active_kinds.discard(kind)
        else:
            active_kinds.add(kind)
        _update_button_states()
        _refresh()

    def reset_users():
        active_users.clear()
        _update_button_states()
        _refresh()

    def reset_kinds():
        active_kinds.clear()
        _update_button_states()
        _refresh()

    def _show_generated_query():
        raw_sql = service.get_query_history_sql(
            full_table_name,
            limit=current_limit[0],
            users=sorted(active_users) if len(active_users) < len(unique_users) else None,
            kinds=sorted(active_kinds) if len(active_kinds) < len(unique_kinds) else None,
            direct_only=direct_only[0],
        )
        formatted = format_clickhouse_sql(raw_sql)
        escaped = html.escape(formatted)
        with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
            ui.label('Generated Query').classes('text-h6 q-mb-sm')
            ui.html(f'<pre style="white-space:pre-wrap;word-break:break-all;max-height:60vh;overflow:auto">{escaped}</pre>')
            with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                ui.button('Copy', icon='content_copy',
                          on_click=lambda: _copy_to_clipboard(formatted)).props('flat')
                ui.button('Close', on_click=dlg.close).props('flat')
        dlg.open()

    def _reload_filters_and_refresh():
        """Reload filter options (respecting Direct toggle) and refresh data."""
        nonlocal unique_users, unique_kinds, counts
        try:
            new_filters = service.get_query_history_filters(full_table_name, direct_only=direct_only[0])
        except Exception:
            new_filters = {"users": [], "kinds": [], "counts": []}
        unique_users = new_filters['users']
        unique_kinds = new_filters['kinds']
        counts = new_filters['counts']
        # Rebuild cross-filtering matrix
        user_kind_matrix.clear()
        kind_user_matrix.clear()
        for c in counts:
            user_kind_matrix.setdefault(c['user'], set()).add(c['query_kind'])
            kind_user_matrix.setdefault(c['query_kind'], set()).add(c['user'])
        # Keep only still-valid selections
        active_users.intersection_update(unique_users)
        if not active_users:
            active_users.update(unique_users)
        active_kinds.intersection_update(unique_kinds)
        if not active_kinds:
            active_kinds.update(unique_kinds)
        # Rebuild filter buttons
        _rebuild_filter_buttons()
        _refresh()

    def _rebuild_filter_buttons():
        """Rebuild User and Kind button rows."""
        user_buttons.clear()
        kind_buttons.clear()
        user_btn_container.clear()
        kind_btn_container.clear()
        with user_btn_container:
            for u in unique_users:
                btn = ui.button(u, on_click=lambda u=u: toggle_user(u))
                btn.props('push color=primary text-color=white no-caps size=sm')
                user_buttons[u] = btn
        with kind_btn_container:
            for k in unique_kinds:
                btn = ui.button(k, on_click=lambda k=k: toggle_kind(k))
                btn.props('push color=primary text-color=white no-caps size=sm')
                kind_buttons[k] = btn
        _update_button_states()

    # --- Filter controls ---
    # Row 1: User filter
    with ui.row().classes('w-full items-start gap-1 no-wrap').style('margin-bottom: 2px'):
        ui.label('User:').classes('text-caption text-grey-7').style('line-height: 28px; white-space: nowrap')
        ui.button(icon='delete_sweep', on_click=reset_users).props(
            'flat dense size=sm color=grey-7'
        ).tooltip('Clear all')
        with ui.element('div').classes('flex flex-wrap gap-0') as user_btn_container:
            for u in unique_users:
                btn = ui.button(u, on_click=lambda u=u: toggle_user(u))
                btn.props('push color=primary text-color=white no-caps size=sm')
                user_buttons[u] = btn

    # Row 2: Kind filter
    with ui.row().classes('w-full items-center gap-1 no-wrap').style('margin-bottom: 2px'):
        ui.label('Kind:').classes('text-caption text-grey-7').style('white-space: nowrap')
        ui.button(icon='delete_sweep', on_click=reset_kinds).props(
            'flat dense size=sm color=grey-7'
        ).tooltip('Clear all')
        with ui.element('div').classes('flex flex-wrap gap-0') as kind_btn_container:
            for k in unique_kinds:
                btn = ui.button(k, on_click=lambda k=k: toggle_kind(k))
                btn.props('push color=primary text-color=white no-caps size=sm')
                kind_buttons[k] = btn

    # Row 3: Limit, Direct toggle, Code button, Refresh
    with ui.row().classes('w-full items-center gap-4').style('margin-bottom: 2px'):
        ui.label('Limit:').classes('text-caption text-grey-7')
        ui.select(
            [50, 100, 200, 500, 1000], value=200,
            on_change=lambda e: (current_limit.__setitem__(0, e.value), _refresh()),
        ).props('dense borderless').style('min-width: 80px')

        ui.switch('Direct', value=True,
                  on_change=lambda e: (direct_only.__setitem__(0, e.value), _reload_filters_and_refresh()),
                  ).tooltip('Show only queries that directly mention the table name')

        ui.button(icon='code', on_click=_show_generated_query).props(
            'flat dense color=primary'
        ).tooltip('Show generated SQL')

        ui.button('Refresh', icon='refresh', on_click=_refresh).props('flat dense color=primary')

    # Table container for rebuilding (after filters so it renders below them)
    table_container = ui.column().classes('w-full')

    # Initial load
    _refresh()


def _flow_to_mermaid(flow: dict, highlight_table: str = '') -> str:
    """Convert flow dict to Mermaid flowchart syntax."""
    if not flow['nodes'] and not flow['edges']:
        return ''

    lines = ['%%{init: {"flowchart": {"useMaxWidth": false}}}%%', 'graph TB']
    for node in flow['nodes']:
        node_id = re.sub(r'[^a-zA-Z0-9_]', '_', node['id'])
        label = node['id']
        if node['type'] == 'mv':
            lines.append(f'    {node_id}[/"{label}"/]')
        else:
            lines.append(f'    {node_id}["{label}"]')

    for edge in flow['edges']:
        src_id = re.sub(r'[^a-zA-Z0-9_]', '_', edge['from'])
        dst_id = re.sub(r'[^a-zA-Z0-9_]', '_', edge['to'])
        lines.append(f'    {src_id} --> {dst_id}')

    if highlight_table:
        ht_id = re.sub(r'[^a-zA-Z0-9_]', '_', highlight_table)
        lines.append(f'    style {ht_id} fill:#1976d2,color:#fff')

    return '\n'.join(lines)


def _show_fullscreen_mermaid(mermaid_text: str):
    """Open a maximized dialog with the Mermaid diagram, auto-fit, zoom and wheel scroll."""
    with ui.dialog() as dlg, ui.card().classes('q-pa-none').style(
        'width: 100vw; height: 100vh; max-width: 100vw; max-height: 100vh'
    ):
        dlg.props('maximized')
        # Top bar with zoom controls and close button
        with ui.row().classes('w-full items-center q-pa-xs').style(
            'background: rgba(255,255,255,0.95); border-bottom: 1px solid #e0e0e0'
        ):
            ui.button(icon='remove', on_click=lambda: ui.run_javascript('window.mermaidFsZoomOut()')).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn')
            ui.label('100%').classes('mermaid-fs-zoom-label text-caption')
            ui.button(icon='add', on_click=lambda: ui.run_javascript('window.mermaidFsZoomIn()')).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn')
            ui.button('Fit', icon='fit_screen',
                      on_click=lambda: ui.run_javascript('window.mermaidFsAutoFit()')).props(
                'flat dense size=sm'
            ).classes('q-ml-sm')
            ui.space()
            ui.button(icon='close', on_click=dlg.close).props('flat dense')
        # Scrollable diagram area
        with ui.element('div').classes('mermaid-fs-scroll').style(
            'overflow: auto; flex: 1; width: 100%; height: calc(100vh - 40px)'
        ):
            ui.mermaid(mermaid_text).classes('mermaid-fs-flow')
    dlg.open()
    # Auto-fit + wheel zoom + drag-to-pan after mermaid renders
    ui.timer(0.5, lambda: ui.run_javascript('''
        window.mermaidFsZoom = 1.0;
        window.mermaidFsAutoFit();
        var sc = document.querySelector('.mermaid-fs-scroll');
        if (sc) sc.addEventListener('wheel', window.mermaidFsWheel, {passive: false});
        window.initMermaidFsDrag();
    '''), once=True)


def _render_mermaid_scrollable(mermaid_text: str):
    """Render a Mermaid diagram inside a scrollable container with zoom controls."""
    with ui.element('div').classes('w-full').style('position: relative'):
        # Floating zoom controls
        with ui.row().classes('mermaid-zoom-controls'):
            ui.button(icon='remove', on_click=lambda: ui.run_javascript('window.mermaidZoomOut()')).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn')
            ui.label('100%').classes('mermaid-zoom-label text-caption')
            ui.button(icon='add', on_click=lambda: ui.run_javascript('window.mermaidZoomIn()')).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn')
            ui.button(icon='fullscreen',
                      on_click=lambda t=mermaid_text: _show_fullscreen_mermaid(t)).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn q-ml-xs').tooltip('Fullscreen')
        # Scrollable diagram area
        with ui.element('div').classes('w-full').style('overflow: auto; max-height: 60vh'):
            ui.mermaid(mermaid_text).classes('mermaid-flow')
    # Apply saved zoom level after render
    ui.timer(0.3, lambda: ui.run_javascript('window.applyMermaidZoom()'), once=True)


def _render_flow_tab(service, full_table_name: str):
    """Render flow diagrams using Mermaid."""
    with ui.tabs().classes('w-full').props('dense') as sub_tabs:
        mv_tab = ui.tab('MV Flow')
        query_tab = ui.tab('Query Flow')
        full_tab = ui.tab('Full Flow')

    with ui.tab_panels(sub_tabs, value=mv_tab).classes('w-full'):
        with ui.tab_panel(mv_tab):
            try:
                flow = service.get_mv_flow(full_table_name)
            except Exception as ex:
                ui.notify(f'Failed to load MV flow: {ex}', type='negative')
                flow = {'nodes': [], 'edges': []}

            mermaid_text = _flow_to_mermaid(flow, highlight_table=full_table_name)
            if mermaid_text:
                _render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No materialized view flow found.').classes('text-grey-7')

        with ui.tab_panel(query_tab):
            try:
                flow = service.get_query_flow(full_table_name)
            except Exception as ex:
                ui.notify(f'Failed to load query flow: {ex}', type='negative')
                flow = {'nodes': [], 'edges': []}

            mermaid_text = _flow_to_mermaid(flow, highlight_table=full_table_name)
            if mermaid_text:
                _render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No query-based data flow found.').classes('text-grey-7')

        with ui.tab_panel(full_tab):
            try:
                mv_flow = service.get_mv_flow(full_table_name)
                query_flow = service.get_query_flow(full_table_name)
            except Exception as ex:
                ui.notify(f'Failed to load flow: {ex}', type='negative')
                mv_flow = {'nodes': [], 'edges': []}
                query_flow = {'nodes': [], 'edges': []}

            # Merge flows
            all_nodes = {n['id']: n for n in mv_flow['nodes']}
            for n in query_flow['nodes']:
                if n['id'] not in all_nodes:
                    all_nodes[n['id']] = n

            all_edges_set = set()
            all_edges = []
            for e in mv_flow['edges'] + query_flow['edges']:
                key = (e['from'], e['to'])
                if key not in all_edges_set:
                    all_edges_set.add(key)
                    all_edges.append(e)

            merged = {'nodes': list(all_nodes.values()), 'edges': all_edges}
            mermaid_text = _flow_to_mermaid(merged, highlight_table=full_table_name)
            if mermaid_text:
                _render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No data flow found.').classes('text-grey-7')


def _clear_tables(tables_panel):
    tables_panel.clear()
    with tables_panel:
        ui.label('Select a connection.').classes('text-grey-7')


def _clear_columns(columns_panel, right_drawer=None):
    columns_panel.clear()
    if right_drawer:
        right_drawer.hide()
    with columns_panel:
        ui.label('Select a table.').classes('text-grey-7')


def _build_server_info_bar(bar_container):
    """Render server disk info into the bar container (a ui.card)."""
    bar_container.clear()
    service = state.service
    if not service or not state.active_connection_name:
        bar_container.set_visibility(False)
        return

    try:
        disks = service.get_disk_info()
    except Exception as ex:
        bar_container.set_visibility(False)
        ui.notify(f'Disk info error: {ex}', type='warning')
        return

    if not disks:
        bar_container.set_visibility(False)
        return

    bar_container.set_visibility(True)
    with bar_container:
        for disk in disks:
            pct = float(disk['usage_percent'])
            color = 'positive' if pct < 70 else ('warning' if pct < 90 else 'negative')

            with ui.row().classes('items-center gap-4 w-full no-wrap'):
                ui.icon('dns').classes('text-grey-7')
                ui.label(state.active_connection_name).classes('text-weight-bold')
                ui.separator().props('vertical').style('height: 20px')
                ui.label(f'Disk "{disk["name"]}":').classes('text-grey-7')
                ui.label(f'{disk["used"]} / {disk["total"]}')
                ui.linear_progress(
                    value=round(pct / 100.0, 3),
                    color=color,
                ).props('rounded track-color=grey-3').style('max-width: 200px; height: 8px')
                ui.label(f'{pct:.1f}%').classes(f'text-weight-bold text-{color}')


@ui.page('/')
def main_page():
    if not require_auth():
        return

    # Clipboard fallback for non-HTTPS (remote servers)
    ui.add_head_html(_CLIPBOARD_JS)

    # Right drawer resize support
    ui.add_head_html(_DRAWER_JS)

    # CSS for selected table row highlight, drawer toggle button, and scroll fix
    ui.add_css('''
        .q-table__middle {
            max-height: none !important;
        }
        .table-row-active {
            background-color: #1976d2 !important;
        }
        .table-row-active td {
            color: white !important;
        }
        .drawer-toggle-btn {
            position: fixed !important;
            left: 300px;
            top: 50% !important;
            transform: translateY(-50%) !important;
            width: 24px !important;
            min-width: 24px !important;
            height: 80px !important;
            padding: 0 !important;
            border-radius: 0 8px 8px 0 !important;
            z-index: 1000 !important;
            transition: left 0.3s ease !important;
        }
        .drawer-toggle-btn.drawer-closed {
            left: 0 !important;
        }
        .drawer-toggle-btn .q-icon {
            transition: transform 0.3s ease;
        }
        .drawer-toggle-btn.drawer-closed .q-icon {
            transform: rotate(180deg);
        }
        .right-drawer-toggle-btn {
            position: fixed !important;
            right: 0 !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            width: 24px !important;
            min-width: 24px !important;
            height: 80px !important;
            padding: 0 !important;
            border-radius: 8px 0 0 8px !important;
            z-index: 3001 !important;
            transition: none !important;
        }
        .right-drawer-toggle-btn .q-icon {
            transition: transform 0.3s ease;
        }
        .right-drawer-toggle-btn.drawer-closed .q-icon {
            transform: rotate(180deg);
        }
        .mermaid-flow {
            min-width: max-content;
            transform-origin: top left;
        }
        .mermaid-flow svg {
            max-width: none !important;
            width: auto !important;
            height: auto !important;
        }
        .mermaid-zoom-controls {
            position: absolute;
            top: 4px;
            right: 4px;
            z-index: 10;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 4px;
            border: 1px solid #e0e0e0;
            padding: 2px 4px;
            align-items: center;
            gap: 2px;
        }
        .mermaid-zoom-btn {
            min-width: 28px !important;
            width: 28px !important;
            height: 28px !important;
        }
        .mermaid-fs-flow {
            min-width: max-content;
            transform-origin: top left;
        }
        .mermaid-fs-flow svg {
            max-width: none !important;
            width: auto !important;
            height: auto !important;
        }
        .drawer-resize-handle {
            position: absolute;
            left: 0;
            top: 0;
            width: 6px;
            height: 100%;
            cursor: col-resize;
            z-index: 1001;
            background: transparent;
        }
        .drawer-resize-handle:hover {
            background: rgba(25, 118, 210, 0.3);
        }
    ''')

    # Collapsible connections drawer (left)
    with ui.left_drawer(elevated=True, value=True).classes('q-pa-sm') as drawer:
        with ui.row().classes('items-center justify-between w-full q-mb-sm'):
            ui.label('Connections').classes('text-h6')

        conn_container = ui.column().classes('w-full gap-1')

        # Placeholder — will be set after main panels are created
        tables_panel = None
        columns_panel = None
        server_info_bar = None

        # Add button for admin — placed outside conn_container so it survives rebuilds
        add_btn_container = ui.column().classes('w-full')

    # Collapsible Table Details drawer (right, hidden by default, overlay mode)
    with ui.right_drawer(elevated=True, value=False).classes('q-pa-sm').props('overlay') as right_drawer:
        # Resize handle on the left edge
        resize_handle = ui.element('div').classes('drawer-resize-handle')
        with ui.row().classes('items-center justify-between w-full q-mb-sm'):
            ui.label('Table Details').classes('text-h6')
            ui.button(icon='close', on_click=right_drawer.hide).props('flat dense')
        columns_panel = ui.column().classes('w-full')
        with columns_panel:
            ui.label('Select a table.').classes('text-grey-7')

    # Initialize resize handle for right drawer
    ui.timer(0.5, lambda: ui.run_javascript(
        'var h = document.querySelector(".drawer-resize-handle"); if (h) window.initDrawerResize(h);'
    ), once=True)

    # Sync left drawer toggle button state
    def _on_drawer_change(e):
        if e.value:
            ui.run_javascript("document.querySelector('.drawer-toggle-btn')?.classList.remove('drawer-closed')")
        else:
            ui.run_javascript("document.querySelector('.drawer-toggle-btn')?.classList.add('drawer-closed')")

    drawer.on_value_change(_on_drawer_change)

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

    header(drawer=drawer)

    # Left drawer toggle button — fixed-position, always visible
    ui.button(icon='chevron_left', on_click=lambda: drawer.set_value(not drawer.value)).props(
        'color=primary dense unelevated'
    ).classes('drawer-toggle-btn')

    # Right drawer toggle button — fixed-position, always visible
    ui.button(icon='chevron_right', on_click=lambda: right_drawer.set_value(not right_drawer.value)).props(
        'color=primary dense unelevated'
    ).classes('right-drawer-toggle-btn drawer-closed')

    # Main content area
    main_content = ui.column().classes('w-full q-pa-sm gap-2').style('height: calc(100vh - 64px)')

    with main_content:
        # Server info bar
        server_info_bar = ui.card().classes('q-pa-sm w-full').props('flat bordered')
        server_info_bar.set_visibility(False)

        # Tables panel (full width, Table Details is now in right drawer)
        with ui.card().classes('q-pa-sm overflow-auto w-full flex-grow').style('max-height: calc(100vh - 150px)'):
            ui.label('Tables').classes('text-h6 q-mb-sm')
            tables_panel = ui.column().classes('w-full')
            with tables_panel:
                ui.label('Select a connection.').classes('text-grey-7')

    # Auto-hide drawers when clicking on main content
    def _on_main_click():
        global _suppress_right_drawer_hide
        if drawer.value:
            drawer.hide()
        if _suppress_right_drawer_hide:
            _suppress_right_drawer_hide = False
        elif right_drawer.value:
            right_drawer.hide()

    main_content.on('click', _on_main_click)

    # Build connections list
    _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer)

    # Add button — outside conn_container, won't be cleared on rebuild
    if is_admin():
        def open_add_dialog():
            def save(cfg):
                try:
                    state.conn_manager.add_connection(cfg)
                    ui.notify(f'Added "{cfg.name}"', type='positive')
                    _build_connections_panel(conn_container, tables_panel, columns_panel, server_info_bar, drawer, right_drawer)
                except Exception as ex:
                    ui.notify(str(ex), type='negative')
            connection_dialog(on_save=save)

        with add_btn_container:
            ui.button('Add', icon='add', on_click=open_add_dialog).props(
                'color=primary dense'
            ).classes('q-mt-sm w-full')

    # If already connected, show tables and server info
    if state.service:
        _build_server_info_bar(server_info_bar)
        _load_tables(tables_panel, columns_panel, right_drawer)
