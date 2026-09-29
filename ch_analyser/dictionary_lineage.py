"""Extract a ClickHouse dictionary's direct table source without exposing its DDL."""

import re


_IDENT = r'(?:`[^`]+`|"[^"]+"|[A-Za-z_][\w]*)'


def _clickhouse_source(ddl: str) -> str:
    match = re.search(r'\bSOURCE\s*\(\s*CLICKHOUSE\s*\(', ddl, re.IGNORECASE)
    if not match:
        return ''
    start = match.end()
    depth = 1
    quoted = False
    index = start
    while index < len(ddl):
        char = ddl[index]
        if char == "'":
            if quoted and index + 1 < len(ddl) and ddl[index + 1] == "'":
                index += 2
                continue
            if not (index > 0 and ddl[index - 1] == '\\'):
                quoted = not quoted
        elif not quoted:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    return ddl[start:index]
        index += 1
    return ''


def _option(source: str, key: str) -> str:
    match = re.search(r"\b" + key + r"\s+'((?:''|\\.|[^'])*)'", source, re.IGNORECASE | re.DOTALL)
    if not match:
        return ''
    return match.group(1).replace("''", "'").replace("\\'", "'")


def _normalize_table(name: str, database: str) -> str:
    pieces = [part.strip().strip('`"') for part in re.split(r'\s*\.\s*', name)]
    if len(pieces) == 1 and database:
        pieces.insert(0, database)
    return '.'.join(pieces) if len(pieces) == 2 and all(pieces) else ''


def dictionary_source_table(ddl: str, dictionary_database: str = '') -> str:
    """Return the direct source table, or '' for unsupported/ambiguous sources."""
    source = _clickhouse_source(ddl)
    if not source:
        return ''
    database = _option(source, 'DB') or dictionary_database
    table = _option(source, 'TABLE')
    if table:
        return _normalize_table(table, database)
    query = _option(source, 'QUERY')
    if not query:
        return ''
    match = re.search(r'\bFROM\s+(' + _IDENT + r'(?:\s*\.\s*' + _IDENT + r')?)', query, re.IGNORECASE)
    return _normalize_table(match.group(1), database) if match else ''


def dictionary_definition(ddl: str) -> dict:
    """Extract safe display fields for a dictionary before it is loaded."""
    result = {}
    layout = re.search(r'\bLAYOUT\s*\(\s*([A-Za-z_][\w]*)\s*\(', ddl, re.IGNORECASE)
    if layout:
        result['type'] = layout.group(1)
    lifetime = re.search(r'\bLIFETIME\s*\(\s*MIN\s+(\d+)\s+MAX\s+(\d+)\s*\)',
                         ddl, re.IGNORECASE)
    if lifetime:
        result['lifetime_min'] = int(lifetime.group(1))
        result['lifetime_max'] = int(lifetime.group(2))
    return result
