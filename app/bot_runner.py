# -*- coding: utf-8 -*-
"""Запуск Telegram-бота в фоновом потоке.

На бесплатном плане Render работает один процесс, поэтому бот живёт
в том же процессе, что и веб-сервер, но в отдельном потоке.
"""

import os
import threading


def bot_enabled() -> bool:
    """Запускать ли бота (нужен токен и не выключен флагом BOT_ENABLED=0)."""
    flag = (os.getenv("BOT_ENABLED") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    from app.config import Config

    return bool((Config.TELEGRAM_TOKEN or "").strip())


def start_bot_thread() -> threading.Thread | None:
    """Поднять бота в фоновом потоке. Возвращает поток или None."""
    if not bot_enabled():
        print("🤖 Бот выключен (нет TELEGRAM_TOKEN или BOT_ENABLED=0)")
        return None

    def _run():
        try:
            from bot.bot import build_app as build_bot

            bot_app = build_bot()
            print("🤖 Бот запущен (long polling)...")
            bot_app.run_polling()
        except Exception as exc:
            print(f"❌ Бот не запустился: {exc}")

    thread = threading.Thread(target=_run, name="telegram-bot", daemon=True)
    thread.start()
    return thread
