# -*- coding: utf-8 -*-
"""Аутентификация через Telegram Mini App (HMAC-SHA256).

Каждый запрос от Telegram приходит с полями initData и user.
Сервер проверяет подпись: HMAC-SHA256(secret_key, data-check-string) == hash,
где secret_key = HMAC-SHA256("WebAppData", bot_token).

DEV_MODE — локальный режим: пропускает проверку Telegram и использует
DEV_USER_ID из .env (для тестов без реального бота).
"""

import hashlib
import hmac
import json
from functools import wraps

from flask import request, g, jsonify

from app.config import Config
from app import db

# Тексты ошибок доступа. Раньше здесь стояли английские коды
# ("unauthorized", "forbidden") - пользователь видел их в Mini App
# без всякого объяснения. Теперь это понятные фразы, которые ещё и
# переводятся на украинский (словарь app/i18n_dict.py).
ERROR_NO_ACCESS = "нет доступа"
ERROR_NO_RIGHTS = "недостаточно прав"


def get_secret_key():
    """Секретный ключ: HMAC-SHA256("WebAppData", bot_token)."""
    token = (Config.TELEGRAM_TOKEN or "").strip()
    if not token:
        return b""
    return hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()


def _parse_user(init_data):
    """Поле user приходит как JSON-строка -> dict с id, first_name и т.д."""
    raw = init_data.get("user")
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def parse_init_data(raw: str) -> dict:
    """Разобрать сырую строку initData от Telegram в словарь полей.

    Telegram присылает initData строкой запроса: "user={...}&auth_date=...&hash=..."
    Значения при этом percent-encoded, поэтому сначала декодируем их.
    """
    from urllib.parse import parse_qs

    if not raw:
        return {}
    parsed = parse_qs(raw)
    return {key: values[0] for key, values in parsed.items() if values}


def user_from_init_data(init_data: dict) -> dict:
    """Данные пользователя Telegram из initData (пустой dict, если их нет)."""
    return _parse_user(init_data) or {}


def verify_telegram_init_data(init_data: dict) -> bool:
    """Проверить подпись Telegram Mini App initData.

    Алгоритм:
      1. Извлечь hash из init_data.
      2. Собрать data-check-string из остальных полей, отсортированных по ключу.
      3. Вычислить HMAC-SHA256(secret_key, data-check-string).
      4. Сравнить с hash.
    """
    if not init_data or not isinstance(init_data, dict):
        return False
    hash_value = init_data.get("hash")
    if not hash_value:
        return False
    secret_key = get_secret_key()
    if not secret_key:
        return False

    # Собираем data-check-string из всех полей, кроме hash, в порядке возрастания ключей.
    data_check_string = "\n".join(
        "%s=%s" % (k, v)
        for k, v in sorted(init_data.items())
        if k != "hash"
    )

    computed = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Защита от timing-атак: сравниваем через hmac.compare_digest.
    try:
        return hmac.compare_digest(computed, str(hash_value))
    except Exception:
        return False


def _dev_user_id():
    """Вернуть DEV_USER_ID из Config (0 — не установлен)."""
    return getattr(Config, "DEV_USER_ID", 0)


def require_auth(f):
    """Требует валидного initData (или DEV_MODE). Кладёт в g.current_user, g.current_user_level."""

    @wraps(f)
    def decorated(*args, **kwargs):
        tg_id = None

        if Config.DEV_MODE:
            # Локальный режим: пропускаем проверку Telegram, используем DEV_USER_ID.
            tg_id = _dev_user_id() or None
        else:
            init_data = getattr(request, "init_data", None)
            if not verify_telegram_init_data(init_data):
                return jsonify({"error": ERROR_NO_ACCESS}), 401
            user = _parse_user(init_data) or {}
            tg_id = user.get("id")

        g.current_tg_id = tg_id

        try:
            from app.models import User
            u = User.query.filter_by(tg_id=tg_id).first() if tg_id else None

            # Человека ещё нет в БД - заводим его как обычного пользователя
            # (уровень 1). Бот и Mini App работают для всех, кто их открыл,
            # без белого списка. В DEV_MODE не заводим: там нет настоящего
            # Telegram-человека, тесты ждут отказа при неизвестном id.
            if u is None and tg_id and not Config.DEV_MODE:
                u = User(tg_id=tg_id, level=1, is_whitelisted=True)
                db.session.add(u)
                db.session.commit()
        except Exception:
            u = None

        # Пользователя нет в БД - доступа нет (в т.ч. в DEV_MODE).
        # Без этой проверки маршруты падают с 500 при g.current_user.id.
        if u is None:
            g.current_user = None
            g.current_user_level = 0
            return jsonify({"error": ERROR_NO_ACCESS}), 401

        g.current_user = u
        g.current_user_level = u.level

        return f(*args, **kwargs)

    return decorated


def require_level(min_level: int):
    """Требует уровень пользователя >= min_level (1=user, 2=operator, 3=super_admin).

    При открытом доступе (Config.OPEN_ACCESS) проверка уровня не действует:
    доступно всё, что открыто авторизованному пользователю.
    """

    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            if not Config.OPEN_ACCESS:
                level = getattr(g, "current_user_level", 1)
                if level < min_level:
                    return jsonify({"error": ERROR_NO_RIGHTS}), 403
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
            return jsonify({"error": ERROR_NO_RIGHTS}), 403
        return f(*args, **kwargs)

    return decorated


def require_can_clear_logs(f):
    """Доступ к удалению аудит-логов (только уровень 3)."""

    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        level = getattr(g, "current_user_level", 1)
        if level != 3:
            return jsonify({"error": ERROR_NO_RIGHTS}), 403
        return f(*args, **kwargs)

    return decorated