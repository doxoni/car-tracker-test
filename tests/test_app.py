# -*- coding: utf-8 -*-
"""Тесты car-tracker: проверка API и страницы Mini App.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_app.py -q
"""

import os
import tempfile

import pytest

# Тесты работают на временной SQLite, чтобы не трогать рабочую БД.
_TMP_DB = os.path.join(tempfile.gettempdir(), "car_tracker_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["DEV_MODE"] = "true"
os.environ["DEV_USER_ID"] = "1"


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


def test_health(client):
    """Health check отвечает без авторизации (лёгкий, без запроса в БД)."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"


def test_health_db(client):
    """Отдельная проверка БД реально ходит в базу."""
    response = client.get("/api/health/db")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"


def test_miniapp_page(client):
    """Страница Mini App отдаётся по /app и /."""
    for path in ("/app", "/"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"Car Tracker" in response.data


def test_static_files(client):
    """CSS и JS Mini App доступны."""
    for path in ("/static/css/style.css", "/static/js/app.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(response.data) > 0, path


def test_miniapp_page_links_existing_static(client):
    """Все локальные ссылки со страницы Mini App реально отдаются."""
    import re

    page = client.get("/app").get_data(as_text=True)
    for url in re.findall(r'(?:href|src)="(/static/[^"]+)"', page):
        response = client.get(url)
        assert response.status_code == 200, url


def test_dashboard_requires_auth(client):
    """Без initData запрос к дашборду отклоняется."""
    response = client.get("/api/dashboard")
    assert response.status_code in (401, 403)


def test_dev_user_sees_dashboard(client):
    """В DEV_MODE пользователь из БД получает доступ к дашборду."""
    from app import db
    from app.models import User

    with client.application.app_context():
        db.session.add(User(tg_id=1, level=1, is_whitelisted=True))
        db.session.commit()

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.get_json()
    assert "total_amount" in data


def test_auth_verify_rejects_bad_signature(client):
    """Подпись Telegram не проходит - доступ не даём."""
    response = client.post("/api/auth/verify", json={"initData": "user=%7B%22id%22%3A1%7D&hash=abc"})
    assert response.status_code == 401


def test_auth_verify_creates_user_for_everyone(client, monkeypatch):
    """Любой, кто открыл приложение, получает профиль без белого списка."""
    import hashlib
    import hmac
    import json
    import time
    from urllib.parse import urlencode

    from app import db
    from app.config import Config
    from app.models import User

    token = "123456:TESTTOKEN"
    monkeypatch.setattr(Config, "TELEGRAM_TOKEN", token)

    # Считаем настоящую подпись Telegram тем же способом, что и сервер.
    fields = {
        "user": json.dumps({"id": 777001, "first_name": "Тест"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

    response = client.post("/api/auth/verify", json={"initData": urlencode(fields)})
    assert response.status_code == 200, response.get_data(as_text=True)

    data = response.get_json()
    assert data["ok"] is True
    assert data["user"]["level"] == 1

    with client.application.app_context():
        user_row = User.query.filter_by(tg_id=777001).first()
        assert user_row is not None
        assert user_row.level == 1


def test_open_access_allows_vehicle_creation(client):
    """При открытом доступе обычный пользователь может создать фуру."""
    from app import db
    from app.models import User

    with client.application.app_context():
        db.session.add(User(tg_id=1, level=1, is_whitelisted=True))
        db.session.commit()

    response = client.post(
        "/api/vehicles",
        json={"plate": "АА111АА", "brand": "MAN", "driver_id": 1},
    )
    assert response.status_code == 201, response.get_data(as_text=True)


def test_open_access_allows_expense_creation(client):
    """При открытом доступе расход создаётся сразу утверждённым."""
    from app import db
    from app.models import User

    with client.application.app_context():
        db.session.add(User(tg_id=1, level=1, is_whitelisted=True))
        db.session.commit()
        vehicle = client.post(
            "/api/vehicles",
            json={"plate": "ВВ222ВВ", "brand": "Volvo", "driver_id": 1},
        )
        vehicle_id = vehicle.get_json()["id"]

    response = client.post(
        "/api/expenses",
        json={
            "vehicle_id": vehicle_id,
            "category": "топливо",
            "amount": 1500,
            "date": "2026-11-08",
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.get_json()["status"] == "approved"
