# -*- coding: utf-8 -*-
"""Тесты понятных текстов ошибок API.

Раньше пользователь Mini App видел английские коды ("unauthorized",
"forbidden", "missing plate"), теперь - русские фразы, которые ещё и
переводятся на украинский.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_error_messages.py -q

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


def test_error_texts_are_russian_constants():
    """Тексты ошибок доступа заданы по-русски, а не кодами."""
    from app.auth import ERROR_NO_ACCESS, ERROR_NO_RIGHTS

    assert ERROR_NO_ACCESS == "нет доступа"
    assert ERROR_NO_RIGHTS == "недостаточно прав"


def test_no_access_returns_russian_text(client):
    """Нет авторизации - понятный русский текст вместо "unauthorized"."""
    response = client.get("/api/vehicles")
    assert response.status_code == 401
    data = response.get_json()
    assert data["error"] == "нет доступа"
    assert "unauthorized" not in data["error"]


def test_no_rights_returns_russian_text(client, monkeypatch):
    """Не хватает прав - понятный русский текст вместо "forbidden"."""
    from app import db
    from app.config import Config
    from app.models import User

    monkeypatch.setattr(Config, "OPEN_ACCESS", False)
    with client.application.app_context():
        db.session.add(User(tg_id=1, level=1, is_whitelisted=True))
        db.session.commit()

    # Создание фуры доступно с уровня 2, у водителя его нет.
    response = client.post("/api/vehicles", json={"plate": "AA123", "brand": "MAN", "driver_id": 1})
    assert response.status_code == 403
    assert response.get_json()["error"] == "недостаточно прав"


def test_missing_field_returns_russian_text(client, monkeypatch):
    """Не хватает поля - сообщение по-русски, а не "missing plate"."""
    from app import db
    from app.config import Config
    from app.models import User

    monkeypatch.setattr(Config, "OPEN_ACCESS", False)
    with client.application.app_context():
        db.session.add(User(tg_id=1, level=3, is_whitelisted=True))
        db.session.commit()

    response = client.post("/api/vehicles", json={"brand": "MAN"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "нужен номер фуры"


def test_duplicate_plate_returns_russian_text(client, monkeypatch):
    """Повторный номер - сообщение по-русски."""
    from app import db
    from app.config import Config
    from app.models import User, Vehicle

    monkeypatch.setattr(Config, "OPEN_ACCESS", False)
    with client.application.app_context():
        user = User(tg_id=1, level=3, is_whitelisted=True)
        db.session.add(user)
        db.session.commit()
        db.session.add(Vehicle(plate="AA123", brand="MAN", driver_id=user.id, status="active"))
        db.session.commit()

    response = client.post("/api/vehicles", json={"plate": "AA123", "brand": "MAN", "driver_id": 1})
    assert response.status_code == 400
    assert response.get_json()["error"] == "такая фура уже есть в списке"


def test_ukrainian_translation_of_error(client):
    """Русский текст ошибки переводится на украинский."""
    from app.i18n import t
    from app.auth import ERROR_NO_ACCESS, ERROR_NO_RIGHTS

    assert t(ERROR_NO_ACCESS, "uk") != ERROR_NO_ACCESS
    assert t(ERROR_NO_RIGHTS, "uk") != ERROR_NO_RIGHTS
