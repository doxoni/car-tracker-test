# -*- coding: utf-8 -*-
"""Уведомления: о добавлении обслуживания сообщение не присылается.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_notifications.py -q
"""

import pytest


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


def test_service_does_not_notify_admins(app_context, monkeypatch):
    """О добавлении обслуживания уведомление не отправляется."""
    from app import db
    from app.models import ServiceEntry, User, Vehicle

    sent = []
    monkeypatch.setattr(
        "app.notifications.send_message",
        lambda chat_id, text: sent.append((chat_id, text)),
    )

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
        service = ServiceEntry(
            vehicle_id=vehicle.id,
            amount=1500.0,
            description="Замена масла",
            odometer=100000,
            status="pending",
            submitted_by=user.id,
        )
        db.session.add(service)
        db.session.commit()

        from app.notifications import notify_pending_entry

        notify_pending_entry("service", service)

    assert sent == []


def test_fuel_still_notifies_admins(app_context, monkeypatch):
    """О добавлении заправки уведомление админам по-прежнему приходит."""
    from app import db
    from app.models import FuelEntry, User, Vehicle

    sent = []
    monkeypatch.setattr(
        "app.notifications.send_message",
        lambda chat_id, text: sent.append((chat_id, text)),
    )

    with app_context.app_context():
        user = User(tg_id=111, level=1, is_whitelisted=True)
        admin = User(tg_id=999, level=3, is_whitelisted=True)
        db.session.add_all([user, admin])
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

        from app.notifications import notify_pending_entry

        notify_pending_entry("fuel", entry)

    assert len(sent) == 1
    assert sent[0][0] == 999
