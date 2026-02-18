# Архитектура

## Общая структура

Проект разделён на три слоя:

1. **Ядро** (`ch_analyser/`) - подключение, сервисы, конфигурация, авторизация
2. **Веб-интерфейс** (`ch_analyser/web/`) - NiceGUI (Quasar/Vue.js)
3. **Десктопный интерфейс** (`ch_analyser/desktop/`) - Tkinter

Оба интерфейса используют общий сервисный слой.

## Ключевые компоненты

### CHClient (`client.py`)

Обёртка над `clickhouse-driver`. Метод `execute()` возвращает `list[dict]` — строки как словари с именами колонок в качестве ключей.

### AnalysisService (`services.py`)

Содержит **все** SQL-запросы к ClickHouse. UI-код никогда не пишет SQL напрямую. Методы:

- `get_tables()` - список таблиц с размерами и датами последних запросов
- `get_columns(full_table_name)` - колонки таблицы с типами, кодеками, размерами
- `get_disk_info()` - информация о дисках
- `get_query_history(full_table_name)` - история запросов из `system.query_log`
- `get_query_history_sql(full_table_name)` - SQL-строка запроса истории

### ConnectionManager (`config.py`)

CRUD для подключений. Хранит в `.env` с паттерном `CLICKHOUSE_CONNECTION_{N}_{FIELD}`.

### UserManager (`auth.py`)

Аутентификация по `.env` с паттерном `APP_USER_{N}_{NAME|PASSWORD|ROLE}`.

## Системные таблицы ClickHouse

| Таблица | Использование |
|---------|---------------|
| `system.parts` | Размеры таблиц (`bytes_on_disk`) |
| `system.columns` | Определения колонок, типы, кодеки |
| `system.parts_columns` | Размеры колонок на диске |
| `system.query_log` | История запросов, время последних SELECT/INSERT |
| `system.disks` | Дисковое пространство: total, free, used |

Системные базы (`system`, `INFORMATION_SCHEMA`, `information_schema`) исключены из анализа.

## Паттерны веб-интерфейса

### Перестроение панелей

Функции `_build_*()` и `_load_*()` используют паттерн:
```python
panel.clear()
with panel:
    # рендер содержимого
```

### Состояние

Глобальное состояние (`web/state.py`): `client`, `service`, `conn_manager`, `user_manager`, `active_connection_name`. Не сериализуемые объекты.

### Таблицы

Кастомизация через body-слоты Quasar с JS-событиями (`$parent.$emit`).

### SQL-форматирование (`sql_format.py`)

`format_clickhouse_sql()` — форматирование через `sqlparse` + восстановление camelCase для ClickHouse-функций (`toDate`, `arrayJoin`, `dictGet` и т.д.).

## Conventions

- Новые SQL-запросы — только в `services.py` как методы `AnalysisService`
- `formatReadableSize()` в SQL для человекочитаемых размеров
- Функции перестроения UI: `_build_*()` или `_load_*()`
- Ссылки на панели передаются через параметры функций (без глобального UI-состояния)
