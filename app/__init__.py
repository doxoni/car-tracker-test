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


def create_app():
    """Создаёт экземпляр Flask приложения с настройками."""
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    app.before_request(_parse_init_data)

    # Регистрация blueprints (маршрутов)
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    with app.app_context():
        db.create_all()

    return app