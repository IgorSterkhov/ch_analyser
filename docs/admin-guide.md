# Руководство администратора

Это руководство для пользователей с ролью **admin**. Если вы обычный пользователь, см. [Руководство пользователя](user-guide.md).

## Управление подключениями

Администратор может создавать, редактировать и удалять подключения к серверам ClickHouse.

### Добавление подключения

1. Откройте боковую панель «Подключения»
2. Нажмите кнопку «Add» внизу панели
3. Заполните форму:

| Поле | Описание | Пример |
|------|----------|--------|
| Name | Произвольное имя подключения | Production |
| Host | Адрес сервера ClickHouse | clickhouse.example.com |
| Port | Порт (9000 для native, 8443 для HTTPS) | 9000 |
| User | Имя пользователя ClickHouse | default |
| Password | Пароль | |
| Protocol | Протокол: native или http | native |
| Secure | SSL/TLS-соединение | false |

4. Нажмите «Save»

### Редактирование подключения

1. Нажмите кнопку `...` на карточке подключения
2. Выберите «Edit»
3. Измените нужные поля
4. Нажмите «Save»

### Удаление подключения

1. Нажмите кнопку `...` на карточке подключения
2. Выберите «Delete»

Если удаляемое подключение было активным - сессия завершится.

## SSL-подключения

Для подключения через SSL:

1. Установите флаг **Secure** = true при создании подключения
2. Укажите путь к CA-сертификату в файле `.env`:

```
CLICKHOUSE_CA_CERT=/path/to/ca.crt
```

CA-сертификат применяется глобально ко всем подключениям с SSL.

## Управление пользователями

Пользователи приложения настраиваются в файле `.env`. Для каждого пользователя задаются три переменные:

```
APP_USER_1_NAME=admin
APP_USER_1_PASSWORD=secret
APP_USER_1_ROLE=admin

APP_USER_2_NAME=viewer
APP_USER_2_PASSWORD=pass123
APP_USER_2_ROLE=user
```

### Роли

| Роль | Возможности |
|------|-------------|
| admin | Просмотр данных + управление подключениями (добавление, редактирование, удаление) |
| user | Только просмотр данных по существующим подключениям |

### Добавление нового пользователя

Добавьте в `.env` блок с новым номером:

```
APP_USER_3_NAME=analyst
APP_USER_3_PASSWORD=mypass
APP_USER_3_ROLE=user
```

Перезапустите приложение для применения изменений.

## Формат конфигурации (.env)

Все настройки хранятся в файле `.env` в корне проекта. Формат подключений:

```
CLICKHOUSE_CONNECTION_1_NAME=Production
CLICKHOUSE_CONNECTION_1_HOST=clickhouse.example.com
CLICKHOUSE_CONNECTION_1_PORT=9000
CLICKHOUSE_CONNECTION_1_USER=default
CLICKHOUSE_CONNECTION_1_PASSWORD=
CLICKHOUSE_CONNECTION_1_PROTOCOL=native
CLICKHOUSE_CONNECTION_1_SECURE=false

CLICKHOUSE_CONNECTION_2_NAME=Staging
CLICKHOUSE_CONNECTION_2_HOST=staging-ch.example.com
CLICKHOUSE_CONNECTION_2_PORT=9440
CLICKHOUSE_CONNECTION_2_USER=readonly
CLICKHOUSE_CONNECTION_2_PASSWORD=pass
CLICKHOUSE_CONNECTION_2_PROTOCOL=native
CLICKHOUSE_CONNECTION_2_SECURE=true
```

Нумерация подключений (`_1_`, `_2_`, ...) — автоматическая. При удалении подключения через интерфейс нумерация пересчитывается.
