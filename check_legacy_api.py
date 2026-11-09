# -*- coding: utf-8 -*-
"""Сверка legacy API нового проекта со старым сервером.

Старый проект (Desktop/car-tracker-test) - эталон форматов ответов.
Новый проект должен отдавать то же самое по тем же адресам, иначе
старая GUI (app/static/index.html) не заработает.

Запуск (из папки проекта):
    python check_legacy_api.py --base http://127.0.0.1:5055

Нужен запущенный новый сервер в режиме DEV_MODE (или с подписью
Telegram в заголовке X-Telegram-Init-Data).
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


# ---------- Вспомогательные функции ----------


def say(text: str) -> None:
    """Печать без падения на старой кодировке консоли (cp1251)."""
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe + "\n")


def fetch(base: str, path: str, headers: dict | None = None) -> tuple:
    """Запрос к серверу. Возвращает (код, json или текст)."""
    url = base.rstrip("/") + path
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            if "json" in content_type:
                return response.status, json.loads(body.decode("utf-8"))
            return response.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, None
    except Exception as error:  # noqa: BLE001 - сверка не должна падать
        return 0, str(error)


def keys_of(value) -> set:
    """Ключи верхнего уровня ответа (для объекта) или названия полей первого
    элемента списка (для списка)."""
    if isinstance(value, dict):
        return set(value.keys())
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return set(value[0].keys())
    return set()


# ---------- Список проверок ----------

# (адрес, метод, ожидаемый ключ верхнего уровня)
CHECKS = [
    ("/api/cars", "GET", "cars"),
    ("/api/catalog", "GET", "items"),
    ("/api/drivers", "GET", None),
    ("/api/customers", "GET", None),
    ("/api/barrel", "GET", "balance"),
    ("/api/month-costs", "GET", "costs"),
    ("/api/report-summary", "GET", "report"),
    ("/api/reports", "GET", "reports"),
]


def main() -> int:
    """Сверяет старый и новый серверы по списку адресов."""
    parser = argparse.ArgumentParser(description="Сверка legacy API")
    parser.add_argument("--base", default="http://127.0.0.1:5055", help="новый сервер")
    parser.add_argument(
        "--old",
        default="http://127.0.0.1:8000",
        help="старый сервер-эталон (если не нужен - пустая строка)",
    )
    parser.add_argument("--init-data", default="", help="значение заголовка X-Telegram-Init-Data")
    args = parser.parse_args()

    headers = {}
    if args.init_data:
        headers["X-Telegram-Init-Data"] = args.init_data

    problems = 0
    say("Адрес                    | новый            | старый           | ключи")
    say("-------------------------+------------------+------------------+-------")
    for path, method, expected in CHECKS:
        status, data = fetch(args.base, path, headers)
        new_keys = sorted(keys_of(data))
        old_status, old_data = (None, None)
        if args.old:
            old_status, old_data = fetch(args.old, path, headers)
        old_keys = sorted(keys_of(old_data))

        mark = "OK"
        if status != 200:
            mark = "ОШИБКА"
        elif expected and expected not in new_keys:
            mark = "НЕТ КЛЮЧА"
        elif args.old and old_status == 200 and new_keys != old_keys:
            mark = "РАЗЛИЧИЯ"

        if mark != "OK":
            problems += 1

        say(
            f"{path:24} | {str(status):16} | {str(old_status):16} | "
            f"{','.join(new_keys)}  [{mark}]"
        )
        if mark == "РАЗЛИЧИЯ":
            say(f"    старый: {','.join(old_keys)}")

    say("")
    if problems:
        say(f"Проблем: {problems} из {len(CHECKS)}")
        return 1
    say("Все адреса отвечают как надо")
    return 0


if __name__ == "__main__":
    sys.exit(main())
