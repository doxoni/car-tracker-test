# -*- coding: utf-8 -*-
"""Запуск Telegram-бота в фоновом потоке.

На бесплатном плане Render работает один процесс, поэтому бот живёт
в том же процессе, что и веб-сервер, но в отдельном потоке.
"""

import os
import threading
import time
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
    # PID процесса, в котором бот реально работает. Если он не совпадает
    # с PID процесса, который отвечает на /api/health - значит бот живёт
    # в другом процессе (или процесс перезапустился после старта бота).
    "bot_pid": 0,
    # Секунд с последнего обновления состояния: показывает, что бот жив.
    "heartbeat": 0.0,
}

# Поток бота - чтобы health показывал, жив ли он.
_bot_thread = None
# Telegram-приложение и его event loop - нужны, чтобы остановить опрос
# извне (например, когда наступила ночная пауза).
_bot_app = None
_bot_loop = None
# Поток, который обновляет heartbeat: по нему видно, что бот работает.
_heartbeat_thread = None
# Поток-сторож ночного окна: он следит за временем и в 05:00 поднимает бота.
_night_thread = None
# Флаг: бот уже стартовал в этом процессе (чтобы не запустить дважды).
_started = False
# Когда последний раз пытались поднять бота: чтобы при падении не спамить
# перезапусками на каждом запросе.
_last_start_attempt = 0.0
# Откуда запустили бота - для диагностики в /api/health.
_started_by = ""
# Пауза между попытками перезапуска после падения, секунды.
RESTART_COOLDOWN = 60
# Замок на запуск: запросы идут параллельно, старт должен быть один.
_start_lock = threading.Lock()
# PID процесса, в котором модуль загрузился. Если он не совпадает с текущим
# - значит процесс был создан форком уже после импорта (gunicorn с preload).
_import_pid = os.getpid()


def bot_state() -> dict:
    """Текущее состояние бота (копия, чтобы отдача не ломала запись)."""
    import threading

    state = dict(BOT_STATE)
    state["thread_alive"] = bool(_bot_thread and _bot_thread.is_alive())
    state["pid"] = os.getpid()
    state["ppid"] = os.getppid()
    state["parent_cmd"] = _parent_cmd()
    state["heartbeat_age"] = round(time.time() - BOT_STATE["heartbeat"], 1)
    state["started_by"] = _started_by
    # PID процесса, в котором модуль загрузился. Если он отличается от
    # текущего - процесс создан форком уже после импорта, и потоки бота
    # в нём не пережили форк.
    state["import_pid"] = _import_pid
    state["forked"] = _import_pid != os.getpid()
    # Список потоков процесса: видно, есть ли вообще поток бота.
    state["threads"] = sorted(t.name for t in threading.enumerate())
    return state


def _parent_cmd() -> str:
    """Команда родительского процесса - показывает, кто форкнул воркера."""
    try:
        with open(f"/proc/{os.getppid()}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace")[:120]
    except OSError:
        return ""


def _stage(name: str) -> None:
    """Отметить текущий этап запуска бота."""
    from datetime import datetime

    BOT_STATE["stage"] = name
    BOT_STATE["updated_at"] = datetime.now().isoformat(timespec="seconds")
    BOT_STATE["heartbeat"] = time.time()
    try:
        print(f"🤖 Бот: этап {name}", flush=True)
    except Exception:
        # stdout на сервере может быть в не-UTF-8 кодировке: печать не должна
        # ронять бота.
        pass


def _heartbeat_loop() -> None:
    """Обновлять время последнего обновления, пока бот жив.

    Если бот завис или умер, heartbeat перестанет расти - это видно
    в /api/health.
    """
    while True:
        # Поток бота умер - обновлять heartbeat больше нечего, иначе в
        # /api/health будет видно живого бота, хотя он не работает.
        if _bot_thread is None or not _bot_thread.is_alive():
            return
        BOT_STATE["heartbeat"] = time.time()
        time.sleep(5)


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


# ---------- Ночная пауза ----------


def _now_text() -> str:
    """Текущее время в виде строки (для /api/health)."""
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _night_end_text() -> str:
    """Время окончания ночного окна словами: "05:00"."""
    from app.config import Config

    return f"{int(Config.NIGHT_END_HOUR):02d}:00"


def _stop_bot_for_night() -> None:
    """Остановить опрос Telegram, потому что наступило ночное окно.

    Опрос останавливаем из event loop самого бота: stop_running() завершает
    run_forever, после чего run_polling корректно гасит апдейты.
    """
    global _started

    app = _bot_app
    loop = _bot_loop
    thread = _bot_thread
    if app is None or loop is None or thread is None:
        return
    if not thread.is_alive():
        return

    try:
        loop.call_soon_threadsafe(app.stop_running)
    except Exception as exc:
        print(f"🤖 Не удалось остановить бота на ночь: {exc}", flush=True)
        return

    # Ждём, пока опрос действительно завершится (обычно мгновенно).
    thread.join(timeout=30)
    with _start_lock:
        _started = False
        _bot_thread = None
        _bot_app = None
        _bot_loop = None
    BOT_STATE["status"] = "night_mode"
    BOT_STATE["stage"] = f"ночная пауза до {_night_end_text()} по Киеву"
    BOT_STATE["updated_at"] = _now_text()
    print("🤖 Бот остановлен: ночная пауза", flush=True)


def _night_watchdog_loop() -> None:
    """Сторож ночного окна.

    Каждые полминуты смотрит на киевское время:
      - если наступила ночь, а бот ещё работает - останавливает его;
      - если ночь кончилась, а бот не работает - поднимает его снова.
    Так бот сам засыпает в 02:00 и сам просыпается в 05:00, даже если
    сервис всё это время жил.
    """
    from app.night_mode import is_night

    while True:
        try:
            night = is_night()
            alive = bool(_bot_thread and _bot_thread.is_alive())
            if night and alive:
                _stop_bot_for_night()
            elif not night and not alive and bot_enabled():
                ensure_bot_started("night_watchdog")
        except Exception as exc:
            print(f"⚠️ Сторож ночного окна: {exc}", flush=True)
        time.sleep(30)


def _ensure_night_watchdog() -> None:
    """Запустить сторож ночного окна (один раз на процесс)."""
    global _night_thread

    if _night_thread is not None and _night_thread.is_alive():
        return
    _night_thread = threading.Thread(
        target=_night_watchdog_loop, name="bot-night-watchdog", daemon=True
    )
    _night_thread.start()


def _install_thread_excepthook():
    """Ловить исключения потоков, иначе они молча теряются.

    Без этого поток бота может умереть, не оставив в состоянии ни слова
    об ошибке, и /api/health так и будет показывать "starting".
    """
    old_hook = threading.excepthook

    def _hook(args):
        BOT_STATE["status"] = "error"
        BOT_STATE["error"] = _mask(f"{args.exc_type.__name__}: {args.exc_value}")[:300]
        BOT_STATE["traceback"] = _mask(
            "".join(
                traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                )
            )
        )[-800:]
        _stage("ошибка в потоке бота")
        old_hook(args)

    threading.excepthook = _hook


def ensure_bot_started(source: str = "request"):
    """Поднять бота, если в этом процессе он ещё не работает.

    Вызывается из трёх мест:
      - хук post_worker_init gunicorn (основной путь на Render);
      - хук после форка - если приложение импортировали до форка;
      - before_request - запасной вариант, если хуки не сработали.

    Ночью бот не стартует: ночное окно (по умолчанию 02:00-05:00 по Киеву)
    проверяется здесь, в общем месте - иначе разные пути запуска вели бы
    себя по-разному.

    Возвращает поток бота или None.
    """
    if not bot_enabled():
        return None

    _ensure_night_watchdog()

    from app.night_mode import is_night

    if is_night():
        BOT_STATE["status"] = "night_mode"
        BOT_STATE["stage"] = f"ночная пауза до {_night_end_text()} по Киеву"
        BOT_STATE["updated_at"] = _now_text()
        BOT_STATE["heartbeat"] = time.time()
        return None

    with _start_lock:
        if _bot_thread is not None and _bot_thread.is_alive():
            return _bot_thread

        if _started:
            # Бот уже пробовал запуститься и упал. Повторяем не сразу,
            # чтобы не долбить Telegram при каждом запросе.
            if time.time() - _last_start_attempt < RESTART_COOLDOWN:
                return None

        return start_bot_thread(source)


def reset_after_fork():
    """Сбросить состояние бота после форка.

    Потоки при форке не переносятся: в дочернем процессе остаётся только
    копия переменных. Поэтому состояние сбрасываем - иначе /api/health
    будет показывать замороженное состояние из родительского процесса.
    Запуск бота делает вызывающий код (хук gunicorn или обработчик
    запроса) - он уже выполняется в нужном процессе.
    """
    global _bot_thread, _heartbeat_thread, _started, _last_start_attempt, _start_lock
    global _bot_app, _bot_loop, _night_thread

    _bot_thread = None
    _heartbeat_thread = None
    _bot_app = None
    _bot_loop = None
    # Сторож ночного окна - тоже поток, в дочернем процессе его нет.
    _night_thread = None
    _started = False
    _last_start_attempt = 0.0
    # Замок могли удерживать потоки родительского процесса - в дочернем
    # их нет, а сам замок остался в запертом состоянии. Делаем новый.
    _start_lock = threading.Lock()
    BOT_STATE.update(
        {
            "status": "not_started",
            "stage": "",
            "error": "",
            "traceback": "",
            "started_at": "",
            "updated_at": "",
            "bot_pid": 0,
            "heartbeat": 0.0,
        }
    )


def start_bot_thread(source: str = "import") -> threading.Thread | None:
    """Поднять бота в фоновом потоке. Возвращает поток или None.

    source - откуда запустили ("import", "gunicorn", "request"):
    попадает в /api/health, чтобы было видно, где бот поднялся.
    """
    global _bot_thread, _heartbeat_thread, _started, _started_by, _last_start_attempt
    global _bot_app, _bot_loop
    from datetime import datetime

    if not bot_enabled():
        BOT_STATE["enabled"] = False
        BOT_STATE["status"] = "disabled"
        BOT_STATE["stage"] = "выключен флагом BOT_ENABLED или нет токена"
        try:
            print("🤖 Бот выключен (нет TELEGRAM_TOKEN или BOT_ENABLED=0)")
        except Exception:
            pass
        return None

    if _started and _bot_thread is not None and _bot_thread.is_alive():
        # Бот уже поднят в этом процессе - второй раз запускать нельзя,
        # иначе получим конфликт опроса Telegram.
        return _bot_thread

    _started = True
    _started_by = source
    _last_start_attempt = time.time()
    BOT_STATE["enabled"] = True
    BOT_STATE["bot_pid"] = os.getpid()
    BOT_STATE["heartbeat"] = time.time()

    def _run():
        # Статус ставим до импорта: если импорт упадёт, в health будет видно,
        # на каком шаге бот сломался.
        BOT_STATE["status"] = "starting"
        BOT_STATE["started_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            import asyncio

            _stage("импорт модуля бота")
            from bot.bot import build_app as build_bot

            async def _on_ready(application):
                """Бот подключился к Telegram: getMe прошёл, опрос идёт.

                Колбэк обязан быть корутиной: python-telegram-bot ждёт
                awaitable из post_init/post_stop, и обычная функция
                приводит к ошибке "An asyncio.Future, a coroutine or an
                awaitable is required".
                """
                BOT_STATE["status"] = "running"
                _stage("опрос Telegram идёт")

            async def _on_stop(application):
                """Опрос остановлен."""
                BOT_STATE["status"] = "stopped"
                _stage("опрос остановлен")

            _stage("сборка приложения бота")
            bot_app = build_bot(on_ready=_on_ready, on_stop=_on_stop)
            # python-telegram-bot внутри run_polling вызывает
            # asyncio.get_event_loop(). В потоке, где цикла ещё нет, это
            # ошибка - поэтому создаём цикл и делаем его текущим для потока.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # Сохраняем приложение и цикл: сторож ночного окна должен
            # суметь остановить опрос снаружи потока бота.
            _bot_app = bot_app
            _bot_loop = loop
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
            try:
                print(f"❌ Бот не запустился: {exc}", flush=True)
            except Exception:
                pass

    _install_thread_excepthook()
    thread = threading.Thread(target=_run, name="telegram-bot", daemon=True)
    _bot_thread = thread
    thread.start()

    _heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, name="bot-heartbeat", daemon=True
    )
    _heartbeat_thread.start()
    return thread
