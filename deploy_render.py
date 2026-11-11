# -*- coding: utf-8 -*-
"""Деплой car-tracker на Render через Render API.

Что делает:
  1. Берёт DATABASE_URL из .db_connection.txt (создаётся скриптом
     setup_db.ps1).
  2. Создаёт сервис на Render из репозитория doxoni/car-tracker-test
     (ветка test) или обновляет существующий.
  3. Ставит переменные окружения и запускает деплой.
  4. Создаёт админа в БД (уровень 3), если передан TELEGRAM_ID.

Запуск (PowerShell, из папки проекта):
    $env:RENDER_API_KEY = "rnd_..."
    python deploy_render.py --telegram-id 123456789

Ключ Render можно положить в файл render_key.txt (в .gitignore) - тогда
скрипт возьмёт его сам:

    python deploy_render.py --telegram-id 123456789
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Консоль Windows по умолчанию cp1251 - эмодзи в ней не печатаются.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

import requests

API = "https://api.render.com/v1"
ROOT = Path(__file__).resolve().parent

SERVICE_NAME = "car-tracker-test"
SERVICE_REPO = "https://github.com/doxoni/car-tracker-test"
SERVICE_BRANCH = "test"
SERVICE_PLAN = "free"

# Команда запуска. -c gunicorn.conf.py подключает хук post_worker_init:
# бот поднимается в том процессе, который обслуживает запросы.
START_COMMAND = (
    "gunicorn -c gunicorn.conf.py --workers 1 --threads 4 --timeout 120 "
    "--bind 0.0.0.0:$PORT wsgi:app"
)


def fail(message: str):
    """Остановить работу с понятным сообщением."""
    print(f"ОШИБКА: {message}")
    sys.exit(1)


def read_key() -> str:
    """Ключ Render API: из переменной окружения или из render_key.txt.

    Если ключа нет - возвращается пустая строка: скрипт тогда не падает,
    а печатает ручной порядок действий (см. print_manual_steps).
    """
    key = (os.getenv("RENDER_API_KEY") or "").strip()
    if key:
        return key
    key_file = ROOT / "render_key.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
    return key


def read_connection() -> str:
    """Строка подключения к БД из файла.

    Файл общий для всех провайдеров (Google Cloud SQL, Neon и т.п.) -
    его кладёт скрипт настройки БД. Старое имя .cloudsql_connection.txt
    тоже поддерживается, чтобы ничего не ломалось.
    """
    for name in (".db_connection.txt", ".cloudsql_connection.txt"):
        conn_file = ROOT / name
        if not conn_file.exists():
            continue
        # Файл мог быть записан в Windows PowerShell 5.1 - там UTF-8 с BOM,
        # и в начале первой строки остаётся невидимый символ.
        text = conn_file.read_text(encoding="utf-8-sig")
        for line in text.splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip()
                if url:
                    return normalize_url(url)
    fail(
        "Нет файла .db_connection.txt с подключением к БД.\n"
        "  Сначала создай базу: powershell -ExecutionPolicy Bypass -File setup_db.ps1"
    )


def normalize_url(url: str) -> str:
    """Привести строку подключения к виду, который понимает SQLAlchemy.

    Некоторые хостинги отдают схему postgres:// - SQLAlchemy 2.x ждёт
    postgresql://.
    """
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def read_render_env() -> dict:
    """Дополнительные переменные окружения для Render.

    Сначала берёмся из render_env.txt (KEY=VALUE), потом - из локального
    .env проекта. Значения нигде не печатаются.

    TELEGRAM_TOKEN из .env не берём: файл .env может содержать старый
    отозванный токен, и тогда деплой затрёт им рабочий токен, заданный
    в панели Render, - бот перестанет отвечать. Токен бота ставится
    только из render_env.txt (см. tools/set_bot_token.py).
    """
    values = {}
    env_file = ROOT / "render_env.txt"
    if env_file.exists():
        # utf-8-sig: файл мог быть сохранён в PowerShell 5.1 (UTF-8 с BOM).
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()

    # Локальный .env - чтобы настройки не пришлось вписывать дважды.
    dotenv_file = ROOT / ".env"
    if dotenv_file.exists():
        for line in dotenv_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "TELEGRAM_TOKEN":
                # Токен бота - только из render_env.txt, см. docstring.
                continue
            if value and key not in values:
                values[key] = value

    # На Render нужны только эти переменные - лишнее (SECRET_KEY и т.п.) не передаём.
    allowed = (
        "TELEGRAM_TOKEN",
        "ADMIN_TELEGRAM_ID",
        "WHITELISTED_TELEGRAM_IDS",
        "OPEN_ACCESS",
        "TELEGRAM_MODE",
        "TELEGRAM_WEBHOOK_SECRET",
    )
    return {k: v for k, v in values.items() if k in allowed}


def read_uptime_key() -> str:
    """Ключ UptimeRobot API.

    Порядок: переменная окружения, потом файл uptime_key.txt (в
    .gitignore), потом render_env.txt. Пустая строка - ключа нет.
    """
    key = (os.getenv("UPTIME_API_KEY") or "").strip()
    if key:
        return key

    key_file = ROOT / "uptime_key.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8-sig").strip()
        if key:
            return key

    env_file = ROOT / "render_env.txt"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("UPTIME_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def ensure_webhook_secret(values: dict) -> dict:
    """Задать режим бота и секрет вебхука.

    Секрет нужен, чтобы чужие запросы не притворялись сообщениями от
    Telegram. Если его нет - генерируем и сохраняем в render_env.txt
    (файл в .gitignore, в Git секрет не попадает). Секрет должен быть
    один и тот же при каждом деплое, иначе Telegram перестанет
    доставлять обновления.
    """
    import secrets

    values = dict(values)
    values.setdefault("TELEGRAM_MODE", "webhook")

    secret = (values.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not secret:
        secret = secrets.token_urlsafe(24)
        env_file = ROOT / "render_env.txt"
        with env_file.open("a", encoding="utf-8") as file:
            file.write(f"\n# Секрет вебхука Telegram (создан автоматически).\n")
            file.write(f"TELEGRAM_WEBHOOK_SECRET={secret}\n")
        print("  Секрет вебхука сгенерирован и сохранён в render_env.txt")
    values["TELEGRAM_WEBHOOK_SECRET"] = secret
    return values


def check_token(token: str) -> bool:
    """Проверить токен бота у Telegram (getMe).

    Нужно, чтобы деплой не поставил сервису заведомо нерабочий токен:
    с ним бот не отвечает, а Mini App отдаёт 401 на все запросы.
    """
    if not token:
        return False
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=30
        )
        data = response.json()
    except Exception:  # noqa: BLE001 - сеть может быть недоступна
        return False
    return bool(data.get("ok"))


def api(method: str, path: str, key: str, payload=None):
    """Запрос к Render API с обработкой ошибок."""
    url = f"{API}{path}"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.request(method, url, headers=headers, json=payload, timeout=60)
    if response.status_code >= 400:
        fail(f"Render API {method} {path} -> {response.status_code}: {response.text[:600]}")
    if not response.content:
        return {}
    return response.json()


def find_owner(key: str) -> str:
    """ID владельца аккаунта Render.

    API отдаёт владельцев в виде [{"cursor": ..., "owner": {...}}],
    поэтому ID берём из вложенного объекта "owner".
    """
    owners = api("GET", "/owners", key)
    if not owners:
        fail("Не найден владелец аккаунта Render")
    first = owners[0]
    owner = first.get("owner", first)
    owner_id = owner.get("id")
    if not owner_id:
        fail("У ответа Render нет ID владельца")
    return owner_id


def find_service(owner_id: str, key: str):
    """Сервис по имени или None."""
    services = api("GET", f"/services?ownerId={owner_id}", key)
    for item in services:
        service = item.get("service", item)
        if service.get("name") == SERVICE_NAME:
            return service
    return None


def create_service(owner_id: str, key: str) -> dict:
    """Создать веб-сервис на Render.

    Формат тела - по документации Render API: поля type/name/ownerId лежат
    на верхнем уровне, а plan, runtime и команды сборки - внутри
    serviceDetails. Если plan положить наверх, Render отвечает 402
    ("Payment information is required") - как будто нужен платный план.
    """
    payload = {
        "type": "web_service",
        "name": SERVICE_NAME,
        "ownerId": owner_id,
        "repo": SERVICE_REPO,
        "branch": SERVICE_BRANCH,
        "autoDeployTrigger": "commit",
        "serviceDetails": {
            "runtime": "python",
            "plan": SERVICE_PLAN,
            "numInstances": 1,
            "region": "frankfurt",
            "healthCheckPath": "/api/health",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": START_COMMAND,
            },
        },
    }
    result = api("POST", "/services", key, payload)
    return result.get("service", result)


def update_start_command(service_id: str, owner_id: str, key: str) -> bool:
    """Обновить команду запуска существующего сервиса.

    Формат тот же, что и при создании: plan лежит внутри serviceDetails,
    иначе Render отвечает 402 ("Payment information is required").
    Render принимает обновление только через PATCH - на PUT отвечает 405.
    Ошибка здесь не критична: gunicorn и сам подхватывает gunicorn.conf.py
    из рабочей папки, поэтому при неудаче просто пишем предупреждение.
    """
    try:
        details = api("GET", f"/services/{service_id}", key)
        details = details.get("service", details)
        service_details = details.get("serviceDetails") or {}
        env_details = service_details.get("envSpecificDetails") or {}
        if env_details.get("startCommand") == START_COMMAND:
            return True
        payload = {
            "serviceDetails": {
                "runtime": service_details.get("runtime") or "python",
                "plan": service_details.get("plan") or SERVICE_PLAN,
                "numInstances": service_details.get("numInstances") or 1,
                "region": service_details.get("region") or "frankfurt",
                "healthCheckPath": service_details.get("healthCheckPath")
                or "/api/health",
                "envSpecificDetails": {
                    "buildCommand": env_details.get("buildCommand")
                    or "pip install -r requirements.txt",
                    "startCommand": START_COMMAND,
                },
            },
        }
        api("PATCH", f"/services/{service_id}", key, payload)
        return True
    except SystemExit:
        print("⚠️  Команду запуска обновить не удалось - деплой продолжим.")
        return False
    except Exception as exc:
        print(f"⚠️  Не удалось обновить команду запуска: {exc}")
        return False


def get_env_vars(service_id: str, key: str) -> dict:
    """Текущие переменные окружения сервиса (ключ -> значение).

    Нужно перед обновлением: PUT /env-vars в Render ЗАМЕНЯЕТ весь список
    переменных, а не дополняет его. Без этого шага деплой стирал бы
    всё, что задано вручную в панели Render.
    """
    result = {}
    try:
        data = api("GET", f"/services/{service_id}/env-vars", key)
    except SystemExit:
        return result
    items = data if isinstance(data, list) else data.get("envVar", [])
    for item in items:
        env = item.get("envVar") if isinstance(item, dict) else None
        if not isinstance(env, dict):
            continue
        env_key = env.get("key")
        if env_key:
            result[env_key] = env.get("value") or ""
    return result


def set_env(service_id: str, key: str, values: dict):
    """Обновить переменные окружения сервиса.

    Render принимает список переменных одним запросом PUT, причём
    ЗАМЕНЯЕТ весь список - переменные, которых нет в payload, пропадают.
    Поэтому сначала читаем текущие переменные и накладываем новые
    поверх них: всё, что задано вручную в панели Render, сохраняется.

    Значения помечаются как secret - в ответе API они не возвращаются.
    """
    merged = get_env_vars(service_id, key)
    merged.update(values)
    payload = [
        {"key": env_key, "value": env_value, "type": "secret"}
        for env_key, env_value in merged.items()
    ]
    api("PUT", f"/services/{service_id}/env-vars", key, payload)
    for env_key in values:
        print(f"  env: {env_key} = OK")


def trigger_deploy(service_id: str, key: str):
    """Запустить деплой."""
    api("POST", f"/services/{service_id}/deploys", key, {"clearCache": "do_not_clear"})
    print("  deploy: запущен")


def wait_for_deploy(service_id: str, key: str, timeout: int = 900):
    """Дождаться успешного деплоя."""
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        deploys = api("GET", f"/services/{service_id}/deploys?limit=1", key)
        if deploys:
            deploy = deploys[0]["deploy"]
            status = deploy.get("status")
            if status != last_status:
                print(f"  status: {status}")
                last_status = status
            if status == "live":
                print("  сервис запущен")
                return True
            if status == "build_failed" or status == "update_failed":
                fail(f"Деплой провалился ({status}). Логи: {deploy.get('deployLogUrl') or 'в дашборде Render'}")
        time.sleep(15)
    print("  деплой ещё выполняется, проверь дашборд Render")
    return False


def print_manual_steps(extra: dict):
    """Печатает порядок действий, если ключа Render API нет.

    Ключ можно и не заводить: сервис создаётся вручную через Blueprint
    (Render сам прочитает render.yaml), а DATABASE_URL вставляется руками.
    Секреты в консоль не выводятся - только названия файлов, откуда их взять.
    """
    print("")
    print("=" * 60)
    print("КЛЮЧА RENDER API НЕТ - ДЕПЛОЙ ВРУЧНУЮ (5 минут)")
    print("=" * 60)
    print("")
    print("1. Открой https://dashboard.render.com и залогинься.")
    print("2. New -> Blueprint -> выбери репозиторий doxoni/car-tracker-test,")
    print("   ветку test. Render сам прочитает render.yaml из репозитория.")
    print("3. Когда попросит значения переменных, вставь:")
    print("")
    print("   DATABASE_URL - скопируй строку DATABASE_URL=... из файла")
    print("                 .db_connection.txt (лежит в папке проекта)")
    if extra:
        print("   TELEGRAM_TOKEN и прочее - скопируй из файла render_env.txt")
    print("")
    print("   Остальные переменные render.yaml заполнятся сами.")
    print("")
    print("4. Нажми Create. Через пару минут сервис поднимется.")
    print("5. Проверь: https://car-tracker-test.onrender.com/api/health")
    print("")
    print("Чтобы в следующий раз всё делалось автоматически, положи ключ")
    print("Render в файл render_key.txt и запусти setup_all.cmd ещё раз.")
    print("=" * 60)


def create_admin(database_url: str, telegram_id: int, name: str):
    """Создать админа (уровень 3) в базе Cloud SQL."""
    import subprocess

    os.environ["DATABASE_URL"] = database_url
    print("")
    print("=== Создаю админа ===")
    result = subprocess.run(
        [sys.executable, str(ROOT / "create_admin.py"), str(telegram_id), name, "3"],
        cwd=str(ROOT),
        env=os.environ,
    )
    if result.returncode != 0:
        print("Не удалось создать админа (см. вывод выше)")


def main():
    parser = argparse.ArgumentParser(description="Деплой car-tracker на Render")
    parser.add_argument("--telegram-id", type=int, default=0, help="Telegram ID админа (уровень 3)")
    parser.add_argument("--name", default="Koval", help="Имя админа")
    parser.add_argument("--no-wait", action="store_true", help="Не ждать завершения деплоя")
    args = parser.parse_args()

    database_url = read_connection()
    extra = read_render_env()

    key = read_key()
    if not key:
        print_manual_steps(extra)
        # Админа в базе всё равно создаём - БД уже доступна.
        if args.telegram_id:
            create_admin(database_url, args.telegram_id, args.name)
        return

    print("=== Render deploy ===")
    owner_id = find_owner(key)
    service = find_service(owner_id, key)

    if service:
        print(f"Сервис {SERVICE_NAME} найден: {service['id']}")
        service_id = service["id"]
        update_start_command(service_id, owner_id, key)
    else:
        print(f"Сервис {SERVICE_NAME} не найден - создаю")
        service = create_service(owner_id, key)
        service_id = service["id"]
        print(f"Создан: {service_id}")

    # APP_URL нужен боту: без него кнопка Mini App ведёт в никуда.
    # Если значение задано в render_env.txt - не перетираем.
    if "APP_URL" not in extra:
        details = api("GET", f"/services/{service_id}", key)
        details = details.get("service", details)
        host = (
            (details.get("serviceDetails") or {}).get("url")
            or f"https://{SERVICE_NAME}.onrender.com"
        )
        extra = dict(extra)
        extra["APP_URL"] = host

    values = {
        "DATABASE_URL": database_url,
        "PGSSLMODE": "require",
        "PYTHON_VERSION": "3.12.0",
        "BOT_ENABLED": "1",
    }
    values.update(extra)
    # Бот в режиме webhook + секрет вебхука.
    values = ensure_webhook_secret(values)
    # Ключ UptimeRobot: контейнер сам управляет паузой монитора ночью.
    uptime_key = read_uptime_key()
    if uptime_key:
        values["UPTIME_API_KEY"] = uptime_key
    # Адрес вебхука: Telegram шлёт обновления прямо сюда.
    values.setdefault(
        "TELEGRAM_WEBHOOK_URL", "https://car-tracker-test.onrender.com/telegram/webhook"
    )

    # Токен бота проверяем до постановки: нерабочий токен ломает и бота,
    # и Mini App (подпись initData не сойдётся). Если токен не проходит
    # проверку - не ставим его и предупреждаем: переменная на сервере
    # останется прежней (set_env сохраняет те, которых нет в values).
    token = values.get("TELEGRAM_TOKEN")
    if token:
        if check_token(token):
            print("  Токен бота рабочий.")
        else:
            print("⚠️  Токен бота не проходит проверку Telegram - не ставлю его.")
            print("   Возьми новый токен у @BotFather и запусти set_bot_token.cmd")
            values.pop("TELEGRAM_TOKEN")
    set_env(service_id, key, values)

    if "TELEGRAM_TOKEN" not in values:
        print("")
        print("⚠️  TELEGRAM_TOKEN не задан - бот на Render не ответит.")
        print("   Возьми токен у @BotFather и запусти set_bot_token.cmd.")

    trigger_deploy(service_id, key)

    if not args.no_wait:
        wait_for_deploy(service_id, key)

    details = api("GET", f"/services/{service_id}", key)
    details = details.get("service", details)
    host = (details.get("serviceDetails") or {}).get("url") or f"https://{SERVICE_NAME}.onrender.com"
    print("")
    print(f"URL: {host}")
    print(f"Health: {host}/api/health")

    if args.telegram_id:
        create_admin(database_url, args.telegram_id, args.name)


if __name__ == "__main__":
    main()
