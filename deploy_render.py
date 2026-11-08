# -*- coding: utf-8 -*-
"""Деплой car-tracker на Render через Render API.

Что делает:
  1. Берёт DATABASE_URL из .cloudsql_connection.txt (создаётся скриптом
     setup_cloud_sql.ps1).
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

import requests

API = "https://api.render.com/v1"
ROOT = Path(__file__).resolve().parent

SERVICE_NAME = "car-tracker-test"
SERVICE_REPO = "https://github.com/doxoni/car-tracker-test"
SERVICE_BRANCH = "test"
SERVICE_PLAN = "free"


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
    """Строка подключения к Cloud SQL из .cloudsql_connection.txt."""
    conn_file = ROOT / ".cloudsql_connection.txt"
    if not conn_file.exists():
        fail(
            "Нет файла .cloudsql_connection.txt.\n"
            "  Сначала запусти: powershell -ExecutionPolicy Bypass -File setup_cloud_sql.ps1"
        )
    for line in conn_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    fail("В .cloudsql_connection.txt нет строки DATABASE_URL")


def read_render_env() -> dict:
    """Дополнительные переменные окружения для Render.

    Сначала берёмся из render_env.txt (KEY=VALUE), потом - из локального
    .env проекта. Значения нигде не печатаются.
    """
    values = {}
    env_file = ROOT / "render_env.txt"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()

    # Локальный .env - чтобы токен бота не пришлось вписывать дважды.
    dotenv_file = ROOT / ".env"
    if dotenv_file.exists():
        for line in dotenv_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value and key not in values:
                values[key] = value

    # На Render нужны только эти переменные - лишнее (SECRET_KEY и т.п.) не передаём.
    allowed = ("TELEGRAM_TOKEN", "ADMIN_TELEGRAM_ID", "WHITELISTED_TELEGRAM_IDS")
    return {k: v for k, v in values.items() if k in allowed}


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
    """ID владельца аккаунта Render."""
    owners = api("GET", "/owners", key)
    if not owners:
        fail("Не найден владелец аккаунта Render")
    return owners[0]["id"]


def find_service(owner_id: str, key: str):
    """Сервис по имени или None."""
    services = api("GET", f"/services?ownerId={owner_id}", key)
    for service in services:
        if service["name"] == SERVICE_NAME:
            return service
    return None


def create_service(owner_id: str, key: str, env_vars: list) -> dict:
    """Создать веб-сервис на Render."""
    payload = {
        "service": {
            "name": SERVICE_NAME,
            "ownerId": owner_id,
            "repo": SERVICE_REPO,
            "branch": SERVICE_BRANCH,
            "type": "web",
            "runtime": "python",
            "plan": SERVICE_PLAN,
            "autoDeployTrigger": "commit",
            "healthCheckPath": "/api/health",
            "envVars": env_vars,
        }
    }
    return api("POST", "/services", key, payload)["service"]


def set_env(service_id: str, key: str, values: dict):
    """Обновить переменные окружения сервиса."""
    for env_key, env_value in values.items():
        api("PUT", f"/services/{service_id}/env-vars/{env_key}", key, {"value": env_value})
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
    print("                 .cloudsql_connection.txt (лежит в папке проекта)")
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
    else:
        print(f"Сервис {SERVICE_NAME} не найден - создаю")
        env_vars = [
            {"key": "DATABASE_URL", "value": database_url},
            {"key": "PGSSLMODE", "value": "require"},
            {"key": "PYTHON_VERSION", "value": "3.12.0"},
        ]
        for env_key, env_value in extra.items():
            env_vars.append({"key": env_key, "value": env_value})
        service = create_service(owner_id, key, env_vars)
        service_id = service["id"]
        print(f"Создан: {service_id}")

    # APP_URL нужен боту: без него кнопка Mini App ведёт в никуда.
    # Если значение задано в render_env.txt - не перетираем.
    if "APP_URL" not in extra:
        details = api("GET", f"/services/{service_id}", key)["service"]
        host = (details.get("serviceDetails") or {}).get("host") or f"{SERVICE_NAME}.onrender.com"
        extra = dict(extra)
        extra["APP_URL"] = f"https://{host}"

    values = {
        "DATABASE_URL": database_url,
        "PGSSLMODE": "require",
        "PYTHON_VERSION": "3.12.0",
        "BOT_ENABLED": "1",
    }
    values.update(extra)
    set_env(service_id, key, values)

    if "TELEGRAM_TOKEN" not in extra:
        print("")
        print("⚠️  TELEGRAM_TOKEN не найден - бот на Render не запустится.")
        print("   Положи токен в файл render_env.txt (см. render_env.example.txt).")

    trigger_deploy(service_id, key)

    if not args.no_wait:
        wait_for_deploy(service_id, key)

    service = api("GET", f"/services/{service_id}", key)["service"]
    print("")
    print(f"URL: https://{service['serviceDetails']['host']}")
    print(f"Health: https://{service['serviceDetails']['host']}/api/health")

    if args.telegram_id:
        create_admin(database_url, args.telegram_id, args.name)


if __name__ == "__main__":
    main()
