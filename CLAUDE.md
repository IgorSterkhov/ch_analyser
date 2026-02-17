# ClickHouse Analyser — Project Guide

## Overview
A dual-interface (web + desktop) tool for analyzing ClickHouse server storage: table sizes, column details, query history, and disk usage.

## Quick Start
```bash
# Web UI (NiceGUI, port 8080)
python run_web.py

# Desktop UI (Tkinter)
python run_desktop.py
```

## Tech Stack
- **Web UI**: NiceGUI (Quasar/Vue.js under the hood)
- **Desktop UI**: Tkinter
- **ClickHouse driver**: `clickhouse-driver` (native protocol, port 9000)
- **Config**: `.env` file via `python-dotenv`

## Project Structure
```
ch_analyser/
├── client.py          # CHClient — ClickHouse connection wrapper
├── config.py          # ConnectionManager — .env persistence for connections
├── services.py        # AnalysisService — all SQL queries (system tables)
├── auth.py            # UserManager — user auth & roles from .env
├── logging_config.py  # Logging setup
├── web/
│   ├── app.py         # NiceGUI bootstrap
│   ├── state.py       # Global state (client, service, managers)
│   ├── auth_helpers.py
│   ├── pages/
│   │   ├── login.py   # Login page
│   │   └── main.py    # Main layout: Connections | Server Info + Tables + Table Details
│   └── components/
│       ├── header.py
│       └── connection_dialog.py
└── desktop/
    ├── app.py          # Tkinter main app (frame switching)
    ├── frames/         # connections.py, tables.py, columns.py
    └── widgets/        # connection_dialog.py
```

## Key Architecture Decisions
- **Service layer** (`services.py`) contains ALL ClickHouse queries — UI code never writes SQL directly
- **CHClient.execute()** returns `list[dict]` — rows as dictionaries with column names as keys
- System databases (`system`, `INFORMATION_SCHEMA`, `information_schema`) are excluded from analysis
- Web UI uses dynamic panel rebuilding: `panel.clear()` + re-render pattern
- Connection configs stored in `.env` with pattern `CLICKHOUSE_CONNECTION_{N}_{FIELD}`

## ClickHouse System Tables Used
| Table | Purpose |
|-------|---------|
| `system.parts` | Table sizes (bytes_on_disk) |
| `system.columns` | Column definitions, types, codecs |
| `system.parts_columns` | Column-level storage stats |
| `system.query_log` | Query history, last SELECT/INSERT times |
| `system.disks` | Disk space: total, free, used |

## Web UI Layout
```
┌──────────────────────────────────────────────────────┐
│ Header                                                │
├────────────┬─────────────────────────────────────────┤
│            │ [Server Info Bar: name, disk usage, %]   │
│ Connections├──────────────────┬──────────────────────┤
│ (22%)      │ Tables (45%)     │ Table Details (flex)  │
│            │                  │  - Columns tab        │
│            │                  │  - Query History tab  │
└────────────┴──────────────────┴──────────────────────┘
```

## Conventions
- All new ClickHouse queries go into `services.py` as methods on `AnalysisService`
- Use `formatReadableSize()` in SQL for human-readable sizes
- Web UI functions that rebuild panels follow the pattern: `_build_*()` or `_load_*()`
- Panel references are passed through function parameters (no global UI state)
- Russian language in commit messages is acceptable (project originated in Russian)
