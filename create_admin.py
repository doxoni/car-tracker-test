# -*- coding: utf-8 -*-
"""Создание или обновление администратора car-tracker в текущей БД.

Запуск (PowerShell):
    python create_admin.py <telegram_id> [имя] [уровень]

Пример:
    python create_admin.py 123456789 "Koval" 3

Уровни: 1 — водитель, 2 — оператор, 3 — суперадмин (все права).

Строку подключения берёт из переменной окружения DATABASE_URL, а если её
нет - из файла .db_connection.txt (его создаёт setup_db.ps1).
"""

import os
import sys
from pathlib import Path

# Консоль Windows по умолчанию cp1251 - эмодзи и часть букв в ней не печатаются.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ROOT = Path(__file__).resolve().parent
CONN_FILE = ROOT / ".db_connection.txt"


def read_connection() -> str:
    """Строка подключения: из окружения или из файла .db_connection.txt."""
    url = (os.getenv("DATABASE_URL") or "").strip()
    if url:
        return url

    if CONN_FILE.exists():
        # utf-8-sig: файл мог быть записан в PowerShell 5.1 (UTF-8 с BOM).
        for line in CONN_FILE.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("DATABASE_URL="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value

    print(
        "ОШИБКА: нет строки подключения к БД.\n"
        "  Сначала создай базу: powershell -ExecutionPolicy Bypass -File setup_db.ps1"
    )
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Использование: python create_admin.py <telegram_id> [имя|уровень] [уровень]")
        sys.exit(1)

    try:
        tg_id = int(sys.argv[1])
    except ValueError:
        print("Telegram ID должен быть числом")
        sys.exit(1)

    # Второй аргумент - либо уровень (1/2/3), либо имя.
    # Третий аргумент - уровень, если второй был именем.
    username = None
    level = 3
    rest = sys.argv[2:]

    if rest and rest[0] in ("1", "2", "3"):
        level = int(rest[0])
        rest = rest[1:]
    elif rest:
        username = rest[0]
        rest = rest[1:]
        if rest:
            try:
                level = int(rest[0])
            except ValueError:
                print("Уровень должен быть 1, 2 или 3")
                sys.exit(1)

    if level not in (1, 2, 3):
        print("Уровень должен быть 1, 2 или 3")
        sys.exit(1)

    # Строку подключения задаём до импорта app: конфиг читает
    # переменные окружения в момент импорта.
    url = read_connection()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    os.environ["DATABASE_URL"] = url

    from app import create_app, db
    from app.models import User

    application = create_app()
    with application.app_context():
        user = User.query.filter_by(tg_id=tg_id).first()
        if user:
            user.username = username or user.username
            user.level = level
            user.is_whitelisted = True
            action = "Обновлён"
        else:
            user = User(
                tg_id=tg_id,
                username=username,
                level=level,
                is_whitelisted=True,
            )
            db.session.add(user)
            action = "Создан"

        db.session.commit()
        print(f"✅ {action}: tg_id={tg_id}, уровень={level}")


if __name__ == "__main__":
    main()
