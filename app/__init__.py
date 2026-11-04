# -*- coding: utf-8 -*-
"""Создание и настройка Flask приложения."""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from app.config import Config

db = SQLAlchemy()


def create_app():
    """Создаёт экземпляр Flask приложения с настройками."""
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    # Регистрация blueprints (маршрутов)
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    with app.app_context():
        db.create_all()

    return app