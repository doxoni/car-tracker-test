# -*- coding: utf-8 -*-
"""Вебхук Telegram.

Зачем он нужен: на бесплатном тарифе Render контейнер засыпает после
15 минут простоя и просыпается от входящего запроса. Telegram сам
шлёт обновления POST-запросом на этот адрес - значит сообщение в боте
"будит" сервис, и тот не тратит часы бесплатного тарифа попусту.

Адрес: POST /telegram/webhook
"""

import hmac

from flask import Blueprint, jsonify, request

bp = Blueprint("telegram", __name__, url_prefix="/telegram")

# Сколько ждём готовности бота после пробуждения контейнера, секунд.
# Telegram не ждёт ответ вебхука слишком долго - не успел бот за это
# время, отвечаем 503, и Telegram повторит доставку.
BOT_READY_TIMEOUT = 15


def _wait_for_bot(timeout: float = BOT_READY_TIMEOUT) -> bool:
    """Подождать, пока бот поднимется и будет готов принимать обновления.

    Контейнер после сна поднимается не мгновенно: пока идёт старт,
    бот ещё не готов. Telegram повторяет доставку при ответе 503,
    но лучше подождать тут - тогда ответ пользователю быстрее.
    """
    import time

    from app.bot_runner import bot_ready

    deadline = time.time() + timeout
    while time.time() < deadline:
        if bot_ready():
            return True
        time.sleep(0.5)
    return bot_ready()


@bp.post("/webhook")
def telegram_webhook():
    """Принять обновление от Telegram и передать его боту.

    Ответ 403 - если не совпал секрет (X-Telegram-Bot-Api-Secret-Token),
    503 - если бот ещё не готов принять обновление: Telegram повторит
    доставку позже.
    """
    from app.config import Config
    from app.bot_runner import bot_ready, enqueue_update, webhook_mode

    if not webhook_mode():
        return jsonify({"ok": False, "error": "webhook выключен"}), 404

    secret = (Config.TELEGRAM_WEBHOOK_SECRET or "").strip()
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or not hmac.compare_digest(provided, secret):
        return jsonify({"ok": False, "error": "неверный секрет"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "update_id" not in payload:
        return jsonify({"ok": False, "error": "пустое обновление"}), 400

    if not _wait_for_bot():
        # Контейнер только что проснулся - даём боту несколько секунд
        # на старт. Telegram повторит запрос при ответе 503.
        return jsonify({"ok": False, "error": "бот не готов"}), 503

    from telegram import Update

    from app.bot_runner import bot_app_instance

    bot = bot_app_instance()
    if bot is None:
        return jsonify({"ok": False, "error": "бот не готов"}), 503

    try:
        update = Update.de_json(payload, bot)
    except Exception:
        return jsonify({"ok": False, "error": "не удалось разобрать обновление"}), 400

    if not enqueue_update(update):
        return jsonify({"ok": False, "error": "бот не готов"}), 503

    return jsonify({"ok": True}), 200
