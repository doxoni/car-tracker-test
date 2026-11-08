# -*- coding: utf-8 -*-
"""Конфигурация приложения car-tracker.

Загружает переменные окружения из .env, настраивает Flask и SQLAlchemy.
Запуск: `python app/main.py`
"""

import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()


def _build_database_uri():
    """Собрать строку подключения к БД.

    Поддерживаются варианты:
    - DATABASE_URL — готовая строка (Render, Cloud SQL, локально)
    - DB_HOST + DB_PORT + DB_NAME + DB_USER + DB_PASSWORD — Cloud SQL по частям
    - иначе — локальный SQLite
    """
    url = (os.getenv("DATABASE_URL") or "").strip()
    if url:
        # Некоторые платформы отдают схему postgres:// — SQLAlchemy 2.x ждёт postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url

    host = (os.getenv("DB_HOST") or "").strip()
    if host:
        port = (os.getenv("DB_PORT") or "5432").strip()
        name = (os.getenv("DB_NAME") or "cars").strip()
        user = (os.getenv("DB_USER") or "").strip()
        password = (os.getenv("DB_PASSWORD") or "").strip()
        sslmode = (os.getenv("DB_SSLMODE") or "require").strip()
        creds = user
        if password:
            creds = f"{quote(user, safe='')}:{quote(password, safe='')}"
        return f"postgresql://{creds}@{host}:{port}/{name}?sslmode={sslmode}"

    return "sqlite:///cars.db"


class Config:
    """Конфигурация приложения."""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Пул соединений: облачные БД рвут простаивающие соединения, поэтому
    # pool_pre_ping проверяет соединение перед использованием.
    # Размер пула настраивается переменными окружения: у бесплатных
    # хостингов (Neon, Aiven) свой лимит на одновременные соединения.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
    }

    # Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

    # Wialon
    WIALON_TOKEN = os.getenv("WIALON_TOKEN", "")

    # URLs
    APP_URL = os.getenv("APP_URL", "http://localhost:5000")

    # Роли
    ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID") or "0")
    WHITELISTED_TELEGRAM_IDS = [
        int(x) for x in os.getenv("WHITELISTED_TELEGRAM_IDS", "").split(",")
        if x.strip().isdigit()
    ]

    # Период синхронизации с Wialon (минуты)
    WIALON_SYNC_INTERVAL = int(os.getenv("WIALON_SYNC_INTERVAL", "15"))

    # DEV режим: пропускает проверку Telegram initData, использует DEV_USER_ID
    DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ("1", "true", "yes")
    DEV_USER_ID = int(os.getenv("DEV_USER_ID", "0"))