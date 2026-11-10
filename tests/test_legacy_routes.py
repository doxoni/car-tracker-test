# -*- coding: utf-8 -*-
"""Проверка API старой системы (app/legacy_routes.py).

Старая GUI ждёт ответы строго в старом формате: успех - {"ok": true, ...},
ошибка - {"ok": false, "error": "текст"}. Тест проверяет этот контракт
и то, что уровни доступа работают так же, как в старом проекте.

Запуск:
    python -m pytest tests/test_legacy_routes.py -q
"""

import os
import tempfile

import pytest

# Тесты работают на временной SQLite, чтобы не трогать рабочую БД.
_TMP_DB = os.path.join(tempfile.gettempdir(), "car_tracker_legacy_routes.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["DEV_MODE"] = "true"
os.environ["DEV_USER_ID"] = "1"


@pytest.fixture()
def app():
    """Приложение на временной SQLite с админом по умолчанию."""
    from app import create_app, db

    application = create_app()
    with application.app_context():
        db.drop_all()
        db.create_all()
        _make_user(3)
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """Клиент тестового сервера."""
    return app.test_client()


def _make_user(level: int):
    """Пользователь с нужным уровнем доступа.

    В локальном режиме сервер смотрит на DEV_USER_ID, поэтому работаем
    под этим номером.
    """
    from app import db
    from app.models import User

    user = User.query.filter_by(tg_id=1).first()
    if user is None:
        user = User(tg_id=1, level=level)
        db.session.add(user)
    else:
        user.level = level
    db.session.commit()
    return user


def test_cars_answer_has_old_format(client, app):
    """Список фур отдаётся в старом формате."""
    from app import db
    from app.models import Vehicle

    with app.app_context():
        user = _make_user(3)
        db.session.add(
            Vehicle(
                plate="АА1111АА",
                brand="MAN",
                driver_id=user.id,
                current_mileage=100000,
                status="active",
            )
        )
        db.session.commit()

    response = client.get("/api/cars")
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert "cars" in data
    assert "level" in data
    assert "is_admin" in data
    assert data["cars"][0]["plate"] == "АА1111АА"


def test_catalog_has_items(client):
    """Каталог работ отдаётся списком."""
    data = client.get("/api/catalog").get_json()

    assert data["ok"] is True
    assert len(data["items"]) > 0
    assert "title" in data["items"][0]


def test_barrel_balance_counts_fill_as_expense(client, app):
    """Заправка из бочки уменьшает остаток, долив - увеличивает."""
    from app import db
    from app.models import FuelBarrel, FuelInflow, FuelOutflow, Vehicle

    with app.app_context():
        user = _make_user(3)
        vehicle = Vehicle(
            plate="АА1111АА",
            brand="MAN",
            driver_id=user.id,
            current_mileage=100000,
            status="active",
        )
        db.session.add(vehicle)
        db.session.commit()

        barrel = FuelBarrel(
            name="Бочка дизель",
            fuel_type="diesel",
            capacity_liters=30000.0,
            current_liters=0.0,
        )
        db.session.add(barrel)
        db.session.commit()

        db.session.add(
            FuelInflow(
                barrel_id=barrel.id,
                liters=1000.0,
                price_per_liter=40.0,
                total=40000.0,
            )
        )
        db.session.add(
            FuelOutflow(
                barrel_id=barrel.id,
                vehicle_id=vehicle.id,
                liters=300.0,
                cost_per_liter=40.0,
                total=12000.0,
            )
        )
        db.session.commit()

    data = client.get("/api/barrel").get_json()

    assert data["ok"] is True
    assert data["balance"]["diesel"] == 700.0
    actions = sorted(item["action"] for item in data["items"])
    assert actions == ["add", "fill"]


def test_report_text_is_file(client, app):
    """Выгрузка истории отдаётся текстовым файлом."""
    response = client.get("/api/report")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "text/plain" in response.headers["Content-Type"]
    assert "attachment" in response.headers.get("Content-Disposition", "")
    assert body


def test_month_costs_answer(client):
    """Итоги месяца - в старом формате."""
    data = client.get("/api/month-costs").get_json()

    assert data["ok"] is True
    assert "costs" in data
    assert "totals" in data["costs"]
    assert "total" in data["costs"]["totals"]


def test_error_answer_has_message(client, app):
    """Ошибка отдаётся как {"ok": false, "error": "текст"}."""
    from app import db
    from app.models import Vehicle

    with app.app_context():
        user = _make_user(3)
        db.session.add(
            Vehicle(
                plate="АА1111АА",
                brand="MAN",
                driver_id=user.id,
                current_mileage=100000,
                status="active",
            )
        )
        db.session.commit()

    response = client.post("/api/cars/999999/mileage", json={"mileage": 1})
    data = response.get_json()

    assert response.status_code == 404
    assert data["ok"] is False
    assert data["error"]


def test_level_one_cannot_manage_barrel(client, app):
    """Уровень 1 не управляет бочками."""
    from app import db

    with app.app_context():
        _make_user(1)

    response = client.post(
        "/api/barrel",
        json={"fuel_type": "diesel", "action": "add", "liters": 100},
    )

    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_level_one_cannot_see_costs(client, app):
    """Затраты доступны с 2 уровня, водитель их не видит."""
    from app import db

    with app.app_context():
        _make_user(1)

    response = client.get("/api/month-costs")

    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_level_two_can_see_costs(client, app):
    """Оператор (2 уровень) затраты видит."""
    from app import db

    with app.app_context():
        _make_user(2)

    response = client.get("/api/month-costs")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_level_two_cannot_see_reports(client, app):
    """Отчёты доступны только с 3 уровня."""
    from app import db

    with app.app_context():
        _make_user(2)

    response = client.get("/api/reports")

    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_level_one_cannot_see_reports(client, app):
    """Водитель (1 уровень) список отчётов не получает."""
    from app import db

    with app.app_context():
        _make_user(1)

    response = client.get("/api/reports")

    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_level_three_can_see_reports(client, app):
    """Суперадмин (3 уровень) отчёты видит."""
    from app import db

    with app.app_context():
        _make_user(3)

    response = client.get("/api/reports")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_level_one_sees_no_cars_without_search(client, app):
    """Водитель без поиска не видит список машин."""
    from app import db
    from app.models import Vehicle

    with app.app_context():
        user = _make_user(1)
        db.session.add(
            Vehicle(
                plate="АА1111АА",
                brand="MAN",
                driver_id=user.id,
                current_mileage=100000,
                status="active",
            )
        )
        db.session.commit()

    response = client.get("/api/cars")

    assert response.status_code == 200
    assert response.get_json()["cars"] == []


def test_level_one_sees_cars_found_by_search(client, app):
    """Водитель видит ту машину, которую нашёл поиском."""
    from app import db
    from app.models import Vehicle

    with app.app_context():
        user = _make_user(1)
        db.session.add(
            Vehicle(
                plate="АА1111АА",
                brand="MAN",
                driver_id=user.id,
                current_mileage=100000,
                status="active",
            )
        )
        db.session.commit()

    response = client.get("/api/cars?q=1111")
    data = response.get_json()

    assert response.status_code == 200
    assert len(data["cars"]) == 1
    assert data["cars"][0]["plate"] == "АА1111АА"


def test_level_three_sees_all_cars_without_search(client, app):
    """Суперадмин видит все машины и без поиска."""
    from app import db
    from app.models import Vehicle

    with app.app_context():
        user = _make_user(3)
        db.session.add(
            Vehicle(
                plate="АА1111АА",
                brand="MAN",
                driver_id=user.id,
                current_mileage=100000,
                status="active",
            )
        )
        db.session.commit()

    response = client.get("/api/cars")

    assert response.status_code == 200
    assert len(response.get_json()["cars"]) == 1


def _add_vehicle(app, plate: str = "АА1111АА", brand: str = "MAN"):
    """Создать активную фуру от имени администратора."""
    from app import db
    from app.models import Vehicle

    with app.app_context():
        user = _make_user(3)
        vehicle = Vehicle(
            plate=plate,
            brand=brand,
            driver_id=user.id,
            current_mileage=100000,
            status="active",
        )
        db.session.add(vehicle)
        db.session.commit()
        return vehicle.id


def test_claim_saves_car_to_my_list(client, app):
    """Найденная по поиску машина сохраняется в список водителя."""
    from app import db
    from app.models import UserVehicle

    vehicle_id = _add_vehicle(app)
    with app.app_context():
        _make_user(1)

    response = client.post("/api/cars/%d/claim" % vehicle_id)
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True

    with app.app_context():
        link = UserVehicle.query.filter_by(vehicle_id=vehicle_id).first()
        assert link is not None


def test_claimed_car_visible_without_search(client, app):
    """После сохранения машина видна в списке без поиска."""
    vehicle_id = _add_vehicle(app)
    with app.app_context():
        _make_user(1)

    client.post("/api/cars/%d/claim" % vehicle_id)

    response = client.get("/api/cars")
    data = response.get_json()

    assert response.status_code == 200
    assert len(data["cars"]) == 1
    assert data["cars"][0]["id"] == vehicle_id
    assert data["cars"][0]["claimed"] is True


def test_claim_is_idempotent(client, app):
    """Повторное добавление той же машины не дублирует запись."""
    from app import db
    from app.models import UserVehicle

    vehicle_id = _add_vehicle(app)
    with app.app_context():
        _make_user(1)

    client.post("/api/cars/%d/claim" % vehicle_id)
    response = client.post("/api/cars/%d/claim" % vehicle_id)

    assert response.status_code == 200
    with app.app_context():
        assert UserVehicle.query.filter_by(vehicle_id=vehicle_id).count() == 1


def test_unclaim_removes_car_from_list(client, app):
    """Машину можно убрать из своего списка."""
    from app import db
    from app.models import UserVehicle

    vehicle_id = _add_vehicle(app)
    with app.app_context():
        _make_user(1)

    client.post("/api/cars/%d/claim" % vehicle_id)
    response = client.delete("/api/cars/%d/claim" % vehicle_id)

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    with app.app_context():
        assert UserVehicle.query.filter_by(vehicle_id=vehicle_id).count() == 0
    assert client.get("/api/cars").get_json()["cars"] == []


def test_claim_unknown_car_returns_404(client, app):
    """Незначимая машина - ошибка 404 в старом формате."""
    with app.app_context():
        _make_user(1)

    response = client.post("/api/cars/999999/claim")
    data = response.get_json()

    assert response.status_code == 404
    assert data["ok"] is False
    assert data["error"]


def test_added_car_goes_to_my_list(client, app):
    """Добавленная самим машина сразу попадает в личный список."""
    from app import db
    from app.models import UserVehicle

    with app.app_context():
        _make_user(1)

    response = client.post(
        "/api/cars",
        json={"model": "MAN", "plate": "ВВ7777ВВ", "mileage": 100},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    with app.app_context():
        assert UserVehicle.query.filter_by(vehicle_id=data["id"]).count() == 1


