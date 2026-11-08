# Repository Guidelines

Руководство для контрибьюторов проекта учёта расходов по фурам (Telegram Mini App + бот + PostgreSQL в Google Cloud SQL).

## Структура проекта и организация модулей

- `app/` — Flask-приложение (Mini App и API):
  - `app/__init__.py` — создание приложения, `db.create_all()`, blueprints.
  - `app/config.py` — конфиг из переменных окружения (`DATABASE_URL` / `DB_HOST`+... / SQLite).
  - `app/models.py` — модели: `User`, `Vehicle`, `Expense`, `FuelBarrel`.
  - `app/auth.py` — авторизация по Telegram initData, уровни доступа 1/2/3.
  - `app/routes.py` — API (`/api/...`) и веб-маршруты Mini App (`/`, `/app`, `/static/...`).
  - `app/notifications.py` — отправка уведомлений в Telegram.
  - `app/main.py` — точка входа: веб-сервер + бот в отдельном потоке.
- `bot/bot.py` — Telegram-бот на `pyTelegramBotAPI` (long polling).
- `static/` — файлы Mini App (HTML/CSS/JS).
- `migrations/` — Alembic-миграции.
- `tests/test_app.py` — pytest-тесты на SQLite.

Скрипты эксплуатации:

- `setup_cloud_sql.ps1` — создаёт инстанс Cloud SQL PostgreSQL, базу `cars`, пользователя и сохраняет строку подключения.
- `deploy_render.py` — создаёт/обновляет сервис на Render через API, ставит `DATABASE_URL`, запускает деплой.
- `setup_all.cmd` — одна команда: Cloud SQL + Render + админ.
- `create_admin.py` — создаёт админа в БД (уровень 1/2/3).

## Команды сборки, тестов и запуска

```powershell
python app/main.py                 # запуск веба + бота в одном процессе
pip install -r requirements.txt    # зависимости
python -m pytest tests/ -q        # тесты
.\setup_all.cmd 123456789         # создать БД в Google Cloud и задеплоить на Render
```

Переменные окружения:

```powershell
$env:TELEGRAM_TOKEN="123:ABC"     # токен @BotFather
$env:DATABASE_URL="postgresql://..."  # строка подключения к Cloud SQL
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
- Схема БД меняется через миграцию Alembic (`ALTER TABLE` с проверкой существования колонки), чтобы не сломать существующую базу.
- Номера машин и пробеги — личные данные: не выводить их в логи и консоль.
