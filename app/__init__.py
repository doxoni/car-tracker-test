# -*- coding: utf-8 -*-
"""Создание и настройка Flask приложения."""

from urllib.parse import parse_qs

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from app.config import Config

db = SQLAlchemy()


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
            print(f"⚠️ БД недоступна (попытка {attempt}/{attempts}): {e}")
            if attempt == attempts:
                raise
            time.sleep(delay)


def create_app():
    """Создаёт экземпляр Flask приложения с настройками."""
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    app.before_request(_parse_init_data)

    # Регистрация blueprints (маршрутов)
    from .routes import bp as routes_bp, web_bp
    app.register_blueprint(routes_bp)
    app.register_blueprint(web_bp)

    _init_db(app)

    return app