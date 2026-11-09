# -*- coding: utf-8 -*-
"""Создание и настройка Flask приложения."""

import os
from urllib.parse import parse_qs

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from app.config import Config

db = SQLAlchemy()

# Хук после форка регистрируется один раз на процесс.
_fork_hook_done = False


def _parse_init_data():
    """Парсит Telegram Mini App initData из заголовка или query-параметра.

    Telegram Web App передаёт initData как строку вида
    "user=...&hash=...&auth_date=..." через заголовок
    X-Telegram-Init-Data или query-параметр initData.
    """
    raw = request.headers.get("X-Telegram-Init-Data") or request.args.get("initData")
    if not raw:
        request.init_data = None
        return
    parsed = parse_qs(raw)
    request.init_data = {k: v[0] for k, v in parsed.items()}


def _init_db(app, attempts: int = 10, delay: float = 5.0):
    """Привести схему БД в порядок, дожидаясь готовности базы.

    Cloud SQL может быть ещё не готов к первому подключению после деплоя,
    поэтому повторяем попытки с задержкой.
    """
    import time
    from sqlalchemy.exc import OperationalError

    for attempt in range(1, attempts + 1):
        try:
            with app.app_context():
                from app.db_schema import ensure_schema

                ensure_schema(app)
            return
        except OperationalError as e:
            # Печать может упасть на консоли Windows (кодировка cp1251),
            # а из-за этого не будет видно настоящей ошибки. Поэтому
            # печатаем осторожно.
            try:
                print(f"⚠️ БД недоступна (попытка {attempt}/{attempts}): {e}")
            except Exception:
                pass
            if attempt == attempts:
                raise
            time.sleep(delay)


def _ensure_bot_on_request():
    """Поднять Telegram-бота, если он в этом процессе ещё не работает.

    Запасной путь: если хук gunicorn (gunicorn.conf.py) по какой-то
    причине не сработал, бот поднимется при первом обращении к сайту.
    Запросы обслуживает только процесс-воркер, поэтому бот окажется
    именно в том процессе, который отвечает клиентам.
    """
    from app.bot_runner import ensure_bot_started

    ensure_bot_started("request")


def _register_fork_hook(app):
    """Подготовить дочерний процесс после форка.

    Если приложение импортировали до создания воркера (gunicorn с
    preload), то соединения с базой наследуются форкнутым процессом.
    Одно и то же соединение в двух процессах ломает протокол Postgres,
    поэтому в дочернем процессе пул закрывается и соединения создаются
    заново. Заодно сбрасывается состояние бота.
    """
    global _fork_hook_done
    if _fork_hook_done or not hasattr(os, "register_at_fork"):
        return
    _fork_hook_done = True

    def _after_fork():
        try:
            with app.app_context():
                db.engine.dispose()
        except Exception as exc:
            print(f"⚠️ Не удалось закрыть соединения с БД после форка: {exc}")
        from app.bot_runner import reset_after_fork

        reset_after_fork()

    os.register_at_fork(after_in_child=_after_fork)


def create_app():
    """Создаёт экземпляр Flask приложения с настройками."""
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    app.before_request(_parse_init_data)
    app.before_request(_ensure_bot_on_request)

    # Регистрация blueprints (маршрутов)
    from .routes import bp as routes_bp, web_bp
    app.register_blueprint(routes_bp)
    app.register_blueprint(web_bp)

    _register_fork_hook(app)

    _init_db(app)

    return app