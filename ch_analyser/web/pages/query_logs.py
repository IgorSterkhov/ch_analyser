"""Query Logs tab — server-wide query log analysis with advanced filtering.

Provides a filterable view of system.query_log for the entire server,
with toggle-button filters, date range controls, LIKE/NOT LIKE query
patterns, column visibility, and All/Grouped mode toggle.
"""

import html
import json
from datetime import date

from nicegui import app, background_tasks, run, ui

from ch_analyser.sql_format import format_clickhouse_sql
import ch_analyser.web.state as state
from ch_analyser.web.pages._shared import (
    copy_to_clipboard,
    apply_text_filter, export_table_csv, export_table_excel,
    PAGINATION_SLOT, HEADER_CELL_TOOLTIP_SLOT,
)


# ── Column definitions ──

ALL_COLUMNS = [
    ('event_time', 'Time', 'Query execution time'),
    ('user', 'User', 'ClickHouse user'),
    ('query_kind', 'Kind', 'Query type (Select, Insert, etc.)'),
    ('query_duration_ms', 'Duration (ms)', 'Execution duration in milliseconds'),
    ('read_k_rows', 'Read kRows', 'Rows read (thousands)'),
    ('read_mbytes', 'Read MB', 'Data read in megabytes'),
    ('mb_mem', 'Mem MB', 'Peak memory usage in megabytes'),
    ('query', 'Query', 'Query text'),
]

GROUPED_COLUMNS = [
    ('sample_query', 'Query', 'Sample query text'),
    ('sample_user', 'User', 'Sample user'),
    ('query_count', 'Count', 'Total execution count'),
    ('error_count', 'Errors', 'Number of failed executions'),
    ('last_time', 'Last', 'Last execution time'),
    ('total_duration_ms', 'Total (ms)', 'Total duration in milliseconds'),
    ('total_read_k_rows', 'Read kRows', 'Total rows read (thousands)'),
    ('total_read_mbytes', 'Read MB', 'Total data read in megabytes'),
    ('peak_mb_mem', 'Peak MB', 'Peak memory usage in megabytes'),
]


# ── Public entry point ──

async def load_query_logs(ctx):
    """Async loader called from server_details lazy-loading."""
    service = state.service
    if not service:
        return

    ctx.query_logs_panel.clear()
    with ctx.query_logs_panel:
        ui.spinner('dots', size='lg').classes('self-center q-mt-md')

    try:
        filters = await run.io_bound(
            lambda: service.get_query_logs_filters(log_days=state.query_log_days))
    except Exception as ex:
        ctx.query_logs_panel.clear()
        with ctx.query_logs_panel:
            ui.notify(f'Failed to load query log filters: {ex}', type='negative')
        return

    ctx.query_logs_panel.clear()
    with ctx.query_logs_panel:
        _render_query_logs(filters)


# ── Main render ──

def _render_query_logs(filters: dict):
    service = state.service
    if not service:
        return

    all_users = filters['users']
    all_kinds = filters['query_kinds']
    all_types = filters['types']
    all_databases = filters['databases']

    # ── Filter state (mutable containers) ──
    active_users = set(all_users)
    active_kinds = set(all_kinds)
    active_types = set(all_types)
    active_dbs = set(all_databases)

    date_filter = [{'mode': 'relative', 'value': state.query_log_days, 'unit': 'day'}]
    query_patterns: list[dict] = []  # [{'text': str, 'negate': bool}]

    mode = ['all']          # 'all' or 'grouped'
    current_limit = [200]
    filters_collapsed = [False]

    # Visibility state
    saved_all_vis = app.storage.tab.get('query_logs_all_visible_cols')
    saved_grp_vis = app.storage.tab.get('query_logs_grouped_visible_cols')
    all_visible = {c: (saved_all_vis.get(c, True) if isinstance(saved_all_vis, dict) else True) for c, _, _ in ALL_COLUMNS}
    grp_visible = {c: (saved_grp_vis.get(c, True) if isinstance(saved_grp_vis, dict) else True) for c, _, _ in GROUPED_COLUMNS}

    # ── Helper: build WHERE text for collapsed view ──
    def _build_where_text() -> str:
        parts = []
        if len(active_users) < len(all_users):
            if active_users:
                parts.append(f"user IN ({', '.join(repr(u) for u in sorted(active_users))})")
            else:
                parts.append("user IN ()")
        if len(active_kinds) < len(all_kinds):
            if active_kinds:
                parts.append(f"query_kind IN ({', '.join(repr(k) for k in sorted(active_kinds))})")
            else:
                parts.append("query_kind IN ()")
        if len(active_types) < len(all_types):
            if active_types:
                parts.append(f"type IN ({', '.join(repr(t) for t in sorted(active_types))})")
            else:
                parts.append("type IN ()")
        if len(active_dbs) < len(all_databases):
            if active_dbs:
                parts.append(f"databases ∩ ({', '.join(repr(d) for d in sorted(active_dbs))})")
            else:
                parts.append("databases ∩ ()")
        df = date_filter[0]
        if df.get('mode') == 'relative':
            parts.append(f"event_time > now() - INTERVAL {df['value']} {df['unit'].upper()}")
        elif df.get('mode') == 'date':
            parts.append(f"event_date = '{df['date']}'")
        elif df.get('mode') == 'range':
            parts.append(f"event_date >= '{df['from']}' AND event_date <= '{df['to']}'")
        for p in query_patterns:
            if p.get('text'):
                op = 'NOT LIKE' if p.get('negate') else 'LIKE'
                parts.append(f"query {op} '%{p['text']}%'")
        return ' AND '.join(parts) if parts else '(no filters)'

    # ── Helper: build service call kwargs ──
    def _build_filter_kwargs() -> dict:
        kwargs: dict = {'log_days': state.query_log_days}
        if len(active_users) < len(all_users):
            kwargs['users'] = sorted(active_users) if active_users else ['__none__']
        if len(active_kinds) < len(all_kinds):
            kwargs['query_kinds'] = sorted(active_kinds) if active_kinds else ['__none__']
        if len(active_types) < len(all_types):
            kwargs['types'] = sorted(active_types) if active_types else ['__none__']
        if len(active_dbs) < len(all_databases):
            kwargs['databases'] = sorted(active_dbs) if active_dbs else ['__none__']
        pats = [p for p in query_patterns if p.get('text')]
        if pats:
            kwargs['query_patterns'] = pats
        df = date_filter[0]
        if df.get('mode') in ('relative', 'date', 'range'):
            kwargs['event_date_filter'] = dict(df)
        return kwargs

    # ── Refresh ──
    def _refresh():
        where_label.text = _build_where_text()
        where_label.update()
        table_container.clear()
        with table_container:
            try:
                kwargs = _build_filter_kwargs()
                if mode[0] == 'all':
                    data = service.get_query_logs(limit=current_limit[0], **kwargs)
                    _render_table_all(data, table_container, all_visible)
                else:
                    data = service.get_query_logs_grouped(**kwargs)
                    _render_table_grouped(data, table_container, grp_visible)
            except Exception as ex:
                ui.label(f'Error: {ex}').classes('text-negative')

    # ── Toggle helpers for filter button sets ──
    def _make_toggle_fns(active_set, all_set, buttons_dict):
        def toggle(val):
            if val in active_set:
                active_set.discard(val)
            else:
                active_set.add(val)
            _update_btn_styles(active_set, buttons_dict)
            _refresh()

        def reset():
            active_set.clear()
            _update_btn_styles(active_set, buttons_dict)
            _refresh()

        def select_all():
            active_set.update(all_set)
            _update_btn_styles(active_set, buttons_dict)
            _refresh()

        return toggle, reset, select_all

    def _update_btn_styles(active_set, buttons_dict):
        for val, btn in buttons_dict.items():
            if val in active_set:
                btn.props('push color=primary text-color=white')
            else:
                btn.props('push color=grey-4 text-color=grey-8')
            btn.update()

    def _render_filter_row(label_text, values, active_set, tooltip_clear='Clear all', tooltip_all='Show all'):
        buttons: dict = {}
        toggle, reset, select_all = _make_toggle_fns(active_set, set(values), buttons)
        with ui.row().classes('w-full items-start gap-1 no-wrap').style('margin-bottom: 2px'):
            ui.label(f'{label_text}:').classes('text-caption text-grey-7').style(
                'line-height: 28px; white-space: nowrap; min-width: 40px'
            )
            ui.button(icon='delete_sweep', on_click=reset).props(
                'flat dense size=sm color=grey-7'
            ).tooltip(tooltip_clear)
            ui.button(icon='select_all', on_click=select_all).props(
                'flat dense size=sm color=grey-7'
            ).tooltip(tooltip_all)
            with ui.element('div').classes('flex flex-wrap gap-0'):
                for v in values:
                    btn = ui.button(v, on_click=lambda v=v: toggle(v))
                    btn.props('push color=primary text-color=white no-caps size=sm')
                    buttons[v] = btn
        return buttons

    # ══════════════════════════════════════════════
    # UI Layout
    # ══════════════════════════════════════════════

    # ── Collapse toggle + WHERE summary ──
    with ui.row().classes('w-full items-center gap-2').style('margin-bottom: 4px'):
        def _toggle_collapse():
            filters_collapsed[0] = not filters_collapsed[0]
            filters_container.set_visibility(not filters_collapsed[0])
            collapse_btn.props(f'icon={"unfold_more" if filters_collapsed[0] else "unfold_less"}')
            collapse_btn.update()
            where_label.set_visibility(filters_collapsed[0])

        collapse_btn = ui.button(icon='unfold_less', on_click=_toggle_collapse).props(
            'flat dense size=sm color=grey-7'
        ).tooltip('Collapse/expand filters')
        ui.label('WHERE').classes('text-caption text-grey-5').style('white-space: nowrap')
        where_label = ui.label(_build_where_text()).classes(
            'text-caption text-grey-7'
        ).style('overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1')
        where_label.set_visibility(False)

    # ── Filters container ──
    filters_container = ui.column().classes('w-full gap-0')
    with filters_container:
        # Toggle-button filter rows
        user_buttons = _render_filter_row('User', all_users, active_users)
        kind_buttons = _render_filter_row('Kind', all_kinds, active_kinds)
        type_buttons = _render_filter_row('Type', all_types, active_types)
        db_buttons = _render_filter_row('DB', all_databases, active_dbs)

        # ── Date filter ──
        with ui.row().classes('w-full items-center gap-2').style('margin-bottom: 2px'):
            ui.label('Date:').classes('text-caption text-grey-7').style(
                'white-space: nowrap; min-width: 40px'
            )

            date_inputs = ui.element('div').classes('flex items-center gap-2')

            def _rebuild_date_inputs():
                date_inputs.clear()
                df = date_filter[0]
                m = df.get('mode', 'relative')
                with date_inputs:
                    if m == 'relative':
                        num = ui.number(value=df.get('value', 7), min=1).props('dense').style(
                            'width: 70px'
                        ).tooltip('Number of time units')
                        unit_sel = ui.select(
                            ['hours', 'days', 'months'],
                            value=df.get('unit', 'day') + 's' if df.get('unit', 'day') + 's' in ('hours', 'days', 'months') else 'days',
                        ).props('dense borderless').style('min-width: 90px').tooltip('Time unit')

                        def _on_relative_change():
                            date_filter[0] = {
                                'mode': 'relative',
                                'value': int(num.value or 7),
                                'unit': (unit_sel.value or 'days').rstrip('s'),
                            }
                            _refresh()

                        num.on('blur', lambda: _on_relative_change())
                        unit_sel.on_value_change(lambda e: _on_relative_change())

                    elif m == 'date':
                        dinp = ui.input(value=df.get('date', str(date.today()))).props(
                            'dense type=date'
                        ).style('width: 160px').tooltip('Select date')

                        def _on_date_change(e):
                            date_filter[0] = {'mode': 'date', 'date': e.value}
                            _refresh()
                        dinp.on('change', _on_date_change)

                    elif m == 'range':
                        finp = ui.input(
                            value=df.get('from', str(date.today())), label='From'
                        ).props('dense type=date').style('width: 160px').tooltip('Start date')
                        tinp = ui.input(
                            value=df.get('to', str(date.today())), label='To'
                        ).props('dense type=date').style('width: 160px').tooltip('End date')

                        def _on_range_change(_=None):
                            date_filter[0] = {
                                'mode': 'range',
                                'from': finp.value,
                                'to': tinp.value,
                            }
                            _refresh()
                        finp.on('change', _on_range_change)
                        tinp.on('change', _on_range_change)

            def _on_date_mode_change(e):
                new_mode = e.value.lower()
                date_filter[0] = {'mode': new_mode}
                if new_mode == 'relative':
                    date_filter[0].update({'value': state.query_log_days, 'unit': 'day'})
                elif new_mode == 'date':
                    date_filter[0]['date'] = str(date.today())
                elif new_mode == 'range':
                    date_filter[0]['from'] = str(date.today())
                    date_filter[0]['to'] = str(date.today())
                _rebuild_date_inputs()
                _refresh()

            ui.select(
                ['Relative', 'Date', 'Range'],
                value='Relative',
                on_change=_on_date_mode_change,
            ).props('dense borderless').style('min-width: 100px').tooltip('Date filter mode')

            _rebuild_date_inputs()

        # ── Query LIKE/NOT LIKE patterns ──
        with ui.row().classes('w-full items-start gap-1 no-wrap').style('margin-bottom: 2px'):
            ui.label('Query:').classes('text-caption text-grey-7').style(
                'line-height: 28px; white-space: nowrap; min-width: 40px'
            )

            def _add_pattern():
                query_patterns.append({'text': '', 'negate': False})
                _rebuild_patterns()

            ui.button(icon='add', on_click=_add_pattern).props(
                'flat dense size=sm color=grey-7'
            ).tooltip('Add LIKE/NOT LIKE pattern')

            patterns_container = ui.column().classes('gap-1')

        def _rebuild_patterns():
            patterns_container.clear()
            with patterns_container:
                for i, p in enumerate(query_patterns):
                    _render_pattern_row(i, p)

        def _render_pattern_row(idx, p):
            with ui.row().classes('items-center gap-1'):
                label = 'NOT LIKE' if p.get('negate') else 'LIKE'
                color = 'negative' if p.get('negate') else 'primary'

                def _toggle_negate(i=idx):
                    query_patterns[i]['negate'] = not query_patterns[i]['negate']
                    _rebuild_patterns()
                    _refresh()

                ui.button(label, on_click=_toggle_negate).props(
                    f'dense no-caps size=sm push color={color}'
                ).tooltip('Toggle LIKE / NOT LIKE')

                pinp = ui.input(value=p.get('text', ''), placeholder='pattern...').props(
                    'dense clearable'
                ).style('width: 200px').tooltip('Search pattern (substring)')

                def _on_text(e, i=idx):
                    query_patterns[i]['text'] = e.value or ''

                def _on_text_enter(i=idx):
                    _refresh()

                pinp.on('update:model-value', _on_text)
                pinp.on('keydown.enter', _on_text_enter)
                pinp.on('clear', lambda i=idx: (query_patterns.__setitem__(i, {**query_patterns[i], 'text': ''}), _refresh()))

                def _remove(i=idx):
                    query_patterns.pop(i)
                    _rebuild_patterns()
                    _refresh()

                ui.button(icon='close', on_click=_remove).props(
                    'flat dense size=sm color=grey-7'
                ).tooltip('Remove pattern')

            # Apply button for this pattern
            ui.button(icon='search', on_click=_refresh).props(
                'flat dense size=sm color=primary'
            ).tooltip('Apply pattern filter')

    # ── Mode + Columns + Controls row ──
    with ui.row().classes('w-full items-center gap-2 q-mt-xs').style('margin-bottom: 2px; flex-wrap: wrap'):
        # Mode toggle
        ui.label('Mode:').classes('text-caption text-grey-7')

        def _set_mode(m):
            mode[0] = m
            _rebuild_col_toggles()
            _refresh()
            mode_all_btn.props(f'push color={"primary" if m == "all" else "grey-4"} text-color={"white" if m == "all" else "grey-8"}')
            mode_grp_btn.props(f'push color={"primary" if m == "grouped" else "grey-4"} text-color={"white" if m == "grouped" else "grey-8"}')
            mode_all_btn.update()
            mode_grp_btn.update()

        mode_all_btn = ui.button('All queries', on_click=lambda: _set_mode('all')).props(
            'push color=primary text-color=white dense no-caps size=sm'
        ).tooltip('Show individual queries')
        mode_grp_btn = ui.button('Grouped', on_click=lambda: _set_mode('grouped')).props(
            'push color=grey-4 text-color=grey-8 dense no-caps size=sm'
        ).tooltip('Group by normalized query hash')

        ui.separator().props('vertical').classes('q-mx-xs')

        # Limit
        ui.label('Limit:').classes('text-caption text-grey-7')
        ui.select(
            [50, 100, 200, 500, 1000], value=200,
            on_change=lambda e: (current_limit.__setitem__(0, e.value), _refresh()),
        ).props('dense borderless').style('min-width: 80px').tooltip('Max results')

        ui.separator().props('vertical').classes('q-mx-xs')

        # Show SQL
        def _show_sql():
            kwargs = _build_filter_kwargs()
            raw_sql = service.get_query_logs_sql(
                limit=current_limit[0],
                grouped=(mode[0] == 'grouped'),
                **kwargs,
            )
            formatted = format_clickhouse_sql(raw_sql)
            escaped = html.escape(formatted)
            with ui.dialog() as dlg, ui.card().classes('w-full max-w-3xl q-pa-md'):
                ui.label('Generated Query').classes('text-h6 q-mb-sm')
                ui.html(f'<pre style="white-space:pre-wrap;word-break:break-all;max-height:60vh;overflow:auto">{escaped}</pre>')
                with ui.row().classes('w-full justify-end q-mt-md gap-2'):
                    copy_js = f'() => window.copyToClipboard({json.dumps(formatted)})'
                    ui.button('Copy', icon='content_copy').props('flat').on('click', js_handler=copy_js)
                    ui.button('Close', on_click=dlg.close).props('flat')
            dlg.open()

        ui.button(icon='code', on_click=_show_sql).props(
            'flat dense color=primary'
        ).tooltip('Show generated SQL')

        # Refresh
        ui.button('Refresh', icon='refresh', on_click=_refresh).props(
            'flat dense color=primary'
        ).tooltip('Reload data')

    # ── Column visibility toggles ──
    col_toggle_container = ui.element('div').classes('flex flex-wrap items-center gap-0 q-mb-xs')

    col_toggle_buttons: dict = {}

    def _rebuild_col_toggles():
        col_toggle_container.clear()
        col_toggle_buttons.clear()
        vis = all_visible if mode[0] == 'all' else grp_visible
        cols = ALL_COLUMNS if mode[0] == 'all' else GROUPED_COLUMNS
        with col_toggle_container:
            ui.label('Columns:').classes('text-caption text-grey-7 q-mr-xs')
            for cid, clabel, _ in cols:
                def _toggle_col(c=cid):
                    vis[c] = not vis[c]
                    b = col_toggle_buttons[c]
                    if vis[c]:
                        b.props('push color=primary text-color=white')
                    else:
                        b.props('push color=grey-4 text-color=grey-8')
                    b.update()
                    _apply_col_visibility()
                    storage_key = 'query_logs_all_visible_cols' if mode[0] == 'all' else 'query_logs_grouped_visible_cols'
                    app.storage.tab[storage_key] = dict(vis)

                btn = ui.button(clabel, on_click=_toggle_col).props(
                    f'push color={"primary" if vis.get(cid, True) else "grey-4"} '
                    f'text-color={"white" if vis.get(cid, True) else "grey-8"} no-caps size=sm'
                ).tooltip(f'Toggle {clabel} column')
                col_toggle_buttons[cid] = btn

    def _apply_col_visibility():
        """Update visible-columns on current table if it exists."""
        vis = all_visible if mode[0] == 'all' else grp_visible
        cols = ALL_COLUMNS if mode[0] == 'all' else GROUPED_COLUMNS
        visible_list = [cid for cid, _, _ in cols if vis.get(cid, True)]
        # Find table in table_container
        for child in table_container:
            if hasattr(child, '_props') and 'columns' in child._props:
                child._props['visible-columns'] = visible_list
                child.update()
                break

    _rebuild_col_toggles()

    # ── Table container ──
    table_container = ui.column().classes('w-full')

    # Initial load
    _refresh()


# ── Table renderers ──

def _render_table_all(data: list[dict], container, visible_cols: dict):
    """Render individual queries table."""
    if not data:
        ui.label('No queries found.').classes('text-grey-7 q-mt-sm')
        return

    rows = []
    for r in data:
        is_error = r.get('exception_code', 0) != 0
        query_short = r['query'][:120] + '...' if len(r['query']) > 120 else r['query']
        rows.append({
            'event_time': r['event_time'],
            'user': r['user'],
            'query_kind': r['query_kind'],
            'query_duration_ms': r['query_duration_ms'],
            'read_k_rows': r['read_k_rows'],
            'read_mbytes': r['read_mbytes'],
            'mb_mem': r['mb_mem'],
            'status': 'error' if is_error else 'ok',
            'query_short': query_short,
            'query_full': r['query'],
            'exception': r.get('exception') or '',
        })

    columns = [
        {'name': 'event_time', 'label': 'Time', 'field': 'event_time', 'align': 'left', 'sortable': True, 'tooltip': 'Query execution time'},
        {'name': 'user', 'label': 'User', 'field': 'user', 'align': 'left', 'sortable': True, 'tooltip': 'ClickHouse user'},
        {'name': 'query_kind', 'label': 'Kind', 'field': 'query_kind', 'align': 'center', 'tooltip': 'Query type'},
        {'name': 'query_duration_ms', 'label': 'Duration (ms)', 'field': 'query_duration_ms', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Execution duration'},
        {'name': 'read_k_rows', 'label': 'Read kRows', 'field': 'read_k_rows', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Rows read (thousands)'},
        {'name': 'read_mbytes', 'label': 'Read MB', 'field': 'read_mbytes', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Data read in megabytes'},
        {'name': 'mb_mem', 'label': 'Mem MB', 'field': 'mb_mem', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Peak memory usage'},
        {'name': 'query', 'label': 'Query', 'field': 'query_short', 'align': 'left', 'tooltip': 'Query text (truncated)'},
    ]

    vis_list = [c for c in visible_cols if visible_cols.get(c, True)]

    filter_input = ui.input(placeholder='Filter...').props('dense clearable').classes('q-mb-sm w-full')

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='event_time',
        pagination={'rowsPerPage': 50, 'sortBy': 'event_time', 'descending': True},
    ).classes('w-full')
    tbl._props['visible-columns'] = vis_list

    tbl.bind_filter_from(filter_input, 'value')
    tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)

    tbl.add_slot('body', r'''
        <q-tr :props="props" class="cursor-pointer"
               @click="$parent.$emit('query-click', props.row)">
            <q-td v-if="props.colsMap.event_time" key="event_time" :props="props" style="white-space: nowrap">
                {{ props.row.event_time }}
            </q-td>
            <q-td v-if="props.colsMap.user" key="user" :props="props">
                {{ props.row.user }}
            </q-td>
            <q-td v-if="props.colsMap.query_kind" key="query_kind" :props="props">
                <q-badge :color="
                    props.row.query_kind === 'Select' ? 'blue-4' :
                    props.row.query_kind === 'Insert' ? 'green-4' :
                    props.row.query_kind === 'Create' ? 'purple-4' :
                    'grey-6'
                " :label="props.row.query_kind" />
            </q-td>
            <q-td v-if="props.colsMap.query_duration_ms" key="query_duration_ms" :props="props">
                {{ props.row.query_duration_ms }}
            </q-td>
            <q-td v-if="props.colsMap.read_k_rows" key="read_k_rows" :props="props">
                {{ props.row.read_k_rows }}
            </q-td>
            <q-td v-if="props.colsMap.read_mbytes" key="read_mbytes" :props="props">
                {{ props.row.read_mbytes }}
            </q-td>
            <q-td v-if="props.colsMap.mb_mem" key="mb_mem" :props="props">
                {{ props.row.mb_mem }}
            </q-td>
            <q-td v-if="props.colsMap.query" key="query" :props="props"
                  style="max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                <q-icon v-if="props.row.status === 'error'" name="cancel" color="negative" size="xs" class="q-mr-xs">
                    <q-tooltip anchor="top middle" self="bottom middle">Query failed</q-tooltip>
                </q-icon>
                {{ props.row.query_short }}
            </q-td>
        </q-tr>
    ''')

    tbl.add_slot('pagination', PAGINATION_SLOT)

    def _on_query_click(e):
        row = e.args
        _show_query_dialog(row['query_full'], row.get('exception', ''))

    tbl.on('query-click', _on_query_click)

    # Export buttons
    with ui.row().classes('gap-1 q-mt-xs'):
        def _get_filtered():
            return apply_text_filter(tbl.rows, columns, filter_input.value)

        ui.button(icon='download', on_click=lambda: export_table_csv(
            _get_filtered(), columns, 'query_logs'
        )).props('flat dense color=primary').tooltip('Export to CSV')
        ui.button(icon='table_chart', on_click=lambda: export_table_excel(
            _get_filtered(), columns, 'query_logs', sheet_name='Query Logs'
        )).props('flat dense color=primary').tooltip('Export to Excel')


def _render_table_grouped(data: list[dict], container, visible_cols: dict):
    """Render grouped queries table."""
    if not data:
        ui.label('No queries found.').classes('text-grey-7 q-mt-sm')
        return

    rows = []
    for r in data:
        query_short = r['sample_query'][:120] + '...' if len(r['sample_query']) > 120 else r['sample_query']
        rows.append({
            'hash': str(r['normalized_query_hash']),
            'sample_query': query_short,
            'sample_query_full': r['sample_query'],
            'sample_user': r['sample_user'],
            'query_count': r['query_count'],
            'error_count': r['error_count'],
            'last_time': r['last_time'],
            'total_duration_ms': r['total_duration_ms'],
            'total_read_k_rows': r['total_read_k_rows'],
            'total_read_mbytes': r['total_read_mbytes'],
            'peak_mb_mem': r['peak_mb_mem'],
            'last_exception': r.get('last_exception') or '',
        })

    columns = [
        {'name': 'sample_query', 'label': 'Query', 'field': 'sample_query', 'align': 'left', 'tooltip': 'Sample query text'},
        {'name': 'sample_user', 'label': 'User', 'field': 'sample_user', 'align': 'left', 'sortable': True, 'tooltip': 'Sample user'},
        {'name': 'query_count', 'label': 'Count', 'field': 'query_count', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Execution count'},
        {'name': 'error_count', 'label': 'Errors', 'field': 'error_count', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Error count'},
        {'name': 'last_time', 'label': 'Last', 'field': 'last_time', 'align': 'center', 'sortable': True, 'tooltip': 'Last execution time'},
        {'name': 'total_duration_ms', 'label': 'Total (ms)', 'field': 'total_duration_ms', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Total duration'},
        {'name': 'total_read_k_rows', 'label': 'Read kRows', 'field': 'total_read_k_rows', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Total rows read (thousands)'},
        {'name': 'total_read_mbytes', 'label': 'Read MB', 'field': 'total_read_mbytes', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Total data read in megabytes'},
        {'name': 'peak_mb_mem', 'label': 'Peak MB', 'field': 'peak_mb_mem', 'align': 'right', 'sortable': True,
         ':sort': '(a, b) => a - b', 'tooltip': 'Peak memory usage in megabytes'},
    ]

    vis_list = [c for c in visible_cols if visible_cols.get(c, True)]

    filter_input = ui.input(placeholder='Filter...').props('dense clearable').classes('q-mb-sm w-full')

    tbl = ui.table(
        columns=columns,
        rows=rows,
        row_key='hash',
        pagination={'rowsPerPage': 50, 'sortBy': 'query_count', 'descending': True},
    ).classes('w-full')
    tbl._props['visible-columns'] = vis_list

    tbl.bind_filter_from(filter_input, 'value')
    tbl.add_slot('header-cell', HEADER_CELL_TOOLTIP_SLOT)

    tbl.add_slot('body', r'''
        <q-tr :props="props" class="cursor-pointer"
               @click="$parent.$emit('group-click', props.row)">
            <q-td v-if="props.colsMap.sample_query" key="sample_query" :props="props"
                  style="max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ props.row.sample_query }}
            </q-td>
            <q-td v-if="props.colsMap.sample_user" key="sample_user" :props="props">
                {{ props.row.sample_user }}
            </q-td>
            <q-td v-if="props.colsMap.query_count" key="query_count" :props="props">
                {{ props.row.query_count }}
            </q-td>
            <q-td v-if="props.colsMap.error_count" key="error_count" :props="props">
                <span :class="props.row.error_count > 0 ? 'text-negative text-weight-bold' : 'text-grey-5'">
                    {{ props.row.error_count }}
                </span>
            </q-td>
            <q-td v-if="props.colsMap.last_time" key="last_time" :props="props" style="white-space: nowrap">
                {{ props.row.last_time }}
            </q-td>
            <q-td v-if="props.colsMap.total_duration_ms" key="total_duration_ms" :props="props">
                {{ props.row.total_duration_ms }}
            </q-td>
            <q-td v-if="props.colsMap.total_read_k_rows" key="total_read_k_rows" :props="props">
                {{ props.row.total_read_k_rows }}
            </q-td>
            <q-td v-if="props.colsMap.total_read_mbytes" key="total_read_mbytes" :props="props">
                {{ props.row.total_read_mbytes }}
            </q-td>
            <q-td v-if="props.colsMap.peak_mb_mem" key="peak_mb_mem" :props="props">
                {{ props.row.peak_mb_mem }}
            </q-td>
        </q-tr>
    ''')

    tbl.add_slot('pagination', PAGINATION_SLOT)

    def _on_group_click(e):
        row = e.args
        _show_query_dialog(row['sample_query_full'], row.get('last_exception', ''))

    tbl.on('group-click', _on_group_click)

    # Export buttons
    with ui.row().classes('gap-1 q-mt-xs'):
        def _get_filtered():
            return apply_text_filter(tbl.rows, columns, filter_input.value)

        ui.button(icon='download', on_click=lambda: export_table_csv(
            _get_filtered(), columns, 'query_logs_grouped'
        )).props('flat dense color=primary').tooltip('Export to CSV')
        ui.button(icon='table_chart', on_click=lambda: export_table_excel(
            _get_filtered(), columns, 'query_logs_grouped', sheet_name='Query Logs Grouped'
        )).props('flat dense color=primary').tooltip('Export to Excel')


# ── Query dialog (local copy to avoid circular import) ──

def _show_query_dialog(query: str, exception: str = ''):
    """Show a dialog with the full query text and optional exception."""
    formatted = format_clickhouse_sql(query)
    with ui.dialog() as dlg, ui.card().classes('q-pa-md').style('min-width: 600px; max-width: 80vw'):
        ui.label('Query').classes('text-h6 q-mb-sm')
        ui.html(
            f'<pre style="white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;">'
            f'{html.escape(formatted)}</pre>'
        )
        if exception:
            ui.label('Exception').classes('text-subtitle2 text-negative q-mt-md q-mb-xs')
            ui.code(exception).classes('w-full text-negative').style('max-height: 150px; overflow: auto')
        with ui.row().classes('w-full justify-end q-mt-md gap-2'):
            copy_js = f'() => window.copyToClipboard({json.dumps(formatted)})'
            ui.button('Copy SQL', icon='content_copy').props('flat').on('click', js_handler=copy_js)
            ui.button('Close', on_click=dlg.close).props('flat')
    dlg.open()
