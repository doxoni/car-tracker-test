# -*- coding: utf-8 -*-
"""Тест импорта данных из старой cars.db в новую базу.

Проверяем, что старые записи (фуры, водители, клиенты, заправки, ТО,
расходы, акты, наполнения бочек) попадают в новые таблицы без потерь.

Запуск:
    python -m pytest tests/test_import_legacy.py -q
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models import (  # noqa: E402
    User,
    Vehicle,
    Expense,
    FuelBarrel,
    FuelInflow,
    Driver,
    Customer,
    FuelEntry,
    ServiceEntry,
    Report,
)
from app import import_legacy  # noqa: E402


OLD_SCHEMA = """
CREATE TABLE cars (
    id INTEGER PRIMARY KEY, sync_id TEXT, user_id INTEGER, model TEXT,
    plate TEXT, mileage INTEGER, wialon_id INTEGER, is_active INTEGER,
    created_at TEXT
);
CREATE TABLE drivers (
    id INTEGER PRIMARY KEY, sync_id TEXT, user_id INTEGER, name TEXT,
    created_at TEXT
);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY, sync_id TEXT, user_id INTEGER, name TEXT,
    created_at TEXT
);
CREATE TABLE fuel (
    id INTEGER PRIMARY KEY, sync_id TEXT, car_id INTEGER, liters REAL,
    price REAL, amount REAL, odometer INTEGER, is_full INTEGER,
    location TEXT, created_at TEXT
);
CREATE TABLE services (
    id INTEGER PRIMARY KEY, sync_id TEXT, car_id INTEGER, amount REAL,
    description TEXT, details TEXT, odometer INTEGER, next_km INTEGER,
    next_date TEXT, created_at TEXT
);
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY, sync_id TEXT, car_id INTEGER, amount REAL,
    description TEXT, details TEXT, created_at TEXT
);
CREATE TABLE reports (
    id INTEGER PRIMARY KEY, sync_id TEXT, car_id INTEGER, client TEXT,
    mileage INTEGER, driver TEXT, created_at TEXT, driver_id INTEGER,
    customer_id INTEGER, paid INTEGER
);
CREATE TABLE barrel (
    id INTEGER PRIMARY KEY, sync_id TEXT, user_id INTEGER, fuel_type TEXT,
    action TEXT, car_plate TEXT, liters REAL, created_at TEXT
);
"""


@pytest.fixture
def app():
    """Приложение на временной SQLite."""
    application = create_app()
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def old_db(tmp_path):
    """Старая база с тестовыми данными."""
    path = tmp_path / "cars_old.db"
    connection = sqlite3.connect(path)
    connection.executescript(OLD_SCHEMA)
    connection.execute(
        "INSERT INTO cars (id, user_id, model, plate, mileage, wialon_id, is_active, created_at)"
        " VALUES (1, 1, 'MAN', 'AA1234BB', 100000, 777, 1, '2026-01-02 03:04:05')"
    )
    connection.execute(
        "INSERT INTO cars (id, user_id, model, plate, mileage, wialon_id, is_active, created_at)"
        " VALUES (2, 1, 'Volvo', 'CC5678DD', 50000, NULL, 0, '2026-01-03 03:04:05')"
    )
    connection.execute(
        "INSERT INTO drivers (id, user_id, name, created_at)"
        " VALUES (1, 1, 'Иван', '2026-01-01 00:00:00')"
    )
    connection.execute(
        "INSERT INTO customers (id, user_id, name, created_at)"
        " VALUES (1, 1, 'Клиент ООО', '2026-01-01 00:00:00')"
    )
    connection.execute(
        "INSERT INTO fuel (id, car_id, liters, price, amount, odometer, is_full, location, created_at)"
        " VALUES (1, 1, 300.0, 45.0, 13500.0, 100000, 1, 'АЗС', '2026-02-01 10:00:00')"
    )
    connection.execute(
        "INSERT INTO services (id, car_id, amount, description, details, odometer, next_km, next_date, created_at)"
        " VALUES (1, 1, 5000.0, 'Замена масла', 'масло 15w40', 100000, 10000, '2026-06-01 00:00:00',"
        " '2026-02-02 10:00:00')"
    )
    connection.execute(
        "INSERT INTO expenses (id, car_id, amount, description, details, created_at)"
        " VALUES (1, 1, 1200.0, 'Штраф', 'превышение скорости', '2026-02-03 10:00:00')"
    )
    connection.execute(
        "INSERT INTO reports (id, car_id, client, mileage, driver, created_at, driver_id, customer_id, paid)"
        " VALUES (1, 1, 'Клиент ООО', 100000, 'Иван', '2026-02-04 10:00:00', 1, 1, 1)"
    )
    connection.execute(
        "INSERT INTO barrel (id, user_id, fuel_type, action, car_plate, liters, created_at)"
        " VALUES (1, 1, 'diesel', 'fill', 'AA1234BB', 500.0, '2026-02-05 10:00:00')"
    )
    connection.commit()
    connection.close()
    return str(path)


def test_import_moves_all_tables(app, old_db):
    """После импорта все записи на месте."""
    admin = User(tg_id=5808824236, level=3)
    db.session.add(admin)
    db.session.commit()

    old = sqlite3.connect(old_db)
    driver_ids = import_legacy.import_drivers(old, admin)
    customer_ids = import_legacy.import_customers(old)
    vehicle_ids = import_legacy.import_vehicles(old, admin, driver_ids)
    fuel_count = import_legacy.import_fuel_entries(old, vehicle_ids)
    service_count = import_legacy.import_service_entries(old, vehicle_ids)
    expense_count = import_legacy.import_expenses(old, vehicle_ids, admin)
    report_count = import_legacy.import_reports(
        old, vehicle_ids, customer_ids, driver_ids
    )
    barrel_count = import_legacy.import_barrels(old)
    old.close()

    assert len(vehicle_ids) == 2
    assert len(driver_ids) == 1
    assert len(customer_ids) == 1
    assert fuel_count == 1
    assert service_count == 1
    assert expense_count == 1
    assert report_count == 1
    assert barrel_count == 1

    assert Vehicle.query.count() == 2
    assert Driver.query.count() == 1
    assert Customer.query.count() == 1
    assert FuelEntry.query.count() == 1
    assert ServiceEntry.query.count() == 1
    assert Expense.query.count() == 1
    assert Report.query.count() == 1
    assert FuelBarrel.query.count() == 1
    assert FuelInflow.query.count() == 1


def test_import_keeps_vehicle_data(app, old_db):
    """Данные фуры переносятся без изменений."""
    admin = User(tg_id=5808824236, level=3)
    db.session.add(admin)
    db.session.commit()

    old = sqlite3.connect(old_db)
    driver_ids = import_legacy.import_drivers(old, admin)
    vehicle_ids = import_legacy.import_vehicles(old, admin, driver_ids)
    old.close()

    vehicle = db.session.get(Vehicle, vehicle_ids["1"])
    assert vehicle.brand == "MAN"
    assert vehicle.current_mileage == 100000
    assert vehicle.wialon_id == 777
    assert vehicle.status == "active"
    assert vehicle.driver_id == admin.id

    archived = db.session.get(Vehicle, vehicle_ids["2"])
    assert archived.status == "archived"


def test_import_is_not_duplicated(app, old_db):
    """Повторный импорт не создаёт дублей."""
    admin = User(tg_id=5808824236, level=3)
    db.session.add(admin)
    db.session.commit()

    for _ in range(2):
        old = sqlite3.connect(old_db)
        driver_ids = import_legacy.import_drivers(old, admin)
        customer_ids = import_legacy.import_customers(old)
        vehicle_ids = import_legacy.import_vehicles(old, admin, driver_ids)
        import_legacy.import_fuel_entries(old, vehicle_ids)
        import_legacy.import_service_entries(old, vehicle_ids)
        import_legacy.import_expenses(old, vehicle_ids, admin)
        import_legacy.import_reports(old, vehicle_ids, customer_ids, driver_ids)
        import_legacy.import_barrels(old)
        old.close()

    assert Vehicle.query.count() == 2
    assert Driver.query.count() == 1
    assert Customer.query.count() == 1
