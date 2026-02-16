from nicegui import ui

import ch_analyser.web.state as state
from ch_analyser.web.auth_helpers import require_auth
from ch_analyser.web.components.header import header


@ui.page('/tables')
def tables_page():
    if not require_auth():
        return
    service = state.service
    if not service:
        ui.notify('Not connected. Redirecting to connections page.', type='warning')
        ui.navigate.to('/')
        return

    header()

    with ui.column().classes('w-full max-w-5xl mx-auto q-pa-md'):
        active_name = state.active_connection_name or ''
        ui.label(f'Tables \u2014 {active_name}').classes('text-h5 q-mb-md')

        table_container = ui.column().classes('w-full')

        def load_tables():
            table_container.clear()
            try:
                data = service.get_tables()
            except Exception as ex:
                ui.notify(f'Failed to load tables: {ex}', type='negative')
                return

            with table_container:
                if not data:
                    ui.label('No tables found in this database.').classes('text-grey-7')
                    return

                columns = [
                    {'name': 'name', 'label': 'Table Name', 'field': 'name', 'align': 'left', 'sortable': True},
                    {'name': 'size', 'label': 'Size', 'field': 'size', 'align': 'right', 'sortable': True,
                     ':sort': '(a, b, rowA, rowB) => rowA.size_bytes - rowB.size_bytes'},
                    {'name': 'last_select', 'label': 'Last SELECT', 'field': 'last_select', 'align': 'center'},
                    {'name': 'last_insert', 'label': 'Last INSERT', 'field': 'last_insert', 'align': 'center'},
                ]
                rows = [
                    {
                        'name': t['name'],
                        'size': t['size'],
                        'size_bytes': t['size_bytes'],
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
                           @click="$parent.$emit('row-click', props.row)">
                        <q-td key="name" :props="props">{{ props.row.name }}</q-td>
                        <q-td key="size" :props="props">{{ props.row.size }}</q-td>
                        <q-td key="last_select" :props="props">{{ props.row.last_select }}</q-td>
                        <q-td key="last_insert" :props="props">{{ props.row.last_insert }}</q-td>
                    </q-tr>
                    ''',
                )

                # Rows per page selector
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

                def on_row_click(e):
                    row = e.args
                    ui.navigate.to(f'/columns/{row["name"]}')

                tbl.on('row-click', on_row_click)

        with ui.row().classes('q-mb-md'):
            ui.button('Refresh', icon='refresh', on_click=load_tables).props('color=primary')
            ui.button('Back to Connections', icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props('flat')

        load_tables()
