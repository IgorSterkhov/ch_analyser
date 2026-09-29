"""Flow tabs for the server table drawer."""

from nicegui import ui

from ch_analyser.web.pages._shared import flow_to_mermaid, render_mermaid_scrollable


def render_flow_tab(mv_flow, query_flow, full_table_name: str):
    with ui.tabs().classes('w-full').props('dense') as sub_tabs:
        mv_tab = ui.tab('MV Flow').tooltip('Materialized view chains')
        query_tab = ui.tab('Query Flow').tooltip('INSERT…SELECT pipelines and dictionary sources')
        full_tab = ui.tab('Full Flow').tooltip('Combined data flow')

    sub_tabs.on_value_change(
        lambda: ui.timer(0.3, lambda: ui.run_javascript('window.initMermaidDrag()'), once=True)
    )

    with ui.tab_panels(sub_tabs, value=mv_tab).classes('w-full'):
        with ui.tab_panel(mv_tab):
            mermaid_text = flow_to_mermaid(mv_flow, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No materialized view flow found.').classes('text-grey-7')

        with ui.tab_panel(query_tab):
            mermaid_text = flow_to_mermaid(query_flow, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No query or dictionary data flow found.').classes('text-grey-7')

        with ui.tab_panel(full_tab):
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
            mermaid_text = flow_to_mermaid(merged, highlight_table=full_table_name)
            if mermaid_text:
                render_mermaid_scrollable(mermaid_text)
            else:
                ui.label('No data flow found.').classes('text-grey-7')
