# Разработка и деплой

## Установка

```bash
git clone <repository-url>
cd ch_analyser
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Зависимости

- `nicegui` - веб-интерфейс
- `clickhouse-driver` - нативный протокол ClickHouse (порт 9000)
- `clickhouse-connect` - HTTP-протокол ClickHouse
- `python-dotenv` - чтение конфигурации из `.env`
- `sqlparse` - форматирование SQL-запросов
- `pytest` - тестирование

## Запуск

### Веб-интерфейс (NiceGUI, порт 8080)

```bash
python run_web.py
```

### Десктопный интерфейс (Tkinter)

```bash
python run_desktop.py
```

## Тестовый ClickHouse (Docker)

```bash
docker compose up -d
```

Создаёт базу `test_db` с тремя таблицами (`events`, `users`, `metrics`) и тестовыми данными. Параметры подключения:

- Host: `localhost`
- Port: `9000`
- User: `default`
- Password: *(пусто)*

## Тесты

```bash
# Unit-тесты (без Docker)
pytest tests/ -m 'not integration'

# Все тесты (требуется запущенный ClickHouse)
pytest tests/ -v
```

## Структура проекта

```
ch_analyser/
├── ch_analyser/
│   ├── client.py              # CHClient - обёртка clickhouse-driver
│   ├── config.py              # ConnectionManager - CRUD подключений (.env)
│   ├── services.py            # AnalysisService - все SQL-запросы
│   ├── auth.py                # UserManager - авторизация
│   ├── sql_format.py          # Форматирование SQL с учётом ClickHouse-функций
│   ├── logging_config.py      # Настройка логирования
│   ├── web/
│   │   ├── app.py             # Bootstrap NiceGUI
│   │   ├── state.py           # Глобальное состояние
│   │   ├── auth_helpers.py    # Хелперы авторизации для веба
│   │   ├── pages/
│   │   │   ├── login.py       # Страница входа
│   │   │   └── main.py        # Основной layout
│   │   └── components/
│   │       ├── header.py      # Шапка приложения
│   │       ├── connection_dialog.py  # Диалог подключения
│   │       └── docs_viewer.py # Просмотрщик документации
│   └── desktop/
│       ├── app.py             # Tkinter приложение
│       ├── frames/            # connections, tables, columns
│       └── widgets/           # connection_dialog
├── docs/                      # Документация
├── tests/                     # Тесты
├── docker/init/               # SQL-инициализация тестовых данных
├── run_web.py                 # Точка входа: веб
├── run_desktop.py             # Точка входа: десктоп
├── requirements.txt
└── docker-compose.yml
```

## Конфигурация (.env)

Пример полного файла:

```env
# Пользователи
APP_USER_1_NAME=admin
APP_USER_1_PASSWORD=admin
APP_USER_1_ROLE=admin

APP_USER_2_NAME=viewer
APP_USER_2_PASSWORD=viewer
APP_USER_2_ROLE=user

# Подключения
CLICKHOUSE_CONNECTION_1_NAME=Local
CLICKHOUSE_CONNECTION_1_HOST=localhost
CLICKHOUSE_CONNECTION_1_PORT=9000
CLICKHOUSE_CONNECTION_1_USER=default
CLICKHOUSE_CONNECTION_1_PASSWORD=
CLICKHOUSE_CONNECTION_1_PROTOCOL=native
CLICKHOUSE_CONNECTION_1_SECURE=false

# SSL (опционально)
CLICKHOUSE_CA_CERT=/path/to/ca.crt
```
