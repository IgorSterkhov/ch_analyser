from nicegui import ui, app

from ch_analyser.web.components.header import header


@ui.page('/columns/{table_name}')
def columns_page(table_name: str):
    service = app.storage.general.get('service')
    if not service:
        ui.notify('Not connected. Redirecting to connections page.', type='warning')
        ui.navigate.to('/')
        return

    header()

    with ui.column().classes('w-full max-w-5xl mx-auto q-pa-md'):
        ui.label(f'Columns \u2014 {table_name}').classes('text-h5 q-mb-md')

        try:
            data = service.get_columns(table_name)
        except Exception as ex:
            ui.notify(f'Failed to load columns: {ex}', type='negative')
            data = []

        if not data:
            ui.label('No columns found for this table.').classes('text-grey-7')
        else:
            columns = [
                {'name': 'name', 'label': 'Column Name', 'field': 'name', 'align': 'left', 'sortable': True},
                {'name': 'type', 'label': 'Type', 'field': 'type', 'align': 'left', 'sortable': True},
                {'name': 'codec', 'label': 'Codec', 'field': 'codec', 'align': 'left'},
                {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
                 ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
            ]
            rows = [
                {
                    'name': c['name'],
                    'type': c['type'],
                    'codec': c.get('codec', ''),
                    'size': c.get('size', '0 B'),
                    'size_bytes': c.get('size_bytes', 0),
                }
                for c in data
            ]

            ui.table(
                columns=columns,
                rows=rows,
                row_key='name',
                pagination={'rowsPerPage': 0, 'sortBy': 'size', 'descending': True},
            ).classes('w-full')

        ui.button('Back to Tables', icon='arrow_back', on_click=lambda: ui.navigate.to('/tables')).props(
            'flat color=primary'
        ).classes('q-mt-md')
