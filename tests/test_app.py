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
    """Health check отвечает без авторизации."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_miniapp_page(client):
    """Страница Mini App отдаётся по /app и /."""
    for path in ("/app", "/"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"Car Tracker" in response.data


def test_static_files(client):
    """CSS и JS Mini App доступны."""
    response = client.get("/static/css/style.css")
    assert response.status_code == 200


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
