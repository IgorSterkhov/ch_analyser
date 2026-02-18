# ClickHouse Analyser

Инструмент для анализа хранилища ClickHouse: размеры таблиц, детализация по колонкам, история запросов, информация о дисках. Веб-интерфейс (NiceGUI) и десктопный интерфейс (Tkinter).

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Веб-интерфейс (http://localhost:8080)
python run_web.py

# Десктопный интерфейс
python run_desktop.py
```

Для тестового ClickHouse: `docker compose up -d`

## Документация

Подробная документация в папке [docs/](docs/index.md):

- [Руководство пользователя](docs/user-guide.md)
- [Руководство администратора](docs/admin-guide.md)
- [Архитектура](docs/architecture.md)
- [Разработка и деплой](docs/development.md)
