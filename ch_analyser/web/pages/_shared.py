"""Shared JS, CSS, and utility functions used by multiple page modules."""

import json
import re

from nicegui import ui

# Clipboard JS fallback for non-HTTPS contexts (remote servers)
CLIPBOARD_JS = '''
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
DRAWER_JS = '''
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
                toggleBtn.style.setProperty('right', newWidth + 'px', 'important');
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

# Shared CSS for the application
SHARED_CSS = '''
    .q-table__middle {
        max-height: none !important;
    }
    .table-row-active {
        background-color: #1976d2 !important;
    }
    .table-row-active td {
        color: white !important;
    }
    .right-drawer-toggle-btn {
        position: fixed !important;
        right: 0;
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
    /* Table density settings */
    .density-compact .q-table td,
    .density-compact .q-table th {
        padding: 2px 8px !important;
        height: auto !important;
        font-size: 0.8rem;
        line-height: 1.2;
    }
    .density-compact .q-table .q-btn--dense {
        padding: 0 4px !important;
        min-height: 0 !important;
    }
    .density-comfortable .q-table td,
    .density-comfortable .q-table th {
        padding: 12px 16px !important;
    }
    /* Nav active highlight */
    .bg-white-3 {
        background: rgba(255,255,255,0.2) !important;
        border-radius: 4px;
    }
'''

# Standard pagination slot template for Quasar tables
PAGINATION_SLOT = r'''
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
'''


def copy_to_clipboard(text: str):
    """Copy text to clipboard with fallback for non-HTTPS contexts."""
    ui.run_javascript(f'window.copyToClipboard({json.dumps(text)})')


def show_refs_dialog(title: str, refs_list: list[str]):
    """Show a dialog with a list of referencing entities and a Copy button."""
    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 400px'):
        ui.label(f'References: {title}').classes('text-h6 q-mb-sm')
        text = '\n'.join(refs_list)
        for ref in refs_list:
            ui.label(ref).classes('text-body2')
        with ui.row().classes('w-full justify-end q-mt-md gap-2'):
            copy_js = f'() => window.copyToClipboard({json.dumps(text)})'
            ui.button('Copy', icon='content_copy').props('flat').on('click', js_handler=copy_js)
            ui.button('Close', on_click=dlg.close).props('flat')
    dlg.open()


def flow_to_mermaid(flow: dict, highlight_table: str = '') -> str:
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


def show_fullscreen_mermaid(mermaid_text: str):
    """Open a maximized dialog with the Mermaid diagram."""
    with ui.dialog() as dlg, ui.card().classes('q-pa-none').style(
        'width: 100vw; height: 100vh; max-width: 100vw; max-height: 100vh'
    ):
        dlg.props('maximized')
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
        with ui.element('div').classes('mermaid-fs-scroll').style(
            'overflow: auto; flex: 1; width: 100%; height: calc(100vh - 40px)'
        ):
            ui.mermaid(mermaid_text).classes('mermaid-fs-flow')
    dlg.open()
    ui.timer(0.5, lambda: ui.run_javascript('''
        window.mermaidFsZoom = 1.0;
        window.mermaidFsAutoFit();
        var sc = document.querySelector('.mermaid-fs-scroll');
        if (sc) sc.addEventListener('wheel', window.mermaidFsWheel, {passive: false});
        window.initMermaidFsDrag();
    '''), once=True)


def render_mermaid_scrollable(mermaid_text: str):
    """Render a Mermaid diagram inside a scrollable container with zoom controls."""
    with ui.element('div').classes('w-full').style('position: relative'):
        with ui.row().classes('mermaid-zoom-controls'):
            ui.button(icon='remove', on_click=lambda: ui.run_javascript('window.mermaidZoomOut()')).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn')
            ui.label('100%').classes('mermaid-zoom-label text-caption')
            ui.button(icon='add', on_click=lambda: ui.run_javascript('window.mermaidZoomIn()')).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn')
            ui.button(icon='fullscreen',
                      on_click=lambda t=mermaid_text: show_fullscreen_mermaid(t)).props(
                'flat dense size=sm'
            ).classes('mermaid-zoom-btn q-ml-xs').tooltip('Fullscreen')
        with ui.element('div').classes('w-full').style('overflow: auto; max-height: 60vh'):
            ui.mermaid(mermaid_text).classes('mermaid-flow')
    ui.timer(0.3, lambda: ui.run_javascript('window.applyMermaidZoom()'), once=True)
