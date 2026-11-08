# -*- coding: utf-8 -*-
"""Создание или обновление администратора car-tracker в текущей БД.

Запуск (PowerShell):
    $env:DATABASE_URL="postgresql://car_tracker:пароль@IP:5432/cars?sslmode=require"
    python create_admin.py <telegram_id> [имя] [уровень]

Пример:
    python create_admin.py 123456789 "Koval" 3

Уровни: 1 — водитель, 2 — оператор, 3 — суперадмин (все права).
"""

import sys

# Консоль Windows по умолчанию cp1251 - эмодзи и часть букв в ней не печатаются.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from app import create_app, db
from app.models import User


def main():
    if len(sys.argv) < 2:
        print("Использование: python create_admin.py <telegram_id> [имя] [уровень]")
        sys.exit(1)

    try:
        tg_id = int(sys.argv[1])
    except ValueError:
        print("Telegram ID должен быть числом")
        sys.exit(1)

    username = sys.argv[2] if len(sys.argv) > 2 else None
    level = int(sys.argv[3]) if len(sys.argv) > 3 else 3

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
