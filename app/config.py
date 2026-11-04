# -*- coding: utf-8 -*-
"""Конфигурация приложения car-tracker.

Загружает переменные окружения из .env, настраивает Flask и SQLAlchemy.
Запуск: `python app/main.py`
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Конфигурация приложения."""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///cars.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

    # Wialon
    WIALON_TOKEN = os.getenv("WIALON_TOKEN", "")

    # URLs
    APP_URL = os.getenv("APP_URL", "http://localhost:5000")

    # Роли
    ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))
    WHITELISTED_TELEGRAM_IDS = [
        int(x) for x in os.getenv("WHITELISTED_TELEGRAM_IDS", "").split(",")
        if x.strip().isdigit()
    ]

    # Период синхронизации с Wialon (минуты)
    WIALON_SYNC_INTERVAL = int(os.getenv("WIALON_SYNC_INTERVAL", "15"))