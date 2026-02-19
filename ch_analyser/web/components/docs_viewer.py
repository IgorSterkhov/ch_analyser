"""In-app documentation viewer dialog (user-facing docs only)."""

import re
from pathlib import Path

from nicegui import ui

# User-facing docs shown in the viewer
USER_DOCS = [
    ('Руководство пользователя', 'user-guide.md'),
    ('Руководство администратора', 'admin-guide.md'),
    ('Релизы', 'releases.md'),
]

_DOCS_DIR = Path(__file__).resolve().parents[3] / 'docs'


def _read_doc(filename: str) -> str:
    path = _DOCS_DIR / filename
    if path.is_file():
        return path.read_text(encoding='utf-8')
    return f'*Файл `{filename}` не найден.*'


def _preprocess_links(content: str) -> str:
    """Replace cross-links to .md files with bold text + hint."""
    def _replace(m):
        text = m.group(1)
        return f'**{text}** *(см. меню слева)*'
    return re.sub(r'\[([^\]]+)\]\([a-z-]+\.md\)', _replace, content)


def show_docs_dialog():
    """Open a full-screen dialog with user-facing documentation."""
    with ui.dialog().props('maximized') as dlg, \
         ui.card().classes('w-full h-full q-pa-none').style(
             'display: flex; flex-direction: column; overflow: hidden'
         ):

        # Header bar
        with ui.row().classes('w-full items-center q-pa-md bg-primary text-white').style('flex-shrink: 0'):
            ui.label('Documentation').classes('text-h6')
            ui.space()
            ui.button(icon='close', on_click=dlg.close).props('flat dense color=white')

        nav_buttons: dict[str, ui.button] = {}
        content_container = None

        def _show(filename: str):
            nonlocal content_container
            raw = _read_doc(filename)
            processed = _preprocess_links(raw)
            content_container.clear()
            with content_container:
                ui.markdown(processed).classes('w-full')
            for fname, btn in nav_buttons.items():
                if fname == filename:
                    btn.props('color=primary')
                else:
                    btn.props('color=grey-4 text-color=grey-8')
                btn.update()

        # Body: sidebar + content — takes all remaining height
        with ui.row().classes('w-full overflow-hidden').style(
            'flex: 1 1 0; min-height: 0'
        ):
            # Sidebar
            with ui.column().classes('q-pa-md gap-1').style('width: 240px; min-width: 240px'):
                for label, fname in USER_DOCS:
                    btn = ui.button(label, on_click=lambda f=fname: _show(f)).props(
                        'no-caps push color=grey-4 text-color=grey-8'
                    ).classes('w-full justify-start')
                    nav_buttons[fname] = btn

            # Content area — scrollable
            content_container = ui.column().classes(
                'flex-grow q-pa-lg overflow-auto'
            ).style('min-height: 0; height: 100%')

        # Show first doc by default
        _show(USER_DOCS[0][1])

    dlg.open()
