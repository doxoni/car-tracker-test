# -*- coding: utf-8 -*-
"""Вписать токен бота и задеплоить сервис на Render.

Скрипт спрашивает токен (его выдаёт @BotFather), записывает его в
файл render_env.txt и запускает деплой deploy_render.py.

Запуск (PowerShell, из папки проекта):
    python tools/set_bot_token.py

Токен сохраняется только в render_env.txt - этот файл в .gitignore,
в Git токен не попадёт.
"""

import os
import re
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, "render_env.txt")
DEPLOY = os.path.join(ROOT, "deploy_render.py")

TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


def read_env_file() -> list:
    """Строки файла render_env.txt."""
    if not os.path.exists(ENV_FILE):
        return []
    with open(ENV_FILE, encoding="utf-8-sig") as handle:
        return handle.read().splitlines()


def save_token(token: str) -> None:
    """Записать токен в render_env.txt, заменив старую строку."""
    lines = read_env_file()
    result = []
    replaced = False
    for line in lines:
        if line.strip().startswith("TELEGRAM_TOKEN="):
            if not replaced:
                result.append(f"TELEGRAM_TOKEN={token}")
                replaced = True
            continue
        result.append(line)
    if not replaced:
        result.append(f"TELEGRAM_TOKEN={token}")
    with open(ENV_FILE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(result).rstrip() + "\n")


def main() -> int:
    """Спросить токен, сохранить и задеплоить."""
    print("Нужен токен бота от @BotFather.")
    print("Открой @BotFather -> /mybots -> выбери бота -> API Token.")
    print("Токен выглядит как 123456789:AA... (около 46 символов).")
    token = input("Вставь токен: ").strip()

    if not TOKEN_RE.match(token):
        print("Похоже, это не токен бота. Формат: 123456789:AA...")
        return 1

    # Проверяем токен у Telegram до деплоя.
    try:
        import requests

        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=30
        )
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - сеть может быть недоступна
        print(f"Проверить токен не удалось: {type(exc).__name__}. Продолжаю.")
    else:
        if not data.get("ok"):
            print(f"Telegram не принимает токен: {data.get('description')}")
            return 1
        print(f"Токен рабочий, бот: @{data['result'].get('username')}")

    save_token(token)
    print("Токен записан в render_env.txt.")
    print("Запускаю деплой...")

    return subprocess.call([sys.executable, DEPLOY], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
