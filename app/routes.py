# -*- coding: utf-8 -*-
"""API маршруты для car-tracker (MVP).

Эндпоинты:
- /api/vehicles — список фур (GET), создание (POST)
- /api/vehicles/<id> — получить (GET), обновить (PUT), архивировать (DELETE)
- /api/expenses — список расходов (GET), создать (POST)
- /api/expenses/<id> — обновить (PUT), удалить (DELETE)
- /api/dashboard — сводка для главной вкладки
"""

from flask import Blueprint, request, jsonify, g
from datetime import datetime, date
from sqlalchemy import func, desc

from . import db
from .models import User, Vehicle, Expense
from .auth import require_auth, require_admin


bp = Blueprint("api", __name__, url_prefix="/api")


# ---------- Helpers ----------

def _parse_date(date_str: str):
    """Парсинг даты в формате дд.мм.гггг или YYYY-MM-DD."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _jsonify_expense(e: Expense):
    return {
        "id": e.id,
        "vehicle_id": e.vehicle_id,
        "category": e.category,
        "amount": e.amount,
        "date": e.date.isoformat() if e.date else None,
        "comment": e.comment,
        "photo_url": e.photo_url,
        "formatted_amount": f"₴ {e.amount:,.0f}",
    }


def _jsonify_vehicle(v: Vehicle):
    return {
        "id": v.id,
        "plate": v.plate,
        "brand": v.brand,
        "vin": v.vin,
        "driver_id": v.driver_id,
        "driver_name": v.driver.username if v.driver else None,
        "status": v.status,
        "wialon_id": v.wialon_id,
        "current_mileage": v.current_mileage,
        "avg_fuel_consumption": v.avg_fuel_consumption,
        "display_name": v.display_name,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


# ---------- Vehicles ----------

@bp.get("/vehicles")
@require_auth
def list_vehicles():
    """Список фур. Админ видит все, водитель — только свою."""
    if g.is_admin:
        vehicles = Vehicle.query.order_by(Vehicle.plate).all()
    else:
        vehicles = Vehicle.query.filter_by(driver_id=g.current_user.id, status="active").all()
    return jsonify([_jsonify_vehicle(v) for v in vehicles])


@bp.post("/vehicles")
@require_admin
def create_vehicle():
    """Создать новую фуру (только админ)."""
    data = request.get_json() or {}
    required = ["plate", "brand", "driver_id"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"missing {field}"}), 400

    # Проверить уникальность номера
    if Vehicle.query.filter_by(plate=data["plate"]).first():
        return jsonify({"error": "plate exists"}), 400

    vehicle = Vehicle(
        plate=data["plate"].strip().upper(),
        brand=data["brand"].strip(),
        vin=data.get("vin", "").strip().upper() or None,
        driver_id=int(data["driver_id"]),
        wialon_id=int(data["wialon_id"]) if data.get("wialon_id") else None,
        current_mileage=int(data.get("current_mileage", 0)),
        avg_fuel_consumption=float(data.get("avg_fuel_consumption", 30.0)),
        status="active",
    )
    db.session.add(vehicle)
    db.session.commit()
    return jsonify(_jsonify_vehicle(vehicle)), 201


@bp.get("/vehicles/<int:vehicle_id>")
@require_auth
def get_vehicle(vehicle_id):
    """Получить детали фуры."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if not g.is_admin and not g.current_user.can_view_vehicle(vehicle):
        return jsonify({"error": "forbidden"}), 403
    return jsonify(_jsonify_vehicle(vehicle))


@bp.put("/vehicles/<int:vehicle_id>")
@require_admin
def update_vehicle(vehicle_id):
    """Обновить фуру (только админ)."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    data = request.get_json() or {}

    for field in ("plate", "brand", "vin", "driver_id", "wialon_id", "current_mileage", "avg_fuel_consumption", "status"):
        if field in data:
            if field == "plate":
                new_plate = data[field].strip().upper()
                if new_plate != vehicle.plate and Vehicle.query.filter_by(plate=new_plate).first():
                    return jsonify({"error": "plate exists"}), 400
                setattr(vehicle, field, new_plate)
            elif field == "vin":
                setattr(vehicle, field, data[field].strip().upper() or None)
            elif field in ("driver_id", "wialon_id", "current_mileage"):
                setattr(vehicle, field, int(data[field]) if data[field] else None)
            elif field == "avg_fuel_consumption":
                setattr(vehicle, field, float(data[field]))
            else:
                setattr(vehicle, field, data[field])

    db.session.commit()
    return jsonify(_jsonify_vehicle(vehicle))


@bp.delete("/vehicles/<int:vehicle_id>")
@require_admin
def archive_vehicle(vehicle_id):
    """Архивировать фуру (только админ)."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    vehicle.status = "archived"
    db.session.commit()
    return jsonify({"status": "archived"})


# ---------- Expenses ----------

@bp.get("/expenses")
@require_auth
def list_expenses():
    """Список расходов с фильтрами: vehicle_id, category, date_from, date_to."""
    vehicle_id = request.args.get("vehicle_id", type=int)
    category = request.args.get("category", "").strip().lower()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    query = Expense.query.join(Vehicle)

    # Права доступа: админ видит всё, водитель — только свои фуры
    if not g.is_admin:
        query = query.filter(Vehicle.driver_id == g.current_user.id)

    if vehicle_id:
        query = query.filter(Expense.vehicle_id == vehicle_id)

    if category:
        query = query.filter(Expense.category == category)

    if date_from:
        d = _parse_date(date_from)
        if d:
            query = query.filter(Expense.date >= d)

    if date_to:
        d = _parse_date(date_to)
        if d:
            query = query.filter(Expense.date <= d)

    expenses = query.order_by(desc(Expense.date)).limit(500).all()
    return jsonify([_jsonify_expense(e) for e in expenses])


@bp.post("/expenses")
@require_auth
def create_expense():
    """Создать расход. Водитель может только для своей фуры."""
    data = request.get_json() or {}
    required = ["vehicle_id", "category", "amount", "date"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"missing {field}"}), 400

    vehicle = Vehicle.query.get_or_404(data["vehicle_id"])

    if not g.is_admin and not g.current_user.can_add_expense_to_vehicle(vehicle):
        return jsonify({"error": "forbidden"}), 403

    if data["category"] not in Expense.CATEGORIES:
        return jsonify({"error": "invalid category"}), 400

    expense = Expense(
        vehicle_id=vehicle.id,
        category=data["category"],
        amount=float(data["amount"]),
        date=_parse_date(data["date"]) or datetime.utcnow().date(),
        comment=data.get("comment", "").strip() or None,
        photo_url=data.get("photo_url", "").strip() or None,
    )
    db.session.add(expense)
    db.session.commit()
    return jsonify(_jsonify_expense(expense)), 201


@bp.put("/expenses/<int:expense_id>")
@require_auth
def update_expense(expense_id):
    """Обновить расход."""
    expense = Expense.query.get_or_404(expense_id)

    if not g.is_admin and not g.current_user.can_add_expense_to_vehicle(expense.vehicle):
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json() or {}
    for field in ("category", "amount", "date", "comment", "photo_url"):
        if field in data:
            if field == "category" and data[field] not in Expense.CATEGORIES:
                return jsonify({"error": "invalid category"}), 400
            if field == "date":
                d = _parse_date(data[field])
                if d:
                    setattr(expense, field, d)
            elif field == "amount":
                setattr(expense, field, float(data[field]))
            else:
                setattr(expense, field, data[field] or None)

    db.session.commit()
    return jsonify(_jsonify_expense(expense))


@bp.delete("/expenses/<int:expense_id>")
@require_auth
def delete_expense(expense_id):
    """Удалить расход."""
    expense = Expense.query.get_or_404(expense_id)

    if not g.is_admin and not g.current_user.can_add_expense_to_vehicle(expense.vehicle):
        return jsonify({"error": "forbidden"}), 403

    db.session.delete(expense)
    db.session.commit()
    return jsonify({"status": "deleted"})


# ---------- Dashboard ----------

@bp.get("/dashboard")
@require_auth
def dashboard():
    """Сводка для главной вкладки: итоги по периодам, топ фур, категории, бочки."""
    # Фильтры
    period = request.args.get("period", "month").strip().lower()  # week | month | year | all
    date_from = None
    today = date.today()

    if period == "week":
        date_from = today.replace(day=today.day - today.weekday())
    elif period == "month":
        date_from = today.replace(day=1)
    elif period == "year":
        date_from = today.replace(month=1, day=1)

    # Базовые запросы с учётом прав
    def _base_query():
        if g.is_admin:
            return Expense.query.join(Vehicle)
        return Expense.query.join(Vehicle).filter(Vehicle.driver_id == g.current_user.id)

    base = _base_query()
    if date_from:
        base = base.filter(Expense.date >= date_from)

    # Итоговая сумма
    total_amount = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
        Expense.id.in_(base.with_entities(Expense.id).subquery())
    ).scalar()

    # Топ-5 фур по затратам
    top_vehicles = db.session.query(
        Vehicle.plate, Vehicle.brand, func.sum(Expense.amount).label("total")
    ).join(Expense, Vehicle.id == Expense.vehicle_id).filter(
        Expense.id.in_(base.with_entities(Expense.id).subquery())
    ).group_by(Vehicle.id).order_by(desc("total")).limit(5).all()

    top_vehicles_data = [
        {"plate": v[0], "brand": v[1], "total": float(v[2])}
        for v in top_vehicles
    ]

    # Структура по категориям
    by_category = db.session.query(
        Expense.category, func.sum(Expense.amount).label("total")
    ).filter(Expense.id.in_(base.with_entities(Expense.id).subquery())).group_by(
        Expense.category
    ).all()

    by_category_data = [
        {"category": c[0], "total": float(c[1])}
        for c in by_category
    ]

    # Бочки (только для админа)
    barrels_data = []
    if g.is_admin:
        from .models import FuelBarrel
        barrels = FuelBarrel.query.filter_by(is_active=True).all()
        barrels_data = [
            {
                "id": b.id,
                "name": b.name,
                "fuel_type": b.fuel_type,
                "current": b.current_liters,
                "capacity": b.capacity_liters,
                "remaining_pct": b.remaining_pct,
                "is_low": b.is_low,
                "formatted_current": b.formatted_current,
                "formatted_remaining": b.formatted_remaining,
            }
            for b in barrels
        ]

    return jsonify({
        "period": period,
        "total_amount": float(total_amount),
        "top_vehicles": top_vehicles_data,
        "by_category": by_category_data,
        "barrels": barrels_data,
    })