# -*- coding: utf-8 -*-
"""Запуск Telegram-бота в фоновом потоке.

На бесплатном плане Render работает один процесс, поэтому бот живёт
в том же процессе, что и веб-сервер, но в отдельном потоке.
"""

import os
import threading

# Состояние бота - чтобы его видно было через /api/health без доступа
# к логам Render (их нельзя прочитать через API).
BOT_STATE = {
    "enabled": False,
    "status": "not_started",
    "error": "",
    "started_at": "",
}


def bot_state() -> dict:
    """Текущее состояние бота (копия, чтобы отдача не ломала запись)."""
    return dict(BOT_STATE)


def bot_enabled() -> bool:
    """Запускать ли бота (нужен токен и не выключен флагом BOT_ENABLED=0)."""
    flag = (os.getenv("BOT_ENABLED") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    from app.config import Config

    return bool((Config.TELEGRAM_TOKEN or "").strip())


def start_bot_thread() -> threading.Thread | None:
    """Поднять бота в фоновом потоке. Возвращает поток или None."""
    from datetime import datetime

    if not bot_enabled():
        BOT_STATE["enabled"] = False
        BOT_STATE["status"] = "disabled"
        print("🤖 Бот выключен (нет TELEGRAM_TOKEN или BOT_ENABLED=0)")
        return None

    BOT_STATE["enabled"] = True

    def _run():
        try:
            from bot.bot import build_app as build_bot

            bot_app = build_app()
            BOT_STATE["status"] = "starting"
            BOT_STATE["started_at"] = datetime.now().isoformat(timespec="seconds")
            print("🤖 Бот запущен (long polling)...")
            bot_app.run_polling()
            BOT_STATE["status"] = "stopped"
        except Exception as exc:
            BOT_STATE["status"] = "error"
            BOT_STATE["error"] = f"{type(exc).__name__}: {exc}"[:300]
            print(f"❌ Бот не запустился: {exc}")

    thread = threading.Thread(target=_run, name="telegram-bot", daemon=True)
    thread.start()
    return thread
