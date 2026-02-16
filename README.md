# ClickHouse Analyser

Приложение для анализа данных ClickHouse с двумя интерфейсами — веб (NiceGUI) и десктопный (Tkinter).

## Возможности

- **Управление подключениями** — добавление, редактирование, удаление подключений к ClickHouse. Настройки сохраняются в `.env` файл.
- **Анализ таблиц** — список всех таблиц базы данных с размерами, временем последнего SELECT и INSERT запроса. Сортировка по размеру, пагинация.
- **Анализ колонок** — детальная информация по каждой колонке таблицы: тип данных, кодек сжатия, размер на диске. Сортировка по размеру.

## Технологии

- Python 3.8+
- [NiceGUI](https://nicegui.io/) — веб-интерфейс
- Tkinter — десктопный интерфейс
- [clickhouse-driver](https://github.com/mymarilyn/clickhouse-driver) — подключение к ClickHouse (native протокол)
- python-dotenv — хранение конфигурации

## Быстрый старт

### 1. Установка зависимостей

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Запуск тестового ClickHouse (Docker)

```bash
docker compose up -d
```

Будет создана база `test_db` с тремя таблицами (`events`, `users`, `metrics`) и тестовыми данными.

### 3. Запуск

**Веб-интерфейс:**
```bash
python run_web.py
```
Откройте http://localhost:8080

**Десктопный интерфейс:**
```bash
python run_desktop.py
```

### 4. Подключение

Параметры для локального ClickHouse:
- Host: `localhost`
- Port: `9000`
- User: `default`
- Password: *(пусто)*
- Database: `test_db`

## Структура проекта

```
ch_analyser/
├── ch_analyser/
│   ├── config.py          # ConnectionConfig, ConnectionManager (.env CRUD)
│   ├── client.py          # CHClient — обёртка над clickhouse-driver
│   ├── services.py        # AnalysisService — SQL-запросы и бизнес-логика
│   ├── logging_config.py  # Настройка логирования
│   ├── web/               # NiceGUI веб-интерфейс
│   │   ├── app.py
│   │   ├── pages/         # Страницы: connections, tables, columns
│   │   └── components/    # Переиспользуемые компоненты: header, dialog
│   └── desktop/           # Tkinter десктопный интерфейс
│       ├── app.py
│       ├── frames/        # Фреймы: connections, tables, columns
│       └── widgets/       # Виджеты: connection_dialog
├── docker-compose.yml     # Локальный ClickHouse для разработки
├── docker/init/           # SQL-скрипт инициализации тестовых данных
├── tests/                 # Unit и интеграционные тесты
├── run_web.py             # Точка входа — веб
├── run_desktop.py         # Точка входа — десктоп
└── requirements.txt
```

## Тесты

```bash
# Unit-тесты (без Docker)
pytest tests/ -m 'not integration'

# Все тесты (требуется запущенный ClickHouse)
pytest tests/ -v
```

## Формат .env

```
CLICKHOUSE_CONNECTION_1_NAME=Production
CLICKHOUSE_CONNECTION_1_HOST=localhost
CLICKHOUSE_CONNECTION_1_PORT=9000
CLICKHOUSE_CONNECTION_1_USER=default
CLICKHOUSE_CONNECTION_1_PASSWORD=
CLICKHOUSE_CONNECTION_1_DATABASE=test_db
```
