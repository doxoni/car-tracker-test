# -*- coding: utf-8 -*-
"""Применяет миграции alembic к облачной базе.

Что делает:
  1. Берёт строку подключения из .db_connection.txt (её создаёт
     setup_db.ps1) или из переменной окружения DATABASE_URL.
  2. Запускает `alembic upgrade head`.

Зачем это нужно: при первом запуске на пустой базе приложение само
создаёт таблицы через db.create_all(), но таблицы alembic_version
при этом не появляется. И тогда любая следующая миграция упадёт
с ошибкой "таблица уже существует". Миграции должны applied
в порядке, с самого начала.

Запуск (PowerShell, из папки проекта):
    python apply_migrations.py
"""

import os
import subprocess
import sys
from pathlib import Path

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
    url = read_connection()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    print("=== Применяем миграции ===")
    env = dict(os.environ)
    env["DATABASE_URL"] = url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
    )
    if result.returncode != 0:
        print("")
        print("ОШИБКА: миграции не применились (см. вывод выше).")
        sys.exit(result.returncode)

    print("")
    print("DONE. Схема БД актуальна.")


if __name__ == "__main__":
    main()
