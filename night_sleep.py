# -*- coding: utf-8 -*-
"""Ночная пауза сервиса на Render: suspend/resume через API Render.

Скрипт вызывается из GitHub Actions (см. .github/workflows/night-sleep.yml):
по киевскому времени решает, пора ли усыпить сервис или разбудить его.

Команды:
    python night_sleep.py suspend   # усыпить сервис (ночная пауза)
    python night_sleep.py resume    # разбудить сервис
    python night_sleep.py wait_until_morning  # дождаться 05:00 и разбудить
    python night_sleep.py status    # показать состояние (без секретов)

Ключ берётся из переменной окружения RENDER_API_KEY (в GitHub Actions это
секрет репозитория) или из файла render_key.txt - для локального запуска.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://api.render.com/v1"
ROOT = Path(__file__).resolve().parent

# ID веб-сервиса car-tracker-test на Render.
SERVICE_ID = os.getenv("RENDER_SERVICE_ID", "srv-dboda0egekts73eafuc0")
# Сервис, за которым следим (нужен, чтобы найти его по имени при смене ID).
SERVICE_NAME = "car-tracker-test"
# Публичный репозиторий: HEAD ветки test узнаём без токена.
GITHUB_REPO = "doxoni/car-tracker-test"
GITHUB_BRANCH = "test"
# Адрес health check - по нему проверяем, что сервис проснулся.
HEALTH_URL = os.getenv(
    "HEALTH_URL", "https://car-tracker-test.onrender.com/api/health"
)

# Часовой пояс ночной паузы (Киев).
TZ = ZoneInfo(os.getenv("NIGHT_TZ", "Europe/Kyiv"))
NIGHT_START_HOUR = int(os.getenv("NIGHT_START_HOUR", "2"))
NIGHT_END_HOUR = int(os.getenv("NIGHT_END_HOUR", "5"))


# ---------- Вспомогательные функции ----------


def read_key() -> str:
    """Ключ Render API: из окружения или из файла render_key.txt."""
    key = (os.getenv("RENDER_API_KEY") or "").strip()
    if key:
        return key
    key_file = ROOT / "render_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


def api(method: str, path: str, key: str, payload=None):
    """Запрос к Render API. Возвращает (код, разобранный JSON)."""
    url = f"{API}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("Accept", "application/json")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body) if body else {}
        except ValueError:
            parsed = {"error": body.decode("utf-8", "replace")[:300]}
        return exc.code, parsed


def local_now() -> datetime:
    """Текущее время по Киеву."""
    return datetime.now(TZ)


def is_night(now: datetime) -> bool:
    """Сейчас ночное окно по киевскому времени."""
    hour = now.hour
    if NIGHT_START_HOUR <= NIGHT_END_HOUR:
        return NIGHT_START_HOUR <= hour < NIGHT_END_HOUR
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def github_head_commit() -> str:
    """HEAD ветки test в GitHub (публичный API, без токена)."""
    url = (
        f"https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"
    )
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read()).get("sha", "")
    except Exception:
        return ""


def last_deploy(key: str) -> dict:
    """Последний деплой сервиса (пустой словарь, если деплоев нет)."""
    code, data = api("GET", f"/services/{SERVICE_ID}/deploys?limit=1", key)
    if code >= 400 or not isinstance(data, list) or not data:
        return {}
    item = data[0]
    deploy = item.get("deploy", item)
    return deploy if isinstance(deploy, dict) else {}


def service_state(key: str) -> dict:
    """Состояние сервиса: suspended - усыплен ли он сейчас."""
    code, data = api("GET", f"/services/{SERVICE_ID}", key)
    if code >= 400:
        return {}
    return data if isinstance(data, dict) else {}


# ---------- Команды ----------


def cmd_status(key: str) -> int:
    """Показать состояние сервиса и текущее киевское время."""
    state = service_state(key)
    if not state:
        print("❌ Не удалось получить состояние сервиса")
        return 1
    print(f"Время по Киеву: {local_now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Ночное окно: {NIGHT_START_HOUR:02d}:00-{NIGHT_END_HOUR:02d}:00")
    print(f"Сервис усыплён: {state.get('suspended')}")
    print(f"Ветка: {state.get('branch')}")
    return 0


def cmd_suspend(key: str) -> int:
    """Усыпить сервис на ночь.

    Если в ветке есть незадеплоенный коммит, сервис усыплять нельзя:
    Render не умеет деплоить в усыпленное состояние. Тогда ждём деплоя
    и пробуем снова на следующем запуске workflow.
    """
    state = service_state(key)
    if not state:
        print("❌ Не удалось получить состояние сервиса")
        return 1

    if state.get("suspended") == "suspended":
        print("ℹ️ Сервис уже усыплён - ничего делать не нужно")
        return 0

    deploy = last_deploy(key)
    head = github_head_commit()
    deployed_commit = (deploy.get("commit") or {}).get("id", "")
    status = deploy.get("status", "")

    if status and status != "live":
        print(f"⏳ Последний деплой в статусе {status} - пока не усыпляем сервис")
        return 0
    if head and deployed_commit and head != deployed_commit:
        print(
            "⏳ В ветке есть незадеплоенный коммит - сервис усыплять нельзя "
            "(Render не деплоит в усыпленном состоянии)"
        )
        return 0

    code, data = api("POST", f"/services/{SERVICE_ID}/suspend", key)
    if code >= 400:
        print(f"❌ Не удалось усыпить сервис: {code} {str(data)[:200]}")
        return 1
    print(f"🌙 Сервис усыплён (код {code})")
    return 0


def cmd_resume(key: str) -> int:
    """Разбудить сервис и дождаться, пока он начнёт отвечать."""
    state = service_state(key)
    if not state:
        print("❌ Не удалось получить состояние сервиса")
        return 1

    if state.get("suspended") != "suspended":
        print("ℹ️ Сервис не усыплён - разбужать не нужно")
    else:
        code, data = api("POST", f"/services/{SERVICE_ID}/resume", key)
        if code >= 400:
            print(f"❌ Не удалось разбудить сервис: {code} {str(data)[:200]}")
            return 1
        print(f"☀️ Сервис разбужен (код {code})")

    # Ждём живости: после resume холодный старт занимает до минуты.
    for attempt in range(1, 21):
        try:
            request = urllib.request.Request(HEALTH_URL, method="GET")
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status == 200:
                    print(f"✅ Сервис отвечает (попытка {attempt})")
                    return 0
        except Exception:
            pass
        time.sleep(10)
    print("⚠️ Сервис пока не отвечает - он проснётся с задержкой")
    return 0


def cmd_wait_until_morning(key: str) -> int:
    """Дождаться конца ночного окна и разбудить сервис.

    Вызывается сразу после suspend в том же запуске workflow. Смысл:
    запланированные запуски GitHub Actions в этом репозитории идут с
    большими задержками, поэтому полагаться только на отдельный запуск
    в 05:00 рискованно. Здесь ожидание происходит внутри того же
    процесса, и сервис будит именно тот запуск, который его усыпил.
    """
    state = service_state(key)
    if state.get("suspended") != "suspended":
        print("ℹ️ Сервис не усыплён - ждать нечего")
        return 0
    while True:
        now = local_now()
        if now.hour >= NIGHT_END_HOUR:
            break
        # Просыпаемся не позже чем за минуту до конца окна.
        minutes_left = (
            NIGHT_END_HOUR * 60 - now.hour * 60 - now.minute
        )
        wait_seconds = max(30, min(600, minutes_left * 60))
        print(
            f"⏳ Сейчас {now.strftime('%H:%M:%S')}, ждём {wait_seconds} с "
            f"до {NIGHT_END_HOUR:02d}:00 по Киеву"
        )
        time.sleep(wait_seconds)
    print(f"☀️ Наступило {NIGHT_END_HOUR:02d}:00 по Киеву - будим сервис")
    return cmd_resume(key)


def main() -> int:
    """Точка входа: команда из аргументов."""
    command = (sys.argv[1] if len(sys.argv) > 1 else "status").strip()
    key = read_key()
    if not key:
        print("❌ Нет ключа Render API (RENDER_API_KEY или render_key.txt)")
        return 1

    if command == "suspend":
        return cmd_suspend(key)
    if command == "resume":
        return cmd_resume(key)
    if command == "wait_until_morning":
        return cmd_wait_until_morning(key)
    if command == "status":
        return cmd_status(key)
    print("❌ Неизвестная команда. Доступны: suspend, resume, wait_until_morning, status")
    return 1


if __name__ == "__main__":
    sys.exit(main())
