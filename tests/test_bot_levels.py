# -*- coding: utf-8 -*-
"""Тесты команд бота для выдачи уровней доступа.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_bot_levels.py -q

Настройки БД и DEV_MODE берутся из tests/conftest.py.
"""

import pytest

from bot.bot import _parse_admin_args, _set_level  # noqa: E402


@pytest.fixture()
def app_context():
    """Чистая БД на время теста."""
    from app import create_app, db

    application = create_app()
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def test_parse_admin_args_add_with_level():
    """Форма /admin 2 add 123456 разбирается правильно."""
    action, level, user_id = _parse_admin_args(["2", "add", "123456"])
    assert action == "add"
    assert level == 2
    assert user_id == 123456


def test_parse_admin_args_reversed_order():
    """Форма /admin add 123456 2 тоже понимается."""
    action, level, user_id = _parse_admin_args(["add", "123456", "2"])
    assert action == "add"
    assert level == 2
    assert user_id == 123456


def test_parse_admin_args_list():
    """Команда /admin list распознаётся."""
    action, level, user_id = _parse_admin_args(["list"])
    assert action == "list"
    assert level is None
    assert user_id is None


def test_parse_admin_args_del():
    """Команда снятия уровня распознаётся."""
    action, level, user_id = _parse_admin_args(["1", "del", "999"])
    assert action == "del"
    assert level == 1
    assert user_id == 999


def test_set_level_creates_user(app_context):
    """Новому человеку уровень выдаётся, и он попадает в базу."""
    from app import db
    from app.models import User

    action = _set_level(123456, 2)
    assert "Создан" in action

    with app_context.app_context():
        user = User.query.filter_by(tg_id=123456).first()
        assert user is not None
        assert user.level == 2
        assert user.is_whitelisted is True


def test_set_level_updates_existing_user(app_context):
    """Повторная выдача меняет уровень существующего человека."""
    from app import db
    from app.models import User

    with app_context.app_context():
        db.session.add(User(tg_id=555, level=1, is_whitelisted=True))
        db.session.commit()

    action = _set_level(555, 3)
    assert "Обновлён" in action

    with app_context.app_context():
        user = User.query.filter_by(tg_id=555).first()
        assert user.level == 3


def test_bot_registers_level_commands(monkeypatch):
    """Бот слушает именно те команды, что нужны."""
    from app.config import Config

    monkeypatch.setattr(Config, "TELEGRAM_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setattr("bot.bot.TELEGRAM_TOKEN", "123456:TESTTOKEN")

    from bot.bot import build_app

    application = build_app()
    commands = set()
    for handler in application.handlers[0]:
        for group in handler.commands:
            commands.add(group)

    assert "yuser_1" in commands
    assert "admunus2" in commands
    assert "fraeadmin3" in commands
    assert "admin" in commands
    # Старых названий быть не должно - команды нестандартные.
    assert "admin2" not in commands
    assert "admin3" not in commands
