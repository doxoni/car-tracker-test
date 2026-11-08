# -*- coding: utf-8 -*-
"""Точка входа для car-tracker backend.

Запуск: `python app/main.py`

На Render (бесплатный план) работает один процесс, поэтому Telegram-бот
поднимается в отдельном потоке внутри того же процесса, что и веб-сервер.
Бот отключается, если не задан TELEGRAM_TOKEN или стоит BOT_ENABLED=0.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.config import Config


application = create_app()


def _bot_enabled() -> bool:
    """Запускать ли Telegram-бот вместе с веб-сервером."""
    flag = (os.getenv("BOT_ENABLED") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return bool((Config.TELEGRAM_TOKEN or "").strip())


def _start_bot():
    """Поднять бота в фоновом потоке."""
    try:
        from bot.bot import build_app as build_bot

        bot_app = build_bot()
        print("🤖 Бот запущен (long polling)...")
        bot_app.run_polling()
    except Exception as exc:
        print(f"❌ Бот не запустился: {exc}")


def main():
    """Запустить веб-сервер и (если нужно) бота."""
    if _bot_enabled():
        thread = threading.Thread(target=_start_bot, name="telegram-bot", daemon=True)
        thread.start()
    else:
        print("🤖 Бот выключен (нет TELEGRAM_TOKEN или BOT_ENABLED=0)")

    application.run(host="0.0.0.0", port=int(os.getenv("PORT") or 5000))


if __name__ == "__main__":
    main()
