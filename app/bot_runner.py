# -*- coding: utf-8 -*-
"""Запуск Telegram-бота в фоновом потоке.

На бесплатном плане Render работает один процесс, поэтому бот живёт
в том же процессе, что и веб-сервер, но в отдельном потоке.
"""

import os
import threading
import traceback

# Состояние бота - чтобы его видно было через /api/health без доступа
# к логам Render (их нельзя прочитать через API).
BOT_STATE = {
    "enabled": False,
    "status": "not_started",
    "stage": "",
    "error": "",
    "traceback": "",
    "started_at": "",
    "updated_at": "",
}

# Поток бота - чтобы health показывал, жив ли он.
_bot_thread = None


def bot_state() -> dict:
    """Текущее состояние бота (копия, чтобы отдача не ломала запись)."""
    state = dict(BOT_STATE)
    state["thread_alive"] = bool(_bot_thread and _bot_thread.is_alive())
    state["pid"] = os.getpid()
    return state


def _stage(name: str) -> None:
    """Отметить текущий этап запуска бота."""
    from datetime import datetime

    BOT_STATE["stage"] = name
    BOT_STATE["updated_at"] = datetime.now().isoformat(timespec="seconds")
    print(f"🤖 Бот: этап {name}", flush=True)


def _mask(text: str) -> str:
    """Спрятать секреты из текста ошибки.

    Сообщения Telegram иногда содержат сам токен (например, "The token
    ... was rejected"), а трейсбек - строку подключения к БД с паролем.
    /api/health открыт всем, поэтому секретов там быть не должно.
    """
    import re

    from app.config import Config

    token = (Config.TELEGRAM_TOKEN or "").strip()
    if token:
        text = text.replace(token, "***")
    # Пароль в строке подключения: postgres://пользователь:пароль@хост
    text = re.sub(r"(?i)(://[^:/\s]+:)[^@\s]+@", r"\1***@", text)
    return text


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
        BOT_STATE["stage"] = "выключен флагом BOT_ENABLED или нет токена"
        print("🤖 Бот выключен (нет TELEGRAM_TOKEN или BOT_ENABLED=0)")
        return None

    BOT_STATE["enabled"] = True

    def _run():
        # Статус ставим до импорта: если импорт упадёт, в health будет видно,
        # на каком шаге бот сломался.
        BOT_STATE["status"] = "starting"
        BOT_STATE["started_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            import asyncio

            _stage("импорт модуля бота")
            from bot.bot import build_app as build_bot

            def _on_ready(application):
                """Бот подключился к Telegram: getMe прошёл, опрос идёт."""
                BOT_STATE["status"] = "running"
                _stage("опрос Telegram идёт")

            def _on_stop(application):
                """Опрос остановлен."""
                BOT_STATE["status"] = "stopped"
                _stage("опрос остановлен")

            _stage("сборка приложения бота")
            bot_app = build_bot(on_ready=_on_ready, on_stop=_on_stop)
            # python-telegram-bot внутри run_polling вызывает
            # asyncio.get_event_loop(). В потоке, где цикла ещё нет, это
            # ошибка - поэтому создаём цикл и делаем его текущим для потока.
            asyncio.set_event_loop(asyncio.new_event_loop())
            _stage("запуск long polling")
            # stop_signals=None: ставить обработчики сигналов можно только
            # в главном потоке, а бот работает в отдельном.
            bot_app.run_polling(stop_signals=None)
            BOT_STATE["status"] = "stopped"
        except BaseException as exc:
            # BaseException, а не Exception: SystemExit и прочие наследники
            # Exception не ловят, а из-за этого бот молча умирал.
            BOT_STATE["status"] = "error"
            BOT_STATE["error"] = _mask(f"{type(exc).__name__}: {exc}")[:300]
            BOT_STATE["traceback"] = _mask(traceback.format_exc())[-800:]
            _stage("ошибка запуска")
            print(f"❌ Бот не запустился: {exc}", flush=True)

    global _bot_thread
    thread = threading.Thread(target=_run, name="telegram-bot", daemon=True)
    _bot_thread = thread
    thread.start()
    return thread
