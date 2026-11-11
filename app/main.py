# -*- coding: utf-8 -*-
"""Точка входа для car-tracker backend.

Запуск локально (PowerShell):
    python app/main.py

На Render используется gunicorn (см. wsgi.py): веб-сервер отдаёт Mini App,
Telegram-бот работает long polling в отдельном потоке того же процесса.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.bot_runner import ensure_bot_started

application = create_app()


def main():
    """Запустить веб-сервер (и бота, если он включён)."""
    ensure_bot_started("local")

    # Монитор UptimeRobot: днём пинг, ночью пауза (контейнер спит).
    from app.uptime import start_worker

    start_worker()

    application.run(host="0.0.0.0", port=int(os.getenv("PORT") or 5000))


if __name__ == "__main__":
    main()
