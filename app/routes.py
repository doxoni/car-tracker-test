# -*- coding: utf-8 -*-
"""API маршруты для car-tracker (MVP + трёхуровневая админ-система).

Эндпоинты:
- /api/vehicles — список фур (GET), создание (POST)
- /api/vehicles/<id> — получить (GET), обновить (PUT), архивировать (DELETE)
- /api/expenses — список расходов (GET), создать (POST)
- /api/expenses/<id> — обновить (PUT), удалить (DELETE)
- /api/expenses/pending — pending расходы на проверке (GET, уровень 3)
- /api/expenses/<id>/approve — одобрить расход (POST, уровень 3)
- /api/expenses/<id>/reject — отклонить расход (POST, уровень 3)
- /api/dashboard — сводка для главной вкладки
- /api/barrels — бочки (GET/POST, уровни 2/3)
- /api/barrels/<id> — бочка (GET/PUT/DELETE, уровни 2/3)
- /api/barrels/<id>/inflows — приходы (GET/POST)
- /api/barrels/<id>/outflows — расходы (GET/POST)
- /api/logs — аудит-лог (GET, уровни 2/3)
- /api/logs/history — очистка аудит-лога (DELETE, уровень 3)
"""

from flask import Blueprint, request, jsonify, g, send_from_directory
from datetime import datetime, date
import os
from sqlalchemy import func, desc, or_

from app import db
from app.models import User, Vehicle, Expense, FuelBarrel, FuelInflow, FuelOutflow, AuditLog, log_audit
from app.auth import require_auth, require_level, require_can_view_logs, require_can_clear_logs


bp = Blueprint("api", __name__, url_prefix="/api")

# Blueprint для Mini App: отдаёт статику (страницу Telegram Mini App).
web_bp = Blueprint("web", __name__)

# Папка со статикой лежит рядом с пакетом app (app/static). Путь задаём
# явно, чтобы не зависеть от того, из какой папки запущен сервер.
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@bp.get("/health")
def health():
    """Health check для Render: проверяет не только процесс, но и БД.

    Заодно держит соединение с Cloud SQL живым - иначе инстанс на
    бесплатном тарифе может осесть после недели без запросов.
    """
    try:
        db.session.execute(db.text("SELECT 1"))
        db.session.rollback()
    except Exception as exc:
        return jsonify({"status": "error", "database": "unavailable", "detail": str(exc)[:200]}), 503
    return jsonify({"status": "ok", "database": "ok"})


@web_bp.get("/")
@web_bp.get("/app")
def miniapp():
    """Страница Telegram Mini App."""
    return send_from_directory(STATIC_DIR, "index.html")


@web_bp.get("/static/<path:filename>")
def static_files(filename):
    """Статика Mini App (CSS/JS)."""
    return send_from_directory(STATIC_DIR, filename)


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
        "vehicle_plate": e.vehicle.plate if e.vehicle else None,
        "category": e.category,
        "amount": e.amount,
        "date": e.date.isoformat() if e.date else None,
        "comment": e.comment,
        "photo_url": e.photo_url,
        "status": e.status,
        "submitted_by": e.submitted_by,
        "approved_by": e.approved_by,
        "approved_at": e.approved_at.isoformat() if e.approved_at else None,
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


def _jsonify_barrel(b: FuelBarrel):
    return {
        "id": b.id,
        "name": b.name,
        "fuel_type": b.fuel_type,
        "capacity_liters": b.capacity_liters,
        "current_liters": b.current_liters,
        "avg_price_per_liter": b.avg_price_per_liter,
        "threshold_liters": b.threshold_liters,
        "is_active": b.is_active,
        "remaining_pct": b.remaining_pct,
        "is_low": b.is_low,
        "formatted_current": b.formatted_current,
        "formatted_remaining": b.formatted_remaining,
    }


def _jsonify_inflow(i: FuelInflow):
    return {
        "id": i.id,
        "barrel_id": i.barrel_id,
        "date": i.date.isoformat() if i.date else None,
        "liters": i.liters,
        "price_per_liter": i.price_per_liter,
        "supplier": i.supplier,
        "total": i.total,
        "formatted_total": f"₴ {i.total:,.0f}",
    }


def _jsonify_outflow(o: FuelOutflow):
    return {
        "id": o.id,
        "barrel_id": o.barrel_id,
        "vehicle_id": o.vehicle_id,
        "vehicle_plate": o.vehicle.plate if o.vehicle else None,
        "driver_id": o.driver_id,
        "driver_name": o.driver.username if o.driver else None,
        "date": o.date.isoformat() if o.date else None,
        "liters": o.liters,
        "cost_per_liter": o.cost_per_liter,
        "total": o.total,
        "formatted_total": f"₴ {o.total:,.0f}",
        "formatted_liters": f"{o.liters:,.1f} л",
    }


def _jsonify_log(l: AuditLog):
    return {
        "id": l.id,
        "user_id": l.user_id,
        "user_name": l.user.username if l.user else None,
        "action": l.action,
        "entity_type": l.entity_type,
        "entity_id": l.entity_id,
        "old_values": l.old_values,
        "new_values": l.new_values,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }


# ---------- Vehicles ----------

@bp.get("/vehicles")
@require_auth
def list_vehicles():
    """Список фур. Уровень 1 — все активные (поиск), уровни 2/3 — все."""
    if g.current_user_level in (2, 3):
        vehicles = Vehicle.query.order_by(Vehicle.plate).all()
    else:
        vehicles = Vehicle.query.filter_by(status="active").order_by(Vehicle.plate).all()
    return jsonify([_jsonify_vehicle(v) for v in vehicles])


@bp.post("/vehicles")
@require_level(2)
def create_vehicle():
    """Создать новую фуру (уровни 2/3)."""
    data = request.get_json() or {}
    required = ["plate", "brand", "driver_id"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"missing {field}"}), 400

    # Проверить уникальность номера
    if Vehicle.query.filter_by(plate=data["plate"]).first():
        return jsonify({"error": "plate exists"}), 400

    old = None
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
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="create",
        entity_type="vehicle",
        entity_id=vehicle.id,
        old_values=old,
        new_values=_jsonify_vehicle(vehicle),
    )
    return jsonify(_jsonify_vehicle(vehicle)), 201


@bp.get("/vehicles/<int:vehicle_id>")
@require_auth
def get_vehicle(vehicle_id):
    """Получить детали фуры. Уровень 1 — только активные."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if not g.current_user.can_view_vehicle(vehicle):
        return jsonify({"error": "forbidden"}), 403
    return jsonify(_jsonify_vehicle(vehicle))


@bp.put("/vehicles/<int:vehicle_id>")
@require_level(2)
def update_vehicle(vehicle_id):
    """Обновить фуру (уровни 2/3)."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    old = _jsonify_vehicle(vehicle)
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
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="update",
        entity_type="vehicle",
        entity_id=vehicle.id,
        old_values=old,
        new_values=_jsonify_vehicle(vehicle),
    )
    return jsonify(_jsonify_vehicle(vehicle))


@bp.delete("/vehicles/<int:vehicle_id>")
@require_level(2)
def archive_vehicle(vehicle_id):
    """Архивировать фуру (уровни 2/3)."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    old = _jsonify_vehicle(vehicle)
    vehicle.status = "archived"
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="delete",
        entity_type="vehicle",
        entity_id=vehicle.id,
        old_values=old,
        new_values={"status": "archived"},
    )
    return jsonify({"status": "archived"})


# ---------- Expenses ----------

@bp.get("/expenses")
@require_auth
def list_expenses():
    """Список расходов с фильтрами: vehicle_id, category, date_from, date_to.

    Уровень 1: только свои расходы (все статусы).
    Уровни 2/3: все расходы.
    """
    vehicle_id = request.args.get("vehicle_id", type=int)
    category = request.args.get("category", "").strip().lower()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    query = Expense.query.join(Vehicle)

    # Права доступа
    if g.current_user_level == 1:
        query = query.filter(Expense.submitted_by == g.current_user.id)
    # уровни 2/3 видят всё

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
    """Создать расход. Уровень 1 — pending для активных фур, уровни 2/3 — approved сразу."""
    data = request.get_json() or {}
    required = ["vehicle_id", "category", "amount", "date"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"missing {field}"}), 400

    vehicle = Vehicle.query.get_or_404(data["vehicle_id"])

    if not g.current_user.can_add_expense(vehicle):
        return jsonify({"error": "forbidden"}), 403

    if data["category"] not in Expense.CATEGORIES:
        return jsonify({"error": "invalid category"}), 400

    # Уровень 1 — pending, уровни 2/3 — approved сразу
    if g.current_user_level == 1:
        status = "pending"
    else:
        status = "approved"

    expense = Expense(
        vehicle_id=vehicle.id,
        category=data["category"],
        amount=float(data["amount"]),
        date=_parse_date(data["date"]) or datetime.utcnow().date(),
        comment=data.get("comment", "").strip() or None,
        photo_url=data.get("photo_url", "").strip() or None,
        status=status,
        submitted_by=g.current_user.id,
        approved_by=None if status == "pending" else g.current_user.id,
        approved_at=None if status == "pending" else datetime.utcnow(),
    )
    db.session.add(expense)
    db.session.commit()

    # Аудит
    log_audit(
        user_id=g.current_user.id,
        action="create",
        entity_type="expense",
        entity_id=expense.id,
        old_values=None,
        new_values=_jsonify_expense(expense),
    )

    # Уведомление уровням 3 о новом pending
    if status == "pending":
        from .notifications import notify_pending_expense
        notify_pending_expense(expense)

    return jsonify(_jsonify_expense(expense)), 201


@bp.put("/expenses/<int:expense_id>")
@require_auth
def update_expense(expense_id):
    """Обновить расход. Уровень 1 — только свои pending, уровни 2/3 — любые."""
    expense = Expense.query.get_or_404(expense_id)

    if g.current_user_level == 1:
        if expense.submitted_by != g.current_user.id or expense.status != "pending":
            return jsonify({"error": "forbidden"}), 403
    # уровни 2/3 могут редактировать любые

    data = request.get_json() or {}
    old = _jsonify_expense(expense)
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
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="update",
        entity_type="expense",
        entity_id=expense.id,
        old_values=old,
        new_values=_jsonify_expense(expense),
    )
    return jsonify(_jsonify_expense(expense))


@bp.delete("/expenses/<int:expense_id>")
@require_auth
def delete_expense(expense_id):
    """Удалить расход. Уровень 1 — только свои pending, уровни 2/3 — любые."""
    expense = Expense.query.get_or_404(expense_id)

    if g.current_user_level == 1:
        if expense.submitted_by != g.current_user.id or expense.status != "pending":
            return jsonify({"error": "forbidden"}), 403
    # уровни 2/3 могут удалять любые

    old = _jsonify_expense(expense)
    db.session.delete(expense)
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="delete",
        entity_type="expense",
        entity_id=expense_id,
        old_values=old,
        new_values=None,
    )
    return jsonify({"status": "deleted"})


@bp.get("/expenses/pending")
@require_level(3)
def list_pending_expenses():
    """Список pending расходов на проверке (только уровень 3)."""
    expenses = Expense.query.filter_by(status="pending").order_by(desc(Expense.date)).all()
    return jsonify([_jsonify_expense(e) for e in expenses])


@bp.post("/expenses/<int:expense_id>/approve")
@require_level(3)
def approve_expense(expense_id):
    """Одобрить pending расход (только уровень 3)."""
    expense = Expense.query.get_or_404(expense_id)
    if expense.status != "pending":
        return jsonify({"error": "not pending"}), 400

    old = _jsonify_expense(expense)
    expense.status = "approved"
    expense.approved_by = g.current_user.id
    expense.approved_at = datetime.utcnow()
    db.session.commit()

    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="approve",
        entity_type="expense",
        entity_id=expense.id,
        old_values=old,
        new_values=_jsonify_expense(expense),
    )
    return jsonify(_jsonify_expense(expense))


@bp.post("/expenses/<int:expense_id>/reject")
@require_level(3)
def reject_expense(expense_id):
    """Отклонить pending расход (только уровень 3)."""
    expense = Expense.query.get_or_404(expense_id)
    if expense.status != "pending":
        return jsonify({"error": "not pending"}), 400

    old = _jsonify_expense(expense)
    expense.status = "rejected"
    expense.approved_by = g.current_user.id
    expense.approved_at = datetime.utcnow()
    db.session.commit()

    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="reject",
        entity_type="expense",
        entity_id=expense.id,
        old_values=old,
        new_values=_jsonify_expense(expense),
    )
    return jsonify(_jsonify_expense(expense))


# ---------- Dashboard ----------

@bp.get("/dashboard")
@require_auth
def dashboard():
    """Сводка для главной вкладки. Только approved расходы в итогах."""
    period = request.args.get("period", "month").strip().lower()  # week | month | year | all
    date_from = None
    today = date.today()

    if period == "week":
        date_from = today.replace(day=today.day - today.weekday())
    elif period == "month":
        date_from = today.replace(day=1)
    elif period == "year":
        date_from = today.replace(month=1, day=1)

    # Базовые запросы с учётом прав и только approved расходы
    def _base_query():
        query = Expense.query.join(Vehicle).filter(Expense.status == "approved")
        if g.current_user_level == 1:
            query = query.filter(Expense.submitted_by == g.current_user.id)
        # уровни 2/3 видят все approved
        return query

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

    # Бочки (уровни 2/3)
    barrels_data = []
    if g.current_user_level in (2, 3):
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


# ---------- Fuel Barrels ----------

@bp.get("/barrels")
@require_level(2)
def list_barrels():
    """Список бочек (уровни 2/3)."""
    barrels = FuelBarrel.query.order_by(FuelBarrel.fuel_type, FuelBarrel.name).all()
    return jsonify([_jsonify_barrel(b) for b in barrels])


@bp.post("/barrels")
@require_level(2)
def create_barrel():
    """Создать бочку (уровни 2/3)."""
    data = request.get_json() or {}
    required = ["name", "fuel_type", "capacity_liters"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"missing {field}"}), 400

    if data["fuel_type"] not in ("diesel", "petrol"):
        return jsonify({"error": "fuel_type must be diesel or petrol"}), 400

    old = None
    barrel = FuelBarrel(
        name=data["name"].strip(),
        fuel_type=data["fuel_type"],
        capacity_liters=float(data["capacity_liters"]),
        current_liters=float(data.get("current_liters", 0.0)),
        avg_price_per_liter=float(data["avg_price_per_liter"]) if data.get("avg_price_per_liter") else None,
        threshold_liters=float(data.get("threshold_liters", 100.0)),
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(barrel)
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="create",
        entity_type="barrel",
        entity_id=barrel.id,
        old_values=old,
        new_values=_jsonify_barrel(barrel),
    )
    return jsonify(_jsonify_barrel(barrel)), 201


@bp.get("/barrels/<int:barrel_id>")
@require_level(2)
def get_barrel(barrel_id):
    """Получить детали бочки (уровни 2/3)."""
    barrel = FuelBarrel.query.get_or_404(barrel_id)
    return jsonify(_jsonify_barrel(barrel))


@bp.put("/barrels/<int:barrel_id>")
@require_level(2)
def update_barrel(barrel_id):
    """Обновить бочку (уровни 2/3)."""
    barrel = FuelBarrel.query.get_or_404(barrel_id)
    old = _jsonify_barrel(barrel)
    data = request.get_json() or {}

    for field in ("name", "fuel_type", "capacity_liters", "current_liters", "avg_price_per_liter", "threshold_liters", "is_active"):
        if field in data:
            if field == "fuel_type" and data[field] not in ("diesel", "petrol"):
                return jsonify({"error": "fuel_type must be diesel or petrol"}), 400
            if field in ("capacity_liters", "current_liters", "avg_price_per_liter", "threshold_liters"):
                setattr(barrel, field, float(data[field]) if data[field] else None)
            elif field == "is_active":
                setattr(barrel, field, bool(data[field]))
            else:
                setattr(barrel, field, data[field])

    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="update",
        entity_type="barrel",
        entity_id=barrel.id,
        old_values=old,
        new_values=_jsonify_barrel(barrel),
    )
    return jsonify(_jsonify_barrel(barrel))


@bp.delete("/barrels/<int:barrel_id>")
@require_level(2)
def delete_barrel(barrel_id):
    """Удалить бочку (уровни 2/3)."""
    barrel = FuelBarrel.query.get_or_404(barrel_id)
    old = _jsonify_barrel(barrel)
    db.session.delete(barrel)
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="delete",
        entity_type="barrel",
        entity_id=barrel_id,
        old_values=old,
        new_values=None,
    )
    return jsonify({"status": "deleted"})


# ---------- Fuel Inflow (Приход) ----------

@bp.get("/barrels/<int:barrel_id>/inflows")
@require_level(2)
def list_inflows(barrel_id):
    """Список приходов в бочку."""
    inflows = FuelInflow.query.filter_by(barrel_id=barrel_id).order_by(desc(FuelInflow.date)).all()
    return jsonify([_jsonify_inflow(i) for i in inflows])


@bp.post("/barrels/<int:barrel_id>/inflows")
@require_level(2)
def create_inflow(barrel_id):
    """Записать приход топлива в бочку."""
    barrel = FuelBarrel.query.get_or_404(barrel_id)
    data = request.get_json() or {}
    required = ["liters", "price_per_liter", "date"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"missing {field}"}), 400

    liters = float(data["liters"])
    price = float(data["price_per_liter"])
    total = liters * price

    inflow = FuelInflow(
        barrel_id=barrel.id,
        date=_parse_date(data["date"]) or datetime.utcnow().date(),
        liters=liters,
        price_per_liter=price,
        supplier=data.get("supplier", "").strip() or None,
        total=total,
    )

    # Обновляем бочку: весомая средняя цена
    if barrel.current_liters > 0 and barrel.avg_price_per_liter:
        new_total_liters = barrel.current_liters + liters
        new_avg = (barrel.current_liters * barrel.avg_price_per_liter + total) / new_total_liters
        barrel.avg_price_per_liter = round(new_avg, 2)
    else:
        barrel.avg_price_per_liter = price
    barrel.current_liters += liters

    old_barrel = _jsonify_barrel(barrel)
    db.session.add(inflow)
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="create",
        entity_type="inflow",
        entity_id=inflow.id,
        old_values=None,
        new_values=_jsonify_inflow(inflow),
    )
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="update",
        entity_type="barrel",
        entity_id=barrel.id,
        old_values=old_barrel,
        new_values=_jsonify_barrel(barrel),
    )
    return jsonify(_jsonify_inflow(inflow)), 201


@bp.delete("/barrels/inflows/<int:inflow_id>")
@require_level(2)
def delete_inflow(inflow_id):
    """Удалить приход (с откатом бочки)."""
    inflow = FuelInflow.query.get_or_404(inflow_id)
    barrel = inflow.barrel
    old_barrel = _jsonify_barrel(barrel)
    old_inflow = _jsonify_inflow(inflow)

    # Откатываем бочку
    barrel.current_liters -= inflow.liters
    if barrel.current_liters < 0:
        barrel.current_liters = 0

    db.session.delete(inflow)
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="delete",
        entity_type="inflow",
        entity_id=inflow_id,
        old_values=old_inflow,
        new_values=None,
    )
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="update",
        entity_type="barrel",
        entity_id=barrel.id,
        old_values=old_barrel,
        new_values=_jsonify_barrel(barrel),
    )
    return jsonify({"status": "deleted"})


# ---------- Fuel Outflow (Расход/Заправка) ----------

@bp.get("/barrels/<int:barrel_id>/outflows")
@require_level(2)
def list_outflows(barrel_id):
    """Список расходов из бочки."""
    outflows = FuelOutflow.query.filter_by(barrel_id=barrel_id).order_by(desc(FuelOutflow.date)).all()
    return jsonify([_jsonify_outflow(o) for o in outflows])


@bp.post("/barrels/<int:barrel_id>/outflows")
@require_level(2)
def create_outflow(barrel_id):
    """Заправить фуру из бочки — создаёт расход и пополняет expense."""
    barrel = FuelBarrel.query.get_or_404(barrel_id)
    data = request.get_json() or {}
    required = ["vehicle_id", "liters", "date"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"missing {field}"}), 400

    vehicle = Vehicle.query.get_or_404(data["vehicle_id"])
    liters = float(data["liters"])

    if liters > barrel.current_liters:
        return jsonify({"error": "not enough fuel in barrel"}), 400

    cost_per_liter = barrel.avg_price_per_liter or 0.0
    total = liters * cost_per_liter

    outflow = FuelOutflow(
        barrel_id=barrel.id,
        vehicle_id=vehicle.id,
        driver_id=data.get("driver_id", vehicle.driver_id),
        date=_parse_date(data["date"]) or datetime.utcnow().date(),
        liters=liters,
        cost_per_liter=cost_per_liter,
        total=total,
    )

    # Уменьшаем бочку
    barrel.current_liters -= liters

    # Автоматически создаём запись в расходах фуры (approved, так как оператор уровня 2/3)
    expense = Expense(
        vehicle_id=vehicle.id,
        category="топливо",
        amount=total,
        date=outflow.date,
        comment=f"Заправка из бочки {barrel.name}: {liters} л @ {cost_per_liter:.2f} ₴/л",
        photo_url=None,
        status="approved",
        submitted_by=g.current_user.id,
        approved_by=g.current_user.id,
        approved_at=datetime.utcnow(),
    )

    old_barrel = _jsonify_barrel(barrel)
    db.session.add(outflow)
    db.session.add(expense)
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="create",
        entity_type="outflow",
        entity_id=outflow.id,
        old_values=None,
        new_values=_jsonify_outflow(outflow),
    )
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="create",
        entity_type="expense",
        entity_id=expense.id,
        old_values=None,
        new_values=_jsonify_expense(expense),
    )
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="update",
        entity_type="barrel",
        entity_id=barrel.id,
        old_values=old_barrel,
        new_values=_jsonify_barrel(barrel),
    )
    return jsonify(_jsonify_outflow(outflow)), 201


# ---------- Audit Logs ----------

@bp.get("/logs")
@require_can_view_logs
def list_logs():
    """Список аудит-логов (уровни 2/3)."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    entity_type = request.args.get("entity_type", "").strip()
    action = request.args.get("action", "").strip()

    query = AuditLog.query
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action == action)

    logs = query.order_by(desc(AuditLog.created_at)).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify([_jsonify_log(l) for l in logs])


@bp.delete("/logs/history")
@require_can_clear_logs
def clear_logs():
    """Очистить всю аудит-историю (только уровень 3)."""
    count = AuditLog.query.delete()
    db.session.commit()
    log_audit(
        user_id=getattr(g, "current_tg_id", None),
        action="clear",
        entity_type="audit_logs",
        old_values={"deleted_count": count},
        new_values=None,
    )
    return jsonify({"status": "cleared", "deleted": count})