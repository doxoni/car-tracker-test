# -*- coding: utf-8 -*-
"""Проверка вебхука Telegram.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_webhook.py -q

Настройки БД и DEV_MODE берутся из tests/conftest.py.
"""

import pytest


@pytest.fixture()
def client(monkeypatch):
    """Клиент Flask с включённым режимом webhook."""
    from app import create_app
    from app.config import Config

    monkeypatch.setattr(Config, "TELEGRAM_MODE", "webhook")
    monkeypatch.setattr(Config, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    application = create_app()
    with application.test_client() as test_client:
        yield test_client


def test_webhook_rejects_wrong_secret(client):
    """С чужим секретом вебхук не принимает обновления."""
    response = client.post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )

    assert response.status_code == 403


def test_webhook_requires_secret(client):
    """Без заголовка с секретом вебхук не принимает обновления."""
    response = client.post("/telegram/webhook", json={"update_id": 1})

    assert response.status_code == 403


def test_webhook_rejects_empty_update(client):
    """Пустое обновление - ошибка запроса, а не 403."""
    response = client.post(
        "/telegram/webhook",
        json={},
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )

    assert response.status_code == 400


def test_webhook_accepts_update(client, monkeypatch):
    """Обновление с правильным секретом попадает в очередь бота."""
    from app import bot_runner

    received = []

    def _fake_enqueue(update):
        received.append(update)
        return True

    monkeypatch.setattr(bot_runner, "bot_ready", lambda: True)
    monkeypatch.setattr(bot_runner, "bot_app_instance", lambda: _FakeBot())
    monkeypatch.setattr(bot_runner, "enqueue_update", _fake_enqueue)

    response = client.post(
        "/telegram/webhook",
        json={
            "update_id": 42,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 123, "type": "private"},
                "text": "Привет",
            },
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )

    assert response.status_code == 200
    assert len(received) == 1
    assert received[0].update_id == 42


def test_webhook_is_not_registered_in_polling_mode(monkeypatch):
    """В режиме опроса вебхук не работает."""
    from app import create_app
    from app.config import Config

    monkeypatch.setattr(Config, "TELEGRAM_MODE", "polling")
    monkeypatch.setattr(Config, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    application = create_app()
    with application.test_client() as test_client:
        response = test_client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )

    assert response.status_code == 404


class _FakeBot:
    """Заглушка бота: разбор обновления её не касается."""

    def get_id(self):
        return 1


def test_bot_app_is_stored_globally():
    """Приложение и цикл бота должны быть глобальными.

    Если поток бота присвоит их как локальные переменные, вебхук не
    найдёт бота и будет отвечать 503.
    """
    import inspect

    from app import bot_runner

    source = inspect.getsource(bot_runner.start_bot_thread)
    run_function = source.split("def _run():", 1)[1]
    globals_line = [
        line.strip()
        for line in run_function.splitlines()
        if line.strip().startswith("global ")
    ]
    assert globals_line, "в _run нет global - бот не найдётся в вебхуке"
    declared = " ".join(globals_line)
    assert "_bot_app" in declared
    assert "_bot_loop" in declared


def test_enqueue_update_needs_running_loop(monkeypatch):
    """Без работающего цикла обновление принять нельзя."""
    from app import bot_runner

    monkeypatch.setattr(bot_runner, "_bot_app", None)
    monkeypatch.setattr(bot_runner, "_bot_loop", None)

    assert bot_runner.enqueue_update(object()) is False


def test_enqueue_update_puts_into_queue(monkeypatch):
    """Обновление попадает в очередь бота."""
    import asyncio
    import threading
    import time

    from app import bot_runner

    loop = asyncio.new_event_loop()
    queue = asyncio.Queue()

    class FakeApp:
        update_queue = queue

    monkeypatch.setattr(bot_runner, "_bot_app", FakeApp())
    monkeypatch.setattr(bot_runner, "_bot_loop", loop)

    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        assert bot_runner.enqueue_update("обновление") is True
        deadline = time.time() + 5
        while time.time() < deadline and queue.empty():
            time.sleep(0.05)
        assert queue.get_nowait() == "обновление"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
