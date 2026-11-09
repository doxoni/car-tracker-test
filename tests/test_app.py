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


def test_health_contains_night_block(client):
    """/api/health показывает состояние ночной паузы."""
    response = client.get("/api/health")
    assert response.status_code == 200
    night = response.get_json()["night"]
    assert night["tz"] == "Europe/Kyiv"
    assert night["start_hour"] == 2
    assert night["end_hour"] == 5
    assert isinstance(night["active"], bool)
    assert night["local_time"]
    assert night["next_change"]


def test_is_night_inside_window():
    """Внутри окна 02:00-05:00 по Киеву - ночь."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.night_mode import is_night

    kyiv = ZoneInfo("Europe/Kyiv")
    assert is_night(datetime(2026, 1, 15, 2, 0, tzinfo=kyiv)) is True
    assert is_night(datetime(2026, 1, 15, 3, 30, tzinfo=kyiv)) is True
    assert is_night(datetime(2026, 1, 15, 4, 59, tzinfo=kyiv)) is True


def test_is_night_outside_window():
    """Вне окна - не ночь. Границы: 02:00 входит, 05:00 - уже нет."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.night_mode import is_night

    kyiv = ZoneInfo("Europe/Kyiv")
    assert is_night(datetime(2026, 1, 15, 1, 59, tzinfo=kyiv)) is False
    assert is_night(datetime(2026, 1, 15, 5, 0, tzinfo=kyiv)) is False
    assert is_night(datetime(2026, 1, 15, 12, 0, tzinfo=kyiv)) is False
    assert is_night(datetime(2026, 1, 15, 0, 30, tzinfo=kyiv)) is False


def test_is_night_converts_utc_to_kyiv():
    """Время в UTC переводится в киевское: 00:30 UTC зимой = 02:30 Киева."""
    from datetime import datetime, timezone

    from app.night_mode import is_night

    # Зима: Киев на 2 часа впереди UTC. 00:30 UTC -> 02:30 киевского времени.
    assert is_night(datetime(2026, 1, 15, 0, 30, tzinfo=timezone.utc)) is True
    # За час до полуночи UTC ещё 01:30 киевского времени - не ночь.
    assert is_night(datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)) is False
    # Лето: Киев на 3 часа впереди UTC. 23:30 UTC -> 02:30 киевского.
    assert is_night(datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc)) is True


def test_night_info_reports_change_time():
    """В night_info есть местное время и ближайшая смена окна."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.night_mode import night_info

    kyiv = ZoneInfo("Europe/Kyiv")
    info = night_info(datetime(2026, 1, 15, 2, 30, tzinfo=kyiv))
    assert info["active"] is True
    assert info["local_time"].startswith("2026-01-15 02:30")
    # Ближайшая смена - конец окна в 05:00 того же дня.
    assert info["next_change"].startswith("2026-01-15 05:00")

    info_day = night_info(datetime(2026, 1, 15, 12, 0, tzinfo=kyiv))
    assert info_day["active"] is False
    # Ближайшая смена - начало окна в 02:00 следующего дня.
    assert info_day["next_change"].startswith("2026-01-16 02:00")


def test_bot_does_not_start_at_night(monkeypatch):
    """Ночью бот не стартует: в состоянии статус night_mode."""
    from app import bot_runner
    from app.config import Config

    monkeypatch.setattr(Config, "TELEGRAM_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setattr(bot_runner, "bot_enabled", lambda: True)
    monkeypatch.setattr(Config, "NIGHT_MODE_ENABLED", True)
    monkeypatch.setattr(Config, "NIGHT_START_HOUR", 2)
    monkeypatch.setattr(Config, "NIGHT_END_HOUR", 5)
    # Ночь: 03:00 по Киеву.
    monkeypatch.setattr("app.night_mode.is_night", lambda *a, **k: True)
    # Сторож ночного окна в тесте не нужен.
    monkeypatch.setattr(bot_runner, "_ensure_night_watchdog", lambda: None)

    thread = bot_runner.ensure_bot_started("test")
    assert thread is None
    assert bot_runner.BOT_STATE["status"] == "night_mode"
    assert "ночная пауза" in bot_runner.BOT_STATE["stage"]


def test_night_sleep_window_by_kyiv_time():
    """Скрипт ночной паузы считает ночь по киевскому времени."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import night_sleep

    kyiv = ZoneInfo("Europe/Kyiv")
    assert night_sleep.is_night(datetime(2026, 1, 15, 2, 30, tzinfo=kyiv)) is True
    assert night_sleep.is_night(datetime(2026, 1, 15, 5, 0, tzinfo=kyiv)) is False
    assert night_sleep.is_night(datetime(2026, 1, 15, 12, 0, tzinfo=kyiv)) is False


def test_wait_until_morning_skips_when_not_suspended(monkeypatch):
    """Если сервис не усыплён, ждать до утра не нужно."""
    import night_sleep

    monkeypatch.setattr(night_sleep, "service_state", lambda key: {"suspended": "not_suspended"})
    called = []
    monkeypatch.setattr(night_sleep, "cmd_resume", lambda key: called.append(key) or 0)

    assert night_sleep.cmd_wait_until_morning("test-key") == 0
    assert called == []


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
        # Основной интерфейс - старый (экран списка фур и кнопка затрат).
        assert b"screen-cars" in response.data
        assert b"btn-costs" in response.data


def test_miniapp_new_page(client):
    """Новый интерфейс остался доступен по /new."""
    response = client.get("/new")
    assert response.status_code == 200
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
