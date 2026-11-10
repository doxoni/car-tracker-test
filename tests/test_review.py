# -*- coding: utf-8 -*-
"""Проверка заявок в боте: команда /cheak и кнопки «принять/отклонить».

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_review.py -q

Настройки БД и DEV_MODE берутся из tests/conftest.py.
"""

import pytest

from bot.bot import _apply_review, _pending_entries  # noqa: E402


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    """В тестах в Telegram ничего не отправляем."""
    from app.config import Config

    monkeypatch.setattr(Config, "TELEGRAM_TOKEN", "")


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


def _add_pending_fuel(app, status="pending"):
    """Заправка, ждущая проверки."""
    from app import db
    from app.models import FuelEntry, User, Vehicle

    with app.app_context():
        user = User(tg_id=111, level=1, is_whitelisted=True)
        db.session.add(user)
        db.session.commit()
        vehicle = Vehicle(
            plate="АА1111АА",
            brand="MAN",
            driver_id=user.id,
            current_mileage=100000,
            status="active",
        )
        db.session.add(vehicle)
        db.session.commit()
        entry = FuelEntry(
            vehicle_id=vehicle.id,
            liters=100.0,
            price=40.0,
            amount=4000.0,
            odometer=100000,
            status=status,
            submitted_by=user.id,
        )
        db.session.add(entry)
        db.session.commit()
        return entry.id


def test_pending_entries_are_listed(app_context):
    """Заправка на проверке попадает в список."""
    entry_id = _add_pending_fuel(app_context)

    items = _pending_entries()

    assert len(items) == 1
    kind, listed_id, data = items[0]
    assert kind == "fuel"
    assert listed_id == entry_id
    assert data["amount"] == 4000.0


def test_approved_entry_leaves_the_list(app_context):
    """Принятая запись из списка уходит."""
    _add_pending_fuel(app_context)

    assert len(_pending_entries()) == 1
    assert _apply_review("fuel", 1, True, 222) is not None
    assert _pending_entries() == []


def test_rejected_entry_leaves_the_list(app_context):
    """Отклонённая запись тоже уходит из списка."""
    _add_pending_fuel(app_context)

    result = _apply_review("fuel", 1, False, 222)

    assert result is not None
    assert _pending_entries() == []


def test_review_of_unknown_entry_returns_none(app_context):
    """Проверять нечего — возвращаем None."""
    assert _apply_review("fuel", 999, True, 222) is None


def test_approved_entry_counts_in_totals(app_context):
    """После принятия заправка попадает в счётчики машины."""
    from app import db
    from app.models import FuelEntry, User, Vehicle
    from app.legacy_routes import _car_summary

    with app_context.app_context():
        user = User(tg_id=111, level=1, is_whitelisted=True)
        db.session.add(user)
        db.session.commit()
        vehicle = Vehicle(
            plate="АА1111АА",
            brand="MAN",
            driver_id=user.id,
            current_mileage=100000,
            status="active",
        )
        db.session.add(vehicle)
        db.session.commit()
        entry = FuelEntry(
            vehicle_id=vehicle.id,
            liters=100.0,
            price=40.0,
            amount=4000.0,
            odometer=100000,
            status="pending",
            submitted_by=user.id,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id
        vehicle_id = vehicle.id

    assert _apply_review("fuel", entry_id, True, 222) is not None

    with app_context.app_context():
        db.session.expire_all()
        vehicle = db.session.get(Vehicle, vehicle_id)
        summary = _car_summary(vehicle)
        assert summary["fuel_count"] == 1
        assert summary["total_fuel_amount"] == 4000.0


def test_bot_registers_check_commands(monkeypatch):
    """Бот слушает команду /cheak (и /check как синоним)."""
    from app.config import Config

    monkeypatch.setattr(Config, "TELEGRAM_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setattr("bot.bot.TELEGRAM_TOKEN", "123456:TESTTOKEN")

    from bot.bot import build_app

    application = build_app()
    commands = set()
    for handler in application.handlers[0]:
        for group in getattr(handler, "commands", []):
            commands.add(group)

    assert "cheak" in commands
    assert "check" in commands
