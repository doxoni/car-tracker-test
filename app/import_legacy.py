# -*- coding: utf-8 -*-
"""Импорт данных из старой базы cars.db в новую базу проекта.

Старая система (car-tracker, sqlite-файл cars.db) и новая (Flask +
SQLAlchemy + PostgreSQL) хранят разные вещи. Импорт переносит то, что
есть в обеих схемах, и создаёт недостающие записи:

    cars      -> vehicles      (фуры)
    drivers   -> drivers       (водители по имени)
    customers -> customers     (клиенты)
    fuel      -> fuel_entries  (заправки)
    services  -> service_entries (ТО)
    expenses  -> expenses      (расходы)
    reports   -> reports       (акты)
    barrel    -> fuel_barrels + fuel_inflow (наполнения бочек)

Запуск:
    python -m app.import_legacy --db "C:\\path\\cars.db" --user-id 123456

Ключ: в новую баду скрипт идёт по DATABASE_URL (тот же, что у сервиса).
Перед импортом на сервере стоит сделать бэкап базы.
"""

import argparse
import sqlite3
import sys
from datetime import datetime

from app import create_app, db
from app.models import (
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


# ---------- Вспомогательные функции ----------


def say(text: str) -> None:
    """Печать без падения на старой кодировке консоли (cp1251)."""
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe + "\n")


def _parse_dt(value) -> datetime | None:
    """Дата из старой базы в datetime. Старый формат: 'YYYY-MM-DD HH:MM:SS'."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _pick_user(user_id: int | None) -> User | None:
    """Пользователь, которому принадлежит импортированное.

    Фуры в новой схеме требуют водителя (users.id). Если конкретный
    Telegram-номер не указан, берём суперадмина, а если его нет - первого
    пользователя с наивысшим уровнем.
    """
    if user_id:
        user = User.query.filter_by(tg_id=user_id).first()
        if user:
            return user
        say(f"Пользователя с tg_id={user_id} нет в базе - создаю его")
        user = User(tg_id=user_id, level=3)
        db.session.add(user)
        db.session.flush()
        return user

    user = (
        User.query.order_by(User.level.desc(), User.id.asc()).first()
    )
    if user is None:
        say("В базе нет ни одного пользователя - нечего импортировать")
        return None
    return user


# ---------- Импорт таблиц ----------


def import_drivers(old: sqlite3.Connection, user: User) -> dict[str, int]:
    """Водители по имени: старые drivers -> новые drivers."""
    rows = old.execute("SELECT id, name FROM drivers ORDER BY id").fetchall()
    mapping: dict[int, Driver] = {}
    for old_id, name in rows:
        driver = Driver.query.filter_by(name=name).first()
        if driver is None:
            driver = Driver(name=name, user_id=user.id)
            db.session.add(driver)
            db.session.flush()
        mapping[old_id] = driver
    db.session.commit()
    return {str(k): v.id for k, v in mapping.items()}


def import_customers(old: sqlite3.Connection) -> dict[str, int]:
    """Клиенты: старые customers -> новые customers."""
    rows = old.execute("SELECT id, name FROM customers ORDER BY id").fetchall()
    mapping: dict[int, Customer] = {}
    for old_id, name in rows:
        customer = Customer.query.filter_by(name=name).first()
        if customer is None:
            customer = Customer(name=name)
            db.session.add(customer)
            db.session.flush()
        mapping[old_id] = customer
    db.session.commit()
    return {str(k): v.id for k, v in mapping.items()}


def import_vehicles(
    old: sqlite3.Connection, user: User, driver_ids: dict[str, int]
) -> dict[str, int]:
    """Фуры: старые cars -> новые vehicles."""
    rows = old.execute(
        "SELECT id, model, plate, mileage, wialon_id, is_active FROM cars ORDER BY id"
    ).fetchall()
    mapping: dict[int, Vehicle] = {}
    for old_id, model, plate, mileage, wialon_id, is_active in rows:
        vehicle = Vehicle.query.filter_by(plate=plate).first()
        if vehicle is None:
            vehicle = Vehicle(
                plate=plate,
                brand=model or "Фура",
                driver_id=user.id,
                current_mileage=int(mileage or 0),
                wialon_id=int(wialon_id) if wialon_id else None,
                status="active" if is_active else "archived",
            )
            db.session.add(vehicle)
            db.session.flush()
        mapping[old_id] = vehicle
    db.session.commit()
    return {str(k): v.id for k, v in mapping.items()}


def import_fuel_entries(
    old: sqlite3.Connection, vehicle_ids: dict[str, int]
) -> int:
    """Заправки: старые fuel -> новые fuel_entries."""
    rows = old.execute(
        "SELECT car_id, liters, price, amount, odometer, is_full, location, created_at "
        "FROM fuel ORDER BY id"
    ).fetchall()
    count = 0
    for car_id, liters, price, amount, odometer, is_full, location, created_at in rows:
        vehicle_id = vehicle_ids.get(str(car_id))
        if vehicle_id is None:
            continue
        db.session.add(
            FuelEntry(
                vehicle_id=vehicle_id,
                liters=float(liters or 0),
                price=float(price or 0),
                amount=float(amount or 0),
                odometer=int(odometer) if odometer else None,
                is_full=bool(is_full),
                location=location,
                created_at=_parse_dt(created_at) or datetime.utcnow(),
            )
        )
        count += 1
    db.session.commit()
    return count


def import_service_entries(
    old: sqlite3.Connection, vehicle_ids: dict[str, int]
) -> int:
    """ТО: старые services -> новые service_entries."""
    rows = old.execute(
        "SELECT car_id, amount, description, details, odometer, next_km, next_date, "
        "created_at FROM services ORDER BY id"
    ).fetchall()
    count = 0
    for (
        car_id,
        amount,
        description,
        details,
        odometer,
        next_km,
        next_date,
        created_at,
    ) in rows:
        vehicle_id = vehicle_ids.get(str(car_id))
        if vehicle_id is None:
            continue
        db.session.add(
            ServiceEntry(
                vehicle_id=vehicle_id,
                amount=float(amount or 0),
                description=description,
                details=details,
                odometer=int(odometer) if odometer else None,
                next_km=int(next_km) if next_km else None,
                next_date=_parse_dt(next_date),
                created_at=_parse_dt(created_at) or datetime.utcnow(),
            )
        )
        count += 1
    db.session.commit()
    return count


def import_expenses(
    old: sqlite3.Connection, vehicle_ids: dict[str, int], user: User
) -> int:
    """Расходы: старые expenses -> новые expenses."""
    rows = old.execute(
        "SELECT car_id, amount, description, details, created_at FROM expenses ORDER BY id"
    ).fetchall()
    count = 0
    for car_id, amount, description, details, created_at in rows:
        vehicle_id = vehicle_ids.get(str(car_id))
        if vehicle_id is None:
            continue
        db.session.add(
            Expense(
                vehicle_id=vehicle_id,
                category="прочее",
                amount=float(amount or 0),
                comment=" ".join(x for x in (description, details) if x) or None,
                status="approved",
                submitted_by=user.id,
                approved_by=user.id,
                date=_parse_dt(created_at) or datetime.utcnow(),
            )
        )
        count += 1
    db.session.commit()
    return count


def import_reports(
    old: sqlite3.Connection,
    vehicle_ids: dict[str, int],
    customer_ids: dict[str, int],
    driver_ids: dict[str, int],
) -> int:
    """Акты: старые reports -> новые reports."""
    rows = old.execute(
        "SELECT car_id, client, mileage, driver, driver_id, customer_id, paid, created_at "
        "FROM reports ORDER BY id"
    ).fetchall()
    count = 0
    for (
        car_id,
        client,
        mileage,
        driver,
        driver_id,
        customer_id,
        paid,
        created_at,
    ) in rows:
        db.session.add(
            Report(
                vehicle_id=vehicle_ids.get(str(car_id)),
                customer_id=customer_ids.get(str(customer_id)),
                driver_id=driver_ids.get(str(driver_id)),
                client=client,
                driver=driver,
                mileage=int(mileage) if mileage else None,
                paid=bool(paid),
                created_at=_parse_dt(created_at) or datetime.utcnow(),
            )
        )
        count += 1
    db.session.commit()
    return count


def import_barrels(old: sqlite3.Connection) -> int:
    """Наполнения бочек: старые barrel -> fuel_barrels + fuel_inflow.

    В старой системе бочка - это запись о наполнении: тип топлива, что
    сделали (fill), сколько литров и для какой машины. Самих бочек с
    объёмом там нет, поэтому создаём бочку на каждый тип топлива и
    записываем приход.
    """
    rows = old.execute(
        "SELECT fuel_type, action, liters, created_at FROM barrel ORDER BY id"
    ).fetchall()
    count = 0
    for fuel_type, action, liters, created_at in rows:
        if action != "fill":
            continue
        name = "Бочка дизель" if fuel_type == "diesel" else "Бочка бензин"
        barrel = FuelBarrel.query.filter_by(name=name).first()
        if barrel is None:
            barrel = FuelBarrel(
                name=name,
                fuel_type=fuel_type,
                capacity_liters=1000.0,
                current_liters=0.0,
            )
            db.session.add(barrel)
            db.session.flush()
        amount = float(liters or 0)
        barrel.current_liters = float(barrel.current_liters or 0) + amount
        db.session.add(
            FuelInflow(
                barrel_id=barrel.id,
                liters=amount,
                price_per_liter=0.0,
                total=0.0,
                date=_parse_dt(created_at) or datetime.utcnow(),
            )
        )
        count += 1
    db.session.commit()
    return count


# ---------- Точка входа ----------


def main() -> int:
    """Импортировать данные старой базы в новую."""
    parser = argparse.ArgumentParser(description="Импорт cars.db в новую базу")
    parser.add_argument("--db", required=True, help="путь к старой cars.db")
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Telegram-номер владельца импортированных фур (по умолчанию - суперадмин)",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        user = _pick_user(args.user_id)
        if user is None:
            return 1

        old = sqlite3.connect(args.db)
        old.row_factory = sqlite3.Row

        say("Импортирую данные из старой базы...")
        driver_ids = import_drivers(old, user)
        customer_ids = import_customers(old)
        vehicle_ids = import_vehicles(old, user, driver_ids)
        fuel_count = import_fuel_entries(old, vehicle_ids)
        service_count = import_service_entries(old, vehicle_ids)
        expense_count = import_expenses(old, vehicle_ids, user)
        report_count = import_reports(old, vehicle_ids, customer_ids, driver_ids)
        barrel_count = import_barrels(old)
        old.close()

        say("Готово:")
        say(f"  фуры:      {len(vehicle_ids)}")
        say(f"  водители:  {len(driver_ids)}")
        say(f"  клиенты:   {len(customer_ids)}")
        say(f"  заправки:  {fuel_count}")
        say(f"  ТО:        {service_count}")
        say(f"  расходы:   {expense_count}")
        say(f"  акты:      {report_count}")
        say(f"  бочки:     {barrel_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
