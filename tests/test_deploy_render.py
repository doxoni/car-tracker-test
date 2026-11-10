# -*- coding: utf-8 -*-
"""Тесты безопасности деплоя на Render.

Случай, который уже стоил работы: deploy_render.py ставил сервису токен
бота из файла .env. Токен был отозван, поэтому и бот, и Mini App перестали
работать. Теперь:
  - токен бота в .env не читается;
  - переменные, заданные в панели Render, не стираются при деплое;
  - нерабочий токен на сервер не попадает.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_deploy_render.py -q
"""

import os

import pytest


@pytest.fixture()
def deploy(tmp_path, monkeypatch):
    """Модуль deploy_render с корнем в временной папке."""
    import deploy_render

    monkeypatch.setattr(deploy_render, "ROOT", tmp_path)
    return deploy_render


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_dotenv_token_is_ignored(deploy, tmp_path):
    """Токен бота из .env не берётся - он может быть отозванным."""
    _write(tmp_path / ".env", "TELEGRAM_TOKEN=123:OLD\nOPEN_ACCESS=1\n")
    _write(tmp_path / "render_env.txt", "ADMIN_TELEGRAM_ID=42\n")

    values = deploy.read_render_env()
    assert "TELEGRAM_TOKEN" not in values
    assert values["OPEN_ACCESS"] == "1"


def test_token_from_render_env_is_used(deploy, tmp_path):
    """Токен из render_env.txt (его ставит set_bot_token.cmd) берётся."""
    _write(tmp_path / "render_env.txt", "TELEGRAM_TOKEN=123:GOOD\n")

    values = deploy.read_render_env()
    assert values["TELEGRAM_TOKEN"] == "123:GOOD"


def test_only_allowed_vars_are_sent(deploy, tmp_path):
    """На сервер уходят только нужные переменные."""
    _write(tmp_path / ".env", "SECRET_KEY=abc\nOPEN_ACCESS=1\n")
    _write(tmp_path / "render_env.txt", "WHITELISTED_TELEGRAM_IDS=7\n")

    values = deploy.read_render_env()
    assert set(values) <= {
        "TELEGRAM_TOKEN",
        "ADMIN_TELEGRAM_ID",
        "WHITELISTED_TELEGRAM_IDS",
        "OPEN_ACCESS",
        "TELEGRAM_MODE",
        "TELEGRAM_WEBHOOK_SECRET",
    }
    assert "SECRET_KEY" not in values


def test_set_env_keeps_server_variables(deploy, monkeypatch):
    """PUT в Render заменяет весь список - скрипт накладывает новые поверх старых."""
    existing = {"TELEGRAM_TOKEN": "123:ON_SERVER", "MY_CUSTOM": "keep-me"}
    sent = {}

    monkeypatch.setattr(deploy, "get_env_vars", lambda service_id, key: dict(existing))
    monkeypatch.setattr(
        deploy,
        "api",
        lambda method, path, key, payload=None: sent.update(
            {"method": method, "path": path, "payload": payload}
        ),
    )

    deploy.set_env("srv-1", "key", {"DATABASE_URL": "postgresql://..."})

    assert sent["method"] == "PUT"
    assert sent["path"] == "/services/srv-1/env-vars"
    sent_map = {item["key"]: item["value"] for item in sent["payload"]}
    assert sent_map["TELEGRAM_TOKEN"] == "123:ON_SERVER"
    assert sent_map["MY_CUSTOM"] == "keep-me"
    assert sent_map["DATABASE_URL"] == "postgresql://..."


def test_get_env_vars_parses_list(monkeypatch):
    """Ответ Render со списком переменных разбирается правильно."""
    import deploy_render

    payload = [
        {"cursor": "a", "envVar": {"key": "ONE", "value": "1"}},
        {"cursor": "b", "envVar": {"key": "TWO", "value": "2"}},
    ]
    monkeypatch.setattr(deploy_render, "api", lambda *args, **kwargs: payload)

    result = deploy_render.get_env_vars("srv-1", "key")
    assert result == {"ONE": "1", "TWO": "2"}


def test_check_token_rejects_garbage(monkeypatch):
    """Нерабочий токен не проходит проверку."""
    import deploy_render

    class FakeResponse:
        @staticmethod
        def json():
            return {"ok": False, "description": "Unauthorized"}

    monkeypatch.setattr(deploy_render.requests, "get", lambda *args, **kwargs: FakeResponse())
    assert deploy_render.check_token("123:BROKEN") is False
    assert deploy_render.check_token("") is False


def test_webhook_secret_is_generated(deploy, tmp_path):
    """Если секрета нет - он генерируется и попадает в значения."""
    values = deploy.ensure_webhook_secret({})

    secret = values.get("TELEGRAM_WEBHOOK_SECRET")
    assert secret
    assert len(secret) >= 20
    assert values.get("TELEGRAM_MODE") == "webhook"

    # Секрет должен сохраниться, чтобы при следующем деплое не сменился.
    env_file = tmp_path / "render_env.txt"
    assert env_file.exists()
    assert "TELEGRAM_WEBHOOK_SECRET" in env_file.read_text(encoding="utf-8")


def test_existing_webhook_secret_is_kept(deploy, tmp_path):
    """Готовый секрет не меняется - иначе Telegram перестанет доставлять."""
    values = deploy.ensure_webhook_secret(
        {"TELEGRAM_WEBHOOK_SECRET": "стабильный-секрет"}
    )

    assert values["TELEGRAM_WEBHOOK_SECRET"] == "стабильный-секрет"
    assert not (tmp_path / "render_env.txt").exists()
