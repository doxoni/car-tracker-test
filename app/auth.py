# -*- coding: utf-8 -*-
"""Аутентификация через Telegram Mini App (HMAC-SHA1).

Каждый запрос от Telegram приходит с полями initData и user.
Сервер проверяет подпись HMAC-SHA1(секретный ключ, JSON initData) == init_signature.
Секретный ключ берётся от BotFather.
"""

import base64
import hashlib
from functools import wraps

from flask import request, g, jsonify

from app.config import Config


def get_secret_key():
    """Вернуть секретный ключ (тоже самое что в BotFather)."""
    return Config.TELEGRAM_TOKEN.strip() if Config.TELEGRAM_TOKEN else ""


def _verify_hmac(init_data: dict, secret_key: str) -> bool:
    """Проверка подписи HMAC-SHA1."""
    if not init_data or not secret_key:
        return False
    try:
        raw = base64.urlsafe_b64decode(init_data["encrypted_data"]).decode("utf-8")
        expected = base64.b64encode(hashlib.sha1(raw.encode("utf-8")).digest()).decode("ascii")
        actual = init_data["init_signature"].encode("ascii")
        return expected == actual
    except Exception:
        return False


def verify_telegram_init_data(init_data: dict) -> bool:
    """Вернуть True, если initData прошла HMAC-проверку."""
    return _verify_hmac(init_data, get_secret_key())


def require_auth(f):
    """Требует валидного initData. Класть в g.current_user, g.current_user_level."""

    @wraps(f)
    def decorated(*args, **kwargs):
        init_data = getattr(request, "init_data", None)
        if not verify_telegram_init_data(init_data):
            return jsonify({"error": "unauthorized"}), 401

        tg_user = init_data.get("user")
        g.current_tg_id = tg_user

        try:
            from app.models import User
            u = User.query.filter_by(tg_id=tg_user).first()
            g.current_user = u
            g.current_user_level = u.level if u else 1
        except Exception:
            g.current_user = None
            g.current_user_level = 1

        return f(*args, **kwargs)

    return decorated


def require_level(min_level: int):
    """Требует уровень пользователя >= min_level (1=user, 2=operator, 3=super_admin)."""

    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            level = getattr(g, "current_user_level", 1)
            if level < min_level:
                return jsonify({"error": "forbidden"}), 403
            return f(*args, **kwargs)

        return decorated

    return decorator


def require_can_view_logs(f):
    """Доступ к просмотру аудит-логов (уровни 2 и 3)."""

    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        level = getattr(g, "current_user_level", 1)
        if level not in (2, 3):
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)

    return decorated


def require_can_clear_logs(f):
    """Доступ к удалению аудит-логов (только уровень 3)."""

    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        level = getattr(g, "current_user_level", 1)
        if level != 3:
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)

    return decorated