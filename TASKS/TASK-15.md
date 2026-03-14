# TASK-15: Поддержка URL-параметров фильтрации в qmon

## Контекст

ch_analyser встраивает qmon через iframe на вкладке "QMON". Необходимо передавать фильтр по серверу через URL, например:

```
http://10.172.253.73/qmon?include=C13-1
```

Сейчас это не работает по двум причинам:
1. **Nginx**: запрос с query params (`?include=...`) возвращает 503 — не настроен SPA-роутинг
2. **Фронтенд**: параметры читаются из `localStorage`, а не из URL

Бэкенд менять **не нужно** — WebSocket endpoint (`/ws`) уже парсит `include`/`exclude` из query string (`WSPool.from_request`).

---

## Часть 1: Nginx — SPA-роутинг

### Проблема
Запрос `GET /qmon?include=C13-1` возвращает 503. Запрос `GET /qmon` (без параметров) работает.

### Решение
В nginx конфиге для location `/qmon` добавить fallback на `index.html`, чтобы React SPA корректно обрабатывал любые query params:

```nginx
location /qmon {
    alias /var/lib/nginx/static/qmon;
    try_files $uri $uri/ /qmon/index.html;
}
```

Статика деплоится в `/var/lib/nginx/static/qmon` через `init.sh`.

---

## Часть 2: Фронтенд — чтение URL-параметров

### Файл: `app/qmon-front/src/components/ws-cycle/ws-cycle.jsx`

Сейчас (строки 20-23):
```javascript
const include = localStorage.getItem('include')
const exclude = localStorage.getItem('exclude')
const mutations_on = localStorage.getItem('mutations_on')
const frequency = localStorage.getItem('frequency')
```

Нужно заменить на гибридное чтение — URL params приоритетнее, localStorage как fallback:
```javascript
const urlParams = new URLSearchParams(window.location.search);
const include = urlParams.get('include') || localStorage.getItem('include')
const exclude = urlParams.get('exclude') || localStorage.getItem('exclude')
const mutations_on = urlParams.get('mutations_on') || localStorage.getItem('mutations_on')
const frequency = urlParams.get('frequency') || localStorage.getItem('frequency')
```

### Обратная совместимость
- Если URL без параметров (обычное открытие) — работает как раньше через localStorage
- Если URL с параметрами (iframe из ch_analyser) — используются URL params
- Закомментированный код в строках 18-19 можно удалить

### Файл: `app/qmon-front/src/utils/parameters.js` (опционально)
Закомментированный код URL-параметров (строки 7-15) можно оставить как есть — он отвечает за запись параметров в URL при изменении фильтров пользователем, для iframe это не нужно.

---

## Параметры

| Параметр | Формат | Пример | Описание |
|----------|--------|--------|----------|
| `include` | через запятую | `clh2,clh4` | ID серверов для показа |
| `exclude` | через запятую | `clh4-dp` | ID серверов для исключения |
| `mutations_on` | `true` / пусто | `true` | Показывать мутации |

ch_analyser передаёт только `include` с одним сервером, например `?include=C13-1`.

---

## После выполнения

После деплоя этих изменений, в ch_analyser будет включена передача параметра `include` в iframe URL (код уже готов, временно отключен).
