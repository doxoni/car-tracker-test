# -*- coding: utf-8 -*-
"""Тесты уровней доступа при закрытом доступе (OPEN_ACCESS=0).

Уровни:
  1 - водитель: видит активные фуры, добавляет расходы (они ждут одобрения),
      видит только свои расходы, не управляет фурами и бочками;
  2 - оператор: всё, что делает водитель, плюс фуры, бочки, заправки;
  3 - суперадмин: всё, плюс одобрение расходов и аудит-логи.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_access_levels.py -q

Настройки БД и DEV_MODE берутся из tests/conftest.py.
"""

import pytest


@pytest.fixture()
def client():
    """Клиент Flask с чистой БД."""
    from app import create_app, db

    application = create_app()
    with application.app_context():
        db.drop_all()
        db.create_all()
    with application.test_client() as test_client:
        yield test_client
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def closed_access(monkeypatch):
    """Закрытый доступ: уровни действительно ограничивают права."""
    from app.config import Config

    monkeypatch.setattr(Config, "OPEN_ACCESS", False)
    return Config


def _make_user(app, tg_id: int, level: int):
    """Создать пользователя с нужным уровнем."""
    from app import db
    from app.models import User

    with app.app_context():
        user = User(tg_id=tg_id, level=level, is_whitelisted=True)
        db.session.add(user)
        db.session.commit()
        return user.id


def _make_vehicle(app, driver_id: int, status: str = "active"):
    """Создать фуру с нужным статусом."""
    from app import db
    from app.models import Vehicle

    with app.app_context():
        vehicle = Vehicle(
            plate=f"Т{status[:3].upper()}001",
            brand="MAN",
            driver_id=driver_id,
            status=status,
            current_mileage=1000,
        )
        db.session.add(vehicle)
        db.session.commit()
        return vehicle.id


def _act_as(monkeypatch, tg_id: int):
    """В DEV_MODE запросы идут от пользователя с этим Telegram ID."""
    from app.config import Config

    monkeypatch.setattr(Config, "DEV_USER_ID", tg_id)


def test_level1_adds_expense_for_active_vehicle(client, closed_access, monkeypatch):
    """Водитель (1) может добавить расход по активной фуре - расход ждёт одобрения."""
    user_id = _make_user(client.application, 1, 1)
    vehicle_id = _make_vehicle(client.application, user_id, "active")
    _act_as(monkeypatch, 1)

    response = client.post(
        "/api/expenses",
        json={
            "vehicle_id": vehicle_id,
            "category": "топливо",
            "amount": 1000,
            "date": "2026-11-09",
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.get_json()["status"] == "pending"


def test_level1_cannot_add_expense_for_archived_vehicle(
    client, closed_access, monkeypatch
):
    """Водитель (1) не может добавить расход по архивной фуре."""
    user_id = _make_user(client.application, 1, 1)
    vehicle_id = _make_vehicle(client.application, user_id, "archived")
    _act_as(monkeypatch, 1)

    response = client.post(
        "/api/expenses",
        json={
            "vehicle_id": vehicle_id,
            "category": "топливо",
            "amount": 1000,
            "date": "2026-11-09",
        },
    )
    assert response.status_code == 403


def test_level1_sees_only_own_expenses(client, closed_access, monkeypatch):
    """Водитель (1) видит в списке только свои расходы."""
    from app import db
    from app.models import Expense

    driver = _make_user(client.application, 1, 1)
    other = _make_user(client.application, 2, 2)
    vehicle_id = _make_vehicle(client.application, driver, "active")

    with client.application.app_context():
        db.session.add(
            Expense(
                vehicle_id=vehicle_id,
                category="топливо",
                amount=500,
                submitted_by=driver,
                status="approved",
            )
        )
        db.session.add(
            Expense(
                vehicle_id=vehicle_id,
                category="ремонт",
                amount=700,
                submitted_by=other,
                status="approved",
            )
        )
        db.session.commit()

    _act_as(monkeypatch, 1)
    response = client.get("/api/expenses")
    assert response.status_code == 200
    expenses = response.get_json()
    assert len(expenses) == 1
    assert expenses[0]["category"] == "топливо"


def test_level2_sees_all_expenses(client, closed_access, monkeypatch):
    """Оператор (2) видит все расходы."""
    from app import db
    from app.models import Expense

    driver = _make_user(client.application, 1, 1)
    other = _make_user(client.application, 2, 2)
    vehicle_id = _make_vehicle(client.application, driver, "active")

    with client.application.app_context():
        db.session.add(
            Expense(
                vehicle_id=vehicle_id,
                category="топливо",
                amount=500,
                submitted_by=driver,
                status="approved",
            )
        )
        db.session.add(
            Expense(
                vehicle_id=vehicle_id,
                category="ремонт",
                amount=700,
                submitted_by=other,
                status="approved",
            )
        )
        db.session.commit()

    _act_as(monkeypatch, 2)
    response = client.get("/api/expenses")
    assert response.status_code == 200
    assert len(response.get_json()) == 2


def test_level1_cannot_create_vehicle(client, closed_access, monkeypatch):
    """Водитель (1) не может завести фуру - это уровень оператора."""
    user_id = _make_user(client.application, 1, 1)
    _act_as(monkeypatch, 1)

    response = client.post(
        "/api/vehicles",
        json={"plate": "АА777АА", "brand": "MAN", "driver_id": user_id},
    )
    assert response.status_code == 403


def test_level2_can_create_vehicle(client, closed_access, monkeypatch):
    """Оператор (2) может завести фуру."""
    user_id = _make_user(client.application, 2, 2)
    _act_as(monkeypatch, 2)

    response = client.post(
        "/api/vehicles",
        json={"plate": "АА777АА", "brand": "MAN", "driver_id": user_id},
    )
    assert response.status_code == 201, response.get_data(as_text=True)


def test_level1_cannot_see_barrels(client, closed_access, monkeypatch):
    """Бочки - уровень оператора, водитель их не видит."""
    _make_user(client.application, 1, 1)
    _act_as(monkeypatch, 1)

    response = client.get("/api/barrels")
    assert response.status_code == 403


def test_only_level3_clears_logs(client, closed_access, monkeypatch):
    """Очистить аудит-логи может только суперадмин (3)."""
    _make_user(client.application, 2, 2)
    _act_as(monkeypatch, 2)

    denied = client.delete("/api/logs/history")
    assert denied.status_code == 403

    _make_user(client.application, 3, 3)
    _act_as(monkeypatch, 3)

    allowed = client.delete("/api/logs/history")
    assert allowed.status_code in (200, 404)


def test_open_access_ignores_levels(client, monkeypatch):
    """При открытом доступе (OPEN_ACCESS=1) уровни не ограничивают ничего."""
    from app.config import Config

    monkeypatch.setattr(Config, "OPEN_ACCESS", True)
    user_id = _make_user(client.application, 1, 1)
    _act_as(monkeypatch, 1)

    response = client.post(
        "/api/vehicles",
        json={"plate": "АА777АА", "brand": "MAN", "driver_id": user_id},
    )
    assert response.status_code == 201, response.get_data(as_text=True)
