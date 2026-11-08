# Repository Guidelines

Руководство для контрибьюторов проекта учёта расходов по фурам (Telegram Mini App + бот + PostgreSQL в облаке).

## Структура проекта и организация модулей

- `app/` — Flask-приложение (Mini App и API):
  - `app/__init__.py` — создание приложения, blueprints, ожидание готовности БД.
  - `app/db_schema.py` — приведение схемы к актуальной (миграции alembic; при сбое — `db.create_all()`).
  - `app/db_retry.py` — повтор запроса к БД один раз, если база была «спящей».
  - `app/config.py` — конфиг из переменных окружения (`DATABASE_URL` / `DB_HOST`+... / SQLite), размер пула через `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`.
  - `app/models.py` — модели: `User`, `Vehicle`, `Expense`, `FuelBarrel`.
  - `app/auth.py` — авторизация по Telegram initData, уровни доступа 1/2/3.
  - `app/routes.py` — API (`/api/...`) и веб-маршруты Mini App (`/`, `/app`, `/static/...`).
  - `app/notifications.py` — отправка уведомлений в Telegram.
  - `app/main.py` — точка входа: веб-сервер + бот в отдельном потоке.
  - `app/bot_runner.py` — запуск бота в потоке (для gunicorn на Render).
- `bot/bot.py` — Telegram-бот на `python-telegram-bot` (long polling).
- `app/static/` — файлы Mini App (HTML/CSS/JS).
- `migrations/` — Alembic-миграции; `alembic.ini` в корне, адрес БД берётся из `DATABASE_URL`.
- `tests/test_app.py` — pytest-тесты на SQLite.
- `wsgi.py` — точка входа для gunicorn (`wsgi:app`).

Скрипты эксплуатации:

- `setup_db.ps1` — создаёт облачную базу PostgreSQL: Google Cloud SQL, если есть биллинг-аккаунт, иначе Neon (карта не нужна). Сохраняет строку подключения в `.db_connection.txt` и применяет миграции.
- `setup_neon.py` — создаёт проект в Neon через API (нужен ключ в `neon_key.txt`).
- `apply_migrations.py` — применяет миграции alembic к базе из `.db_connection.txt`.
- `deploy_render.py` — создаёт/обновляет сервис на Render через API, ставит `DATABASE_URL`, запускает деплой.
- `setup_all.cmd` — одна команда: база + Render + админ.
- `create_admin.py` — создаёт админа в БД (уровень 1/2/3).

## Команды сборки, тестов и запуска

```powershell
python app/main.py                 # запуск веба + бота в одном процессе
pip install -r requirements.txt    # зависимости
python -m pytest tests/ -q        # тесты
.\setup_all.cmd 123456789         # создать облачную БД и задеплоить на Render
```

Переменные окружения:

```powershell
$env:TELEGRAM_TOKEN="123:ABC"     # токен @BotFather
$env:DATABASE_URL="postgresql://..."  # строка подключения к облачной БД
```

## Стиль кода и соглашения по именам

- Python 3, 4 пробела, `snake_case` для функций и переменных, `UPPER_CASE` для констант (`TELEGRAM_TOKEN`, `SERVICE_NAME`).
- Обязательная шапка-комментарий с `# -*- coding: utf-8 -*-` и русским docstring, где указан запуск.
- Пользовательские строки, ключи JSON и комментарии — на русском; имена полей моделей менять нельзя, это схема БД.
- Секции разделяйте комментариями-баннерами вида `# ---------- Описание ----------`.
- Форматирование: код в стиле `black`, отступы 4, без табов; линтеры в проекте не настроены.

## Тестирование

Автотесты есть: `python -m pytest tests/ -q`. Проверяются health-check, отдача Mini App, 401 без авторизации и работа дашборда под тестовым пользователем.

## Коммиты и Pull Request

Сообщения — короткие, в стиле Imperative Mood: `Добавь историю работ по авто`. В Pull Request указывайте: что изменено, как проверить, какие файлы затронуты. Скриншоты нужны только для изменений UI бота.

## Безопасность и конфигурация

- Токен бота храните только в переменной окружения `TELEGRAM_TOKEN` или в `render_env.txt` (файл в `.gitignore`).
- Render API-ключ — в `render_key.txt` (тоже в `.gitignore`).
- Никогда не коммитьте токены, пароли и рабочую базу (`*.db`).
- Схема БД меняется через миграцию Alembic (`ALTER TABLE` с проверкой существования колонки), чтобы не сломать существующую базу. Новую колонку с `NOT NULL` сначала добавлять со `server_default`, потом заполнять данные, потом значение по умолчанию убирать.
- Ограничения в миграциях называем явно: `batch_alter_table` пересоздаёт таблицу на SQLite и безымянные ограничения туда не переносит.
- Номера машин и пробеги — личные данные: не выводить их в логи и консоль.
