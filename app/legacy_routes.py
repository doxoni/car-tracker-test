# -*- coding: utf-8 -*-
"""API старой системы — для старого интерфейса Mini App.

Старая GUI (app/static/index.html) обращается к адресам вида
/api/cars, /api/drivers, /api/barrel и ждёт ответы в старом формате:
успех — {"ok": true, ...}, ошибка — {"ok": false, "error": "текст"}.
Поэтому этот модуль повторяет контракт старого проекта один в один,
хотя внутри работает с новыми таблицами (vehicles, drivers, customers,
fuel_entries, service_entries, reports, fuel_barrels).

Данные лежат в той же облачной базе, что и новый интерфейс, поэтому
старая и новая части видят одни и те же фуры и записи.

Запуск (из папки проекта):
    python app/main.py
"""

from datetime import datetime, timedelta

from flask import Blueprint, Response, g, jsonify, request

from app import db
from app.auth import require_auth
from app.i18n import current_lang, t
from app.legacy_catalog import all_items
from app.legacy_plates import format_plate, normalize_plate
from app.models import (
    Customer,
    Driver,
    Expense,
    FuelBarrel,
    FuelEntry,
    FuelInflow,
    FuelOutflow,
    Report,
    ServiceEntry,
    UserVehicle,
    Vehicle,
)

bp = Blueprint("legacy_api", __name__, url_prefix="/api")

# Максимальные суммы, чтобы опечатка не ушла в базу.
MAX_AMOUNT = 100_000_000
MAX_TEXT_LENGTH = 500

# Марки грузовиков: по названию модели решаем, грузовик это или нет.
TRUCK_MODELS = (
    "MAN",
    "VOLVO",
    "DAF",
    "SCANIA",
    "IVECO",
    "ACTROS",
    "HOWO",
    "SHACMAN",
    "FOTON",
    "KAMAZ",
    "КАМАЗ",
    "MAZ",
    "МАЗ",
    "HINO",
    "ISUZU",
    "MACK",
    "FREIGHTLINER",
    "PETERBILT",
    "KENWORTH",
)

BARREL_TYPES = ("diesel", "petrol")
BARREL_ACTIONS = ("add", "fill", "sub")

# Названия видов топлива и действий бочки по-русски: в выгрузке текстом
# показываем их словами, а не служебными кодами.
BARREL_TYPE_NAME = {"diesel": "Дизель", "petrol": "Бензин"}
BARREL_ACTION_NAME = {"add": "Пополнение", "fill": "Заправка", "sub": "Убавление"}


# ---------- Вспомогательные функции ----------


def _fail(message: str, code: int = 400):
    """Ответ с ошибкой в старом формате."""
    return jsonify({"ok": False, "error": message}), code


def _clean_text(value, limit: int = MAX_TEXT_LENGTH) -> str:
    """Текст без лишних пробелов, обрезанный до limit символов."""
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _number(value, default=None):
    """Число из значения или default, если значение не число."""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _whole_number(value):
    """Целое число из значения или None."""
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _check_amount(value, field: str):
    """Проверяет сумму. Возвращает (число, ошибка)."""
    amount = _number(value)
    if amount is None:
        return None, f"{field} — число"
    if amount < 0:
        return None, f"{field} не может быть отрицательной"
    if amount > MAX_AMOUNT:
        return None, f"{field} слишком большая"
    return round(amount, 2), None


def _check_odometer(value, car):
    """Проверяет одометр: целое число и не меньше пробега машины.

    Возвращает (одометр, ошибка, предупреждение). Предупреждение
    появляется, если пробег скакнул больше чем на 5000 км.
    """
    odometer = _whole_number(value)
    if odometer is None:
        return None, "одометр — целое число километров", None
    if odometer < 0:
        return None, "одометр не может быть отрицательным", None
    current = int(getattr(car, "current_mileage", 0) or 0)
    if odometer < current:
        return None, f"одометр меньше текущего пробега ({current} км)", None
    warning = None
    if current > 0 and odometer - current > 5000:
        warning = f"Большой скачок пробега: +{odometer - current} км (обычно не более 5000)"
    return odometer, None, warning


def _check_date(value) -> str:
    """Дата в виде ГГГГ-ММ-ДД. Пустая строка — не задана."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _level() -> int:
    """Уровень текущего пользователя (0 — нет доступа)."""
    return int(getattr(g, "current_user_level", 0) or 0)


def _is_admin(level: int) -> bool:
    """Админ — уровень 2 и выше."""
    return level >= 2


def _is_full_admin(level: int) -> bool:
    """Полный доступ (уровень 2 в старой системе) — бочка."""
    return level >= 2


def _is_super_admin(level: int) -> bool:
    """Суперадмин (уровень 3) — отчёты и выгрузка истории."""
    return level >= 3


def _iso(value) -> str:
    """Дата из базы в строку, которую понимает старая GUI."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _json_date(value):
    """Дата для JSON: строка или None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _vehicle_dict(vehicle: Vehicle) -> dict:
    """Фура в словаре новой схемы."""
    return {
        "id": vehicle.id,
        "plate": vehicle.plate or "",
        "model": vehicle.brand or "",
        "mileage": int(vehicle.current_mileage or 0),
        "wialon_id": vehicle.wialon_id,
        "is_active": 1 if (vehicle.status or "active") == "active" else 0,
        "created_at": _iso(vehicle.created_at),
    }


def _is_truck_model(model: str) -> bool:
    """Грузовик ли это: начинается ли модель с названия грузовика.

    «Mazda» — это легковушка, а не грузовик MAZ, поэтому отдельно
    оговорено это исключение.
    """
    text = "".join((model or "").upper().split())
    if not text:
        return False
    for name in TRUCK_MODELS:
        if not text.startswith(name):
            continue
        if name == "MAZ" and text.startswith("MAZDA"):
            continue  # «Mazda CX-5» — не грузовик
        return True
    return False


def _vehicle_by_id(vehicle_id: int):
    """Фура по номеру или None."""
    return db.session.get(Vehicle, vehicle_id)


def _car_for_user(vehicle_id: int):
    """Фура и ответ с ошибкой, если доступа нет.

    Возвращает пару (фура, ошибка). Если всё хорошо, ошибка — None.
    """
    vehicle = _vehicle_by_id(vehicle_id)
    if vehicle is None:
        return None, _fail("машина не найдена", 404)
    if (vehicle.status or "active") != "active":
        return None, _fail("нет доступа к этой машине", 403)
    return vehicle, None


def _user_vehicle_ids(user_id: int) -> set:
    """Номера машин из личного списка пользователя.

    Результат кэшируется на время запроса: список машин считается для
    каждой фуры отдельно, а запрос к базе тут один и тот же.
    """
    if not user_id:
        return set()
    cache = getattr(g, "_my_vehicle_ids", None)
    if cache is not None and cache.get("user_id") == user_id:
        return cache["ids"]
    ids = {
        row.vehicle_id
        for row in UserVehicle.query.filter_by(user_id=user_id).all()
    }
    g._my_vehicle_ids = {"user_id": user_id, "ids": ids}
    return ids


def _current_user_id() -> int:
    """Номер текущего пользователя (0 — нет доступа)."""
    user = getattr(g, "current_user", None)
    return int(user.id) if user is not None else 0


def _visible_vehicles(query: str = ""):
    """Фуры, доступные пользователю.

    Уровень 2 и выше видят все фуры. Водитель (уровень 1) видит свой
    личный список (машины, которые он добавил себе через поиск) и то,
    что нашлось по поиску: без поискового запроса показываем только
    личный список. При поиске видны все подходящие фуры, чтобы можно
    было найти нужную машину.
    """
    level = _level()
    if query:
        # Поиском водитель видит активные фуры, админ - все.
        query_set = Vehicle.query
        if level < 2:
            query_set = query_set.filter(Vehicle.status == "active")
        return query_set.order_by(Vehicle.id.asc()).all()
    if _is_full_admin(level):
        return Vehicle.query.order_by(Vehicle.id.asc()).all()
    if level < 2:
        my_ids = _user_vehicle_ids(_current_user_id())
        if not my_ids:
            return []
        return (
            Vehicle.query.filter(
                Vehicle.id.in_(my_ids), Vehicle.status == "active"
            )
            .order_by(Vehicle.id.asc())
            .all()
        )
    return Vehicle.query.filter(
        Vehicle.status == "active"
    ).order_by(Vehicle.id.asc()).all()


def _fuel_rows(vehicle_id: int) -> list:
    """Заправки фуры из базы."""
    return (
        FuelEntry.query.filter_by(vehicle_id=vehicle_id)
        .order_by(FuelEntry.created_at.desc(), FuelEntry.id.desc())
        .all()
    )


def _service_rows(vehicle_id: int) -> list:
    """Записи ТО фуры."""
    return (
        ServiceEntry.query.filter_by(vehicle_id=vehicle_id)
        .order_by(ServiceEntry.created_at.desc(), ServiceEntry.id.desc())
        .all()
    )


def _expense_rows(vehicle_id: int) -> list:
    """Расходы фуры."""
    return (
        Expense.query.filter_by(vehicle_id=vehicle_id)
        .order_by(Expense.date.desc(), Expense.id.desc())
        .all()
    )


def _total_expenses(vehicle_id: int) -> float:
    """Сумма расходов фуры."""
    total = 0.0
    for expense in _expense_rows(vehicle_id):
        total += float(expense.amount or 0)
    return round(total, 2)


def _fuel_stats(vehicle_id: int) -> dict:
    """Сводка по заправкам: литры, деньги, пробег, средний расход."""
    rows = list(reversed(_fuel_rows(vehicle_id)))
    stats = {
        "count": len(rows),
        "total_liters": 0.0,
        "total_amount": 0.0,
        "min_price": 0.0,
        "max_price": 0.0,
        "distance": 0,
        "avg_consumption": None,
        "first_odometer": 0,
        "last_odometer": 0,
    }
    if not rows:
        return stats

    stats["total_liters"] = sum(float(row.liters or 0) for row in rows)
    stats["total_amount"] = sum(float(row.amount or 0) for row in rows)
    prices = [float(row.price or 0) for row in rows if float(row.price or 0) > 0]
    if prices:
        stats["min_price"] = min(prices)
        stats["max_price"] = max(prices)
    odometers = [row.odometer for row in rows if row.odometer]
    if odometers:
        stats["first_odometer"] = odometers[0]
        stats["last_odometer"] = odometers[-1]
        stats["distance"] = max(0, odometers[-1] - odometers[0])
    if stats["distance"] > 0:
        stats["avg_consumption"] = stats["total_liters"] / stats["distance"] * 100
    return stats


def _car_summary(vehicle: Vehicle) -> dict:
    """Краткая сводка по фуре: что показываем в списке и в шапке."""
    item = _vehicle_dict(vehicle)
    fuels = _fuel_rows(vehicle.id)
    services = _service_rows(vehicle.id)
    item["total_expenses"] = _total_expenses(vehicle.id)
    item["fuel_count"] = len(fuels)
    item["service_count"] = len(services)
    item["total_services"] = round(
        sum(float(service.amount or 0) for service in services), 2
    )
    # Ближайшее обслуживание: по пробегу или по дате.
    next_km = None
    next_date = None
    for service in services:
        if service.next_km and (next_km is None or service.next_km < next_km):
            next_km = service.next_km
        if service.next_date and (
            next_date is None or service.next_date < next_date
        ):
            next_date = service.next_date
    item["next_service_km"] = next_km
    item["next_service_date"] = _json_date(next_date)
    stats = _fuel_stats(vehicle.id)
    item["avg_consumption"] = stats.get("avg_consumption")
    item["total_fuel_amount"] = round(stats.get("total_amount", 0), 2)
    item["is_truck"] = _is_truck_model(vehicle.brand or "")
    # Машина в личном списке пользователя (добавлена через поиск).
    item["claimed"] = vehicle.id in _user_vehicle_ids(_current_user_id())
    return item


def _month_start() -> datetime:
    """Начало текущего месяца."""
    now = datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _in_month(value: datetime) -> bool:
    """Дата попадает в текущий месяц."""
    if not value:
        return False
    return value >= _month_start()


def _barrel_rows() -> list:
    """Записи бочки: приходы и расходы в одном списке.

    Старая система хранила бочку как список действий (долили, заправили,
    убавили). В новой базе приходы лежат в fuel_inflow, а расходы по
    бочке — в fuel_outflow, поэтому собираем оба списка вместе.
    """
    items = []
    for inflow in FuelInflow.query.order_by(FuelInflow.date.asc()).all():
        barrel = db.session.get(FuelBarrel, inflow.barrel_id)
        items.append(
            {
                "id": inflow.id,
                "fuel_type": (barrel.fuel_type if barrel else "diesel"),
                "action": "add",
                "liters": float(inflow.liters or 0),
                "plate": "",
                "car_plate": "",
                "created_at": _iso(inflow.date),
                "barrel_id": inflow.barrel_id,
            }
        )

    for outflow in FuelOutflow.query.order_by(FuelOutflow.date.asc()).all():
        barrel = db.session.get(FuelBarrel, outflow.barrel_id)
        vehicle = (
            db.session.get(Vehicle, outflow.vehicle_id) if outflow.vehicle_id else None
        )
        items.append(
            {
                "id": outflow.id,
                "fuel_type": (barrel.fuel_type if barrel else "diesel"),
                "action": "fill" if vehicle else "sub",
                "liters": float(outflow.liters or 0),
                "plate": format_plate(vehicle.plate) if vehicle else "",
                "car_plate": vehicle.plate if vehicle else "",
                "created_at": _iso(outflow.date),
                "barrel_id": outflow.barrel_id,
            }
        )
    items.sort(key=lambda item: item["created_at"])
    return items


def _barrel_balance() -> dict:
    """Сколько топлива осталось в бочке, по видам.

    Остаток = сколько долили минус сколько заправили из неё минус
    сколько убавили.
    """
    balance = {fuel_type: 0.0 for fuel_type in BARREL_TYPES}
    for item in _barrel_rows():
        fuel_type = item["fuel_type"]
        if fuel_type not in balance:
            continue
        liters = float(item["liters"] or 0)
        if item["action"] == "add":
            balance[fuel_type] += liters
        elif item["action"] in ("fill", "sub"):
            balance[fuel_type] -= liters
    return {key: round(value, 2) for key, value in balance.items()}


def _barrel_for_type(fuel_type: str) -> FuelBarrel:
    """Бочка нужного вида топлива (создаёт, если нет)."""
    barrel = FuelBarrel.query.filter_by(fuel_type=fuel_type).first()
    if barrel is None:
        barrel = FuelBarrel(
            name="Бочка дизель" if fuel_type == "diesel" else "Бочка бензин",
            fuel_type=fuel_type,
            capacity_liters=30000.0,
            current_liters=0.0,
        )
        db.session.add(barrel)
        db.session.flush()
    return barrel


def _barrel_fills_by_plate(plate: str) -> list:
    """Заправки из бочки по номеру машины."""
    plate = normalize_plate(plate or "")
    if not plate:
        return []
    rows = []
    for item in _barrel_rows():
        if item["action"] != "fill":
            continue
        if normalize_plate(item["car_plate"] or "") == plate:
            rows.append(item)
    return rows


# ---------- Фуры ----------


@bp.get("/cars")
@require_auth
def api_cars():
    """Список фур, доступных этому пользователю.

    При поиске (q=...) видны все подходящие фуры — чтобы можно было
    найти свою и добавить в свой список.
    """
    query = _clean_text(request.args.get("q", ""), 50)
    vehicles = _visible_vehicles(query)
    if query:
        needle = query.lower()
        vehicles = [
            vehicle
            for vehicle in vehicles
            if needle in (vehicle.plate or "").lower()
            or needle in (vehicle.brand or "").lower()
        ]
    result = [_car_summary(vehicle) for vehicle in vehicles]
    level = _level()
    return jsonify(
        {
            "ok": True,
            "cars": result,
            "is_admin": _is_admin(level),
            "level": level,
        }
    )


@bp.get("/cars/<int:vehicle_id>")
@require_auth
def api_car(vehicle_id: int):
    """Одна фура: данные и счётчики."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error
    return jsonify(
        {"ok": True, "car": _car_summary(vehicle), "level": _level()}
    )


@bp.get("/cars/<int:vehicle_id>/stats")
@require_auth
def api_car_stats(vehicle_id: int):
    """Сводка по заправкам: расход, суммы, цены."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error
    stats = _fuel_stats(vehicle.id)
    return jsonify({"ok": True, "stats": stats})


@bp.post("/cars/<int:vehicle_id>/claim")
@require_auth
def api_claim_car(vehicle_id: int):
    """Добавляет фуру в личный список пользователя.

    Машина, найденная поиском, сохраняется в таблицу user_vehicles -
    после этого она видна в «Моих автомобилях» без повторного поиска.
    """
    vehicle = _vehicle_by_id(vehicle_id)
    if vehicle is None:
        return _fail("машина не найдена", 404)
    if (vehicle.status or "active") != "active":
        return _fail("нет доступа к этой машине", 403)

    user_id = _current_user_id()
    if not user_id:
        return _fail("нет доступа", 401)

    existing = UserVehicle.query.filter_by(
        user_id=user_id, vehicle_id=vehicle.id
    ).first()
    if existing is None:
        db.session.add(UserVehicle(user_id=user_id, vehicle_id=vehicle.id))
        db.session.commit()
    g._my_vehicle_ids = None
    return jsonify({"ok": True, "message": "машина добавлена в ваш список"})


@bp.delete("/cars/<int:vehicle_id>/claim")
@require_auth
def api_unclaim_car(vehicle_id: int):
    """Убирает фуру из личного списка пользователя."""
    vehicle = _vehicle_by_id(vehicle_id)
    if vehicle is None:
        return _fail("машина не найдена", 404)

    user_id = _current_user_id()
    if not user_id:
        return _fail("нет доступа", 401)

    existing = UserVehicle.query.filter_by(
        user_id=user_id, vehicle_id=vehicle.id
    ).first()
    if existing is not None:
        db.session.delete(existing)
        db.session.commit()
    g._my_vehicle_ids = None
    return jsonify({"ok": True, "message": "машина убрана из вашего списка"})


@bp.post("/cars")
@require_auth
def api_add_car():
    """Добавить фуру из приложения."""
    data = request.get_json(silent=True) or {}
    model = _clean_text(data.get("model"), 100)
    plate = normalize_plate(_clean_text(data.get("plate"), 20))
    mileage = _whole_number(data.get("mileage"))
    if mileage is None:
        mileage = 0
    if mileage < 0:
        return _fail("пробег не может быть отрицательным")
    if not model or not plate:
        return _fail("нужна марка и номер")

    existing = Vehicle.query.filter_by(plate=plate).first()
    if existing is not None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"Машина с номером {format_plate(plate)} уже есть в базе",
                    "existing_id": existing.id,
                    "existing_model": existing.brand,
                }
            ),
            400,
        )

    user = getattr(g, "current_user", None)
    vehicle = Vehicle(
        plate=plate,
        brand=model,
        current_mileage=mileage,
        driver_id=user.id if user else None,
        status="active",
    )
    db.session.add(vehicle)
    db.session.flush()
    # Новая машина сразу попадает в личный список добавившего её.
    if user is not None:
        db.session.add(UserVehicle(user_id=user.id, vehicle_id=vehicle.id))
    db.session.commit()
    return jsonify({"ok": True, "id": vehicle.id, "message": "Машина добавлена"})


@bp.delete("/cars/<int:vehicle_id>")
@require_auth
def api_delete_car(vehicle_id: int):
    """Удалить фуру вместе с её записями."""
    vehicle = _vehicle_by_id(vehicle_id)
    if vehicle is None:
        return _fail("машина не найдена", 404)
    if not _is_admin(_level()):
        return _fail("нет доступа к этой машине", 403)

    for entry in _fuel_rows(vehicle.id):
        db.session.delete(entry)
    for service in _service_rows(vehicle.id):
        db.session.delete(service)
    for expense in _expense_rows(vehicle.id):
        db.session.delete(expense)
    db.session.delete(vehicle)
    db.session.commit()
    return jsonify({"ok": True, "message": "Машина удалена"})


@bp.post("/cars/<int:vehicle_id>/mileage")
@require_auth
def api_set_mileage(vehicle_id: int):
    """Поставить новый пробег фуры."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    mileage, problem, warning = _check_odometer(data.get("mileage"), vehicle)
    if problem:
        return _fail(problem)

    vehicle.current_mileage = mileage
    db.session.commit()
    result = {"ok": True, "message": "Пробег обновлён", "mileage": mileage}
    if warning:
        result["warning"] = warning
    return jsonify(result)


@bp.post("/cars/<int:vehicle_id>/plate")
@require_auth
def api_set_plate(vehicle_id: int):
    """Поправить госномер фуры (если номер обрезался при вводе)."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    raw = _clean_text(data.get("plate"), 20)
    if not raw:
        return _fail("напишите номер машины")
    plate = normalize_plate(raw)
    if len(plate) < 6:
        return _fail("номер слишком короткий")

    existing = Vehicle.query.filter(Vehicle.plate == plate, Vehicle.id != vehicle.id).first()
    if existing is not None:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"Номер {format_plate(plate)} уже занят другой машиной",
                    "existing_id": existing.id,
                    "existing_model": existing.brand,
                }
            ),
            400,
        )

    vehicle.plate = plate
    db.session.commit()
    return jsonify(
        {"ok": True, "message": "Номер обновлён", "plate": format_plate(plate)}
    )


# ---------- Заправки и ТО ----------


@bp.get("/cars/<int:vehicle_id>/fuel")
@require_auth
def api_fuel_list(vehicle_id: int):
    """История заправок: обычные и заправки из бочки."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    fuel = []
    for row in _fuel_rows(vehicle.id):
        fuel.append(
            {
                "id": row.id,
                "source": "barrel" if (row.location or "").strip() else "manual",
                "fuel_type": None,
                "liters": float(row.liters or 0),
                "price": float(row.price or 0),
                "amount": float(row.amount or 0),
                "odometer": row.odometer,
                "is_full": 1 if row.is_full else 0,
                "location": row.location or "",
                "created_at": _iso(row.created_at),
            }
        )
    # Заправки из бочки приходят по номеру машины: бочка общая,
    # а фура может быть заведена кем-то ещё.
    for row in _barrel_fills_by_plate(vehicle.plate):
        fuel.append(
            {
                "id": f"b{row['id']}",
                "source": "barrel",
                "fuel_type": row["fuel_type"],
                "liters": row["liters"],
                "price": 0,
                "amount": 0,
                "odometer": None,
                "is_full": 0,
                "location": "",
                "created_at": row["created_at"],
            }
        )
    fuel.sort(key=lambda item: item["created_at"], reverse=True)
    return jsonify({"ok": True, "fuel": fuel})


@bp.post("/cars/<int:vehicle_id>/fuel")
@require_auth
def api_add_fuel(vehicle_id: int):
    """Добавить заправку: литры, цена за литр, одометр, полный бак."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    liters, problem = _check_amount(data.get("liters"), "количество литров")
    if problem:
        return _fail(problem)
    price, problem = _check_amount(data.get("price"), "цена")
    if problem:
        return _fail(problem)
    odometer, problem, _warning = _check_odometer(data.get("odometer"), vehicle)
    if problem:
        return _fail(problem)

    is_full = data.get("is_full", True)
    is_full = 1 if (is_full in (1, "1", True, "true", "yes")) else 0
    entry = FuelEntry(
        vehicle_id=vehicle.id,
        liters=liters,
        price=price,
        amount=round(liters * price, 2),
        odometer=odometer,
        is_full=bool(is_full),
        location="",
        created_at=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": "Заправка записана",
            "id": entry.id,
            "total": _total_expenses(vehicle.id),
            "odometer": int(vehicle.current_mileage or 0),
            "amount": round(liters * price, 2),
        }
    )


@bp.get("/cars/<int:vehicle_id>/services")
@require_auth
def api_services(vehicle_id: int):
    """История технического обслуживания."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    services = []
    for row in _service_rows(vehicle.id):
        services.append(
            {
                "id": row.id,
                "description": row.description or "",
                "details": row.details or "",
                "amount": float(row.amount or 0),
                "odometer": row.odometer,
                "next_km": row.next_km,
                "next_date": _json_date(row.next_date),
                "created_at": _iso(row.created_at),
            }
        )
    return jsonify({"ok": True, "services": services})


@bp.post("/cars/<int:vehicle_id>/services")
@require_auth
def api_add_service(vehicle_id: int):
    """Добавить обслуживание: что делали, за сколько, на каком пробеге."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    description = _clean_text(data.get("description"))
    details = _clean_text(data.get("details"), 1000)
    if not description:
        return _fail("напишите, что сделали")

    # Сумма необязательна: бывает ТО по времени, без счёта.
    amount = _number(data.get("amount"), 0) or 0
    if amount < 0:
        return _fail("сумма не может быть отрицательной")
    if amount > MAX_AMOUNT:
        return _fail("сумма слишком большая")

    odometer = 0
    if data.get("odometer") not in (None, ""):
        odometer, problem, _warning = _check_odometer(data.get("odometer"), vehicle)
        if problem:
            return _fail(problem)

    next_km = None
    if data.get("next_km") not in (None, ""):
        value = _whole_number(data.get("next_km"))
        if value is None or value <= 0:
            return _fail("следующий пробег — целое число больше нуля")
        if value <= int(vehicle.current_mileage or 0):
            return _fail("следующий пробег должен быть больше текущего")
        next_km = value

    next_date = None
    if data.get("next_date"):
        next_date = _check_date(data.get("next_date"))
        if not next_date:
            return _fail("дата в виде 2026-10-31")

    service = ServiceEntry(
        vehicle_id=vehicle.id,
        amount=round(amount, 2),
        description=description,
        details=details,
        odometer=odometer,
        next_km=next_km,
        next_date=datetime.strptime(next_date, "%Y-%m-%d") if next_date else None,
        created_at=datetime.utcnow(),
    )
    db.session.add(service)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": "Обслуживание записано",
            "id": service.id,
            "total": _total_expenses(vehicle.id),
            "odometer": int(vehicle.current_mileage or 0),
            "next_km": next_km,
            "next_date": next_date,
        }
    )


@bp.delete("/cars/<int:vehicle_id>/services/<int:service_id>")
@require_auth
def api_delete_service(vehicle_id: int, service_id: int):
    """Удалить запись об обслуживании."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    service = db.session.get(ServiceEntry, service_id)
    if service is None or service.vehicle_id != vehicle.id:
        return _fail("запись не найдена", 404)

    db.session.delete(service)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": "Запись удалена",
            "total": _total_expenses(vehicle.id),
            "odometer": int(vehicle.current_mileage or 0),
        }
    )


@bp.get("/cars/<int:vehicle_id>/expenses")
@require_auth
def api_expenses(vehicle_id: int):
    """История расходов по фуре."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    expenses = []
    for row in _expense_rows(vehicle.id):
        expenses.append(
            {
                "id": row.id,
                "description": row.comment or "",
                "details": "",
                "amount": float(row.amount or 0),
                "created_at": _iso(row.date),
            }
        )
    return jsonify({"ok": True, "expenses": expenses})


@bp.post("/cars/<int:vehicle_id>/expenses")
@require_auth
def api_add_expense(vehicle_id: int):
    """Добавить расход: что сделали и сколько заплатили."""
    vehicle, error = _car_for_user(vehicle_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    description = _clean_text(data.get("description"))
    details = _clean_text(data.get("details"), 1000)
    amount, problem = _check_amount(data.get("amount"), "сумма")
    if problem:
        return _fail(problem)
    if not description:
        return _fail("напишите, что сделали")

    user = getattr(g, "current_user", None)
    expense = Expense(
        vehicle_id=vehicle.id,
        category="прочее",
        amount=amount,
        comment=" ".join(part for part in (description, details) if part) or None,
        status="approved",
        submitted_by=user.id if user else None,
        approved_by=user.id if user else None,
        date=datetime.utcnow(),
    )
    db.session.add(expense)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "message": "Расход записан",
            "id": expense.id,
            "total": _total_expenses(vehicle.id),
            "odometer": int(vehicle.current_mileage or 0),
        }
    )


# ---------- Каталог, справочники, бочка ----------


@bp.get("/catalog")
@require_auth
def api_catalog():
    """Список работ по обслуживанию — чтобы выбирать из кнопок, а не вручную."""
    items = [
        {
            "id": item["id"],
            "group": item["group"],
            "title": item["title"],
            "detail": item.get("detail", ""),
        }
        for item in all_items()
    ]
    return jsonify({"ok": True, "items": items})


@bp.get("/drivers")
@require_auth
def api_drivers():
    """Список водителей."""
    rows = Driver.query.order_by(Driver.name.asc()).all()
    return jsonify(
        {
            "ok": True,
            "drivers": [
                {
                    "id": row.id,
                    "name": row.name,
                    "created_at": _iso(row.created_at),
                }
                for row in rows
            ],
        }
    )


@bp.post("/drivers")
@require_auth
def api_driver_add():
    """Добавить водителя."""
    data = request.get_json(silent=True) or {}
    name = _clean_text(data.get("name"), 50)
    if not name:
        return _fail("дайте имя водителя")
    user = getattr(g, "current_user", None)
    driver = Driver(name=name, user_id=user.id if user else None)
    db.session.add(driver)
    db.session.commit()
    return jsonify({"ok": True, "id": driver.id})


@bp.delete("/drivers/<int:driver_id>")
@require_auth
def api_driver_delete(driver_id: int):
    """Удалить водителя. Водитель, который используется в отчётах, не удаляется."""
    driver = db.session.get(Driver, driver_id)
    if driver is None:
        return _fail("водитель не найден", 404)
    used = Report.query.filter_by(driver_id=driver.id).first()
    if used is not None:
        return _fail("водитель используется в отчётах — сначала удалите отчёты")
    db.session.delete(driver)
    db.session.commit()
    return jsonify({"ok": True, "message": "Водитель удалён"})


@bp.get("/customers")
@require_auth
def api_customers():
    """Список заказчиков."""
    rows = Customer.query.order_by(Customer.name.asc()).all()
    return jsonify(
        {
            "ok": True,
            "customers": [
                {"id": row.id, "name": row.name, "created_at": _iso(row.created_at)}
                for row in rows
            ],
        }
    )


@bp.post("/customers")
@require_auth
def api_customer_add():
    """Добавить заказчика."""
    data = request.get_json(silent=True) or {}
    name = _clean_text(data.get("name"), 50)
    if not name:
        return _fail("дайте имя заказчика")
    customer = Customer(name=name)
    db.session.add(customer)
    db.session.commit()
    return jsonify({"ok": True, "id": customer.id})


@bp.delete("/customers/<int:customer_id>")
@require_auth
def api_customer_delete(customer_id: int):
    """Удалить заказчика. Заказчик, который используется в отчётах, не удаляется."""
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        return _fail("заказчик не найден", 404)
    used = Report.query.filter_by(customer_id=customer.id).first()
    if used is not None:
        return _fail("заказчик используется в отчётах — сначала удалите отчёты")
    db.session.delete(customer)
    db.session.commit()
    return jsonify({"ok": True, "message": "Заказчик удалён"})


@bp.get("/barrel")
@require_auth
def api_barrel_list():
    """История бочки и остаток топлива по видам.

    Доступна у менеджера и выше (уровень 2).
    """
    if not _is_full_admin(_level()):
        return _fail("бочка доступна только у администратора полного доступа", 403)
    return jsonify(
        {
            "ok": True,
            "items": _barrel_rows(),
            "balance": _barrel_balance(),
        }
    )


@bp.post("/barrel")
@require_auth
def api_barrel_add():
    """Записать в бочку: долили топливо, заправили из неё фуру или убавили литры.

    Действие приходит от клиента: 'add', 'fill' или 'sub'.
    Номер фуры нужен только для 'fill'.
    """
    data = request.get_json(silent=True) or {}
    fuel_type = _clean_text(data.get("fuel_type"), 20).lower()
    if fuel_type not in BARREL_TYPES:
        return _fail("выберите дизель или бензин")

    if not _is_full_admin(_level()):
        return _fail("бочка доступна только у администратора полного доступа", 403)

    action = _clean_text(data.get("action"), 20).lower() or "fill"
    if action not in BARREL_ACTIONS:
        return _fail("неизвестное действие")

    liters, problem = _check_amount(data.get("liters"), "литры")
    if problem:
        return _fail(problem)

    vehicle = None
    if action == "fill":
        raw_plate = _clean_text(data.get("plate"), 20)
        if not raw_plate:
            return _fail("напишите номер машины")
        plate = normalize_plate(raw_plate)
        vehicle = Vehicle.query.filter_by(plate=plate).first()
        # Дизель заправляют грузовики, а они должны быть в базе:
        # номер выбирают из списка. Для бензина номер вводят руками,
        # такой фуры в базе может не быть — это нормально.
        if fuel_type == "diesel" and vehicle is None:
            return _fail("для дизеля номер должен быть в базе — выбери машину из списка")

    barrel = _barrel_for_type(fuel_type)
    if action == "add":
        from app.models import FuelInflow

        record = FuelInflow(
            barrel_id=barrel.id,
            liters=liters,
            price_per_liter=0.0,
            total=0.0,
            date=datetime.utcnow(),
        )
        barrel.current_liters = float(barrel.current_liters or 0) + liters
    else:
        record = FuelOutflow(
            barrel_id=barrel.id,
            vehicle_id=vehicle.id if vehicle else None,
            liters=liters,
            cost_per_liter=0.0,
            total=0.0,
            date=datetime.utcnow(),
        )
        barrel.current_liters = float(barrel.current_liters or 0) - liters
    db.session.add(record)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "id": record.id,
            "balance": _barrel_balance(),
            "message": "Записано",
        }
    )


@bp.post("/barrel/clear")
@require_auth
def api_barrel_clear():
    """Очистить историю бочки."""
    if not _is_full_admin(_level()):
        return _fail("очищать историю бочки может только администратор полного доступа", 403)
    removed = len(_barrel_rows())
    for record in FuelInflow.query.all():
        db.session.delete(record)
    for record in FuelOutflow.query.all():
        db.session.delete(record)
    for barrel in FuelBarrel.query.all():
        barrel.current_liters = 0.0
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "removed": removed,
            "balance": _barrel_balance(),
            "message": "Историю бочки очищено",
        }
    )


# ---------- Затраты и отчёты ----------


@bp.get("/month-costs")
@require_auth
def api_month_costs():
    """Итоговые затраты за текущий месяц по видимым фурам.

    Доступно с 2 уровня (оператор) и выше.
    """
    if not _is_full_admin(_level()):
        return _fail("затраты доступны с 2 уровня", 403)

    vehicles = _visible_vehicles()
    month_start = _month_start()
    totals = {"expenses": 0.0, "fuel": 0.0, "services": 0.0, "total": 0.0}
    car_items = []

    for vehicle in vehicles:
        car_totals = {"expenses": 0.0, "fuel": 0.0, "services": 0.0, "total": 0.0}
        for expense in _expense_rows(vehicle.id):
            if _in_month(expense.date):
                car_totals["expenses"] += float(expense.amount or 0)
        for entry in _fuel_rows(vehicle.id):
            if _in_month(entry.created_at):
                car_totals["fuel"] += float(entry.amount or 0)
        for service in _service_rows(vehicle.id):
            if _in_month(service.created_at):
                car_totals["services"] += float(service.amount or 0)
        for key in ("expenses", "fuel", "services"):
            car_totals[key] = round(car_totals[key], 2)
        car_totals["total"] = round(
            car_totals["expenses"] + car_totals["fuel"] + car_totals["services"], 2
        )

        if car_totals["total"] > 0:
            car_items.append(
                {
                    "id": vehicle.id,
                    "model": vehicle.brand or "",
                    "plate": vehicle.plate or "",
                    **car_totals,
                }
            )
        for key in totals:
            totals[key] += car_totals[key]

    for key in totals:
        totals[key] = round(totals[key], 2)

    return jsonify(
        {
            "ok": True,
            "costs": {
                "month": month_start.strftime("%Y-%m"),
                "totals": totals,
                "cars": car_items,
            },
        }
    )


def _car_report_summary(vehicle: Vehicle) -> dict:
    """Сводка по одной фуре для общего отчёта."""
    expenses = _expense_rows(vehicle.id)
    fuels = _fuel_rows(vehicle.id)
    services = _service_rows(vehicle.id)
    return {
        "id": vehicle.id,
        "model": vehicle.brand or "",
        "plate": vehicle.plate or "",
        "expense_total": round(
            sum(float(row.amount or 0) for row in expenses), 2
        ),
        "expense_count": len(expenses),
        "fuel_count": len(fuels),
        "fuel_total_liters": round(
            sum(float(row.liters or 0) for row in fuels), 1
        ),
        "fuel_total_amount": round(
            sum(float(row.amount or 0) for row in fuels), 2
        ),
        "service_count": len(services),
        "service_total": round(
            sum(float(row.amount or 0) for row in services), 2
        ),
        "mileage": int(vehicle.current_mileage or 0),
    }


@bp.get("/report-summary")
@require_auth
def api_report_summary():
    """Сводная статистика по фурам — JSON.

    Доступно у суперадмина (уровень 3).
    """
    if not _is_super_admin(_level()):
        return _fail("отчёт доступен только супер-админу", 403)

    fuel_type = _clean_text(request.args.get("fuel_type"), 20).lower()
    if fuel_type and fuel_type not in BARREL_TYPES:
        return _fail("неизвестный вид топлива")

    vehicles = Vehicle.query.order_by(Vehicle.id.asc()).all()
    totals = {
        "total_expenses": 0.0,
        "total_expense_count": 0,
        "total_fuel_liters": 0.0,
        "total_fuel_amount": 0.0,
        "total_services": 0.0,
        "total_service_count": 0,
        "fuel_count": 0,
        "service_total": 0.0,
        "service_count": 0,
        "car_count": len(vehicles),
    }
    car_summaries = []
    for vehicle in vehicles:
        summary = _car_report_summary(vehicle)
        car_summaries.append(summary)
        totals["total_expenses"] += summary["expense_total"]
        totals["total_expense_count"] += summary["expense_count"]
        totals["total_fuel_liters"] += summary["fuel_total_liters"]
        totals["total_fuel_amount"] += summary["fuel_total_amount"]
        totals["total_services"] += summary["service_total"]
        totals["total_service_count"] += summary["service_count"]
        totals["fuel_count"] += summary["fuel_count"]
        totals["service_total"] += summary["service_total"]
        totals["service_count"] += summary["service_count"]

    barrel_totals = {
        "diesel": {"add": 0.0, "fill": 0.0, "sub": 0.0},
        "petrol": {"add": 0.0, "fill": 0.0, "sub": 0.0},
    }
    for item in _barrel_rows():
        if fuel_type and item["fuel_type"] != fuel_type:
            continue
        group = barrel_totals.get(item["fuel_type"])
        if group is None:
            continue
        group[item["action"]] = round(group[item["action"]] + item["liters"], 1)

    result = {
        "totals": totals,
        "car_summaries": car_summaries,
        "barrel_totals": barrel_totals,
    }
    if fuel_type:
        result["filter"] = fuel_type
    return jsonify({"ok": True, "report": result})


def _history_lines_for_vehicle(vehicle: Vehicle) -> list:
    """Строки истории по одной фуре (для выгрузки текстом)."""
    lang = current_lang()
    lines = [
        f"{t('Машина:', lang)} {vehicle.brand or ''} {format_plate(vehicle.plate)}",
        f"{t('Пробег:', lang)} {int(vehicle.current_mileage or 0)} км",
        "",
    ]
    lines.append(t("Заправки:", lang))
    for entry in _fuel_rows(vehicle.id):
        lines.append(
            f"  {_iso(entry.created_at)} | {float(entry.liters or 0):.1f} л | "
            f"{float(entry.price or 0):.2f} | {float(entry.amount or 0):.2f} | "
            f"{entry.odometer if entry.odometer is not None else '-'}"
        )
    lines.append("")
    lines.append(t("Обслуживание:", lang))
    for service in _service_rows(vehicle.id):
        lines.append(
            f"  {_iso(service.created_at)} | {service.description or ''} | "
            f"{float(service.amount or 0):.2f} | "
            f"{service.odometer if service.odometer is not None else '-'}"
        )
    lines.append("")
    lines.append(t("Расходы:", lang))
    for expense in _expense_rows(vehicle.id):
        lines.append(
            f"  {_iso(expense.date)} | {expense.comment or ''} | "
            f"{float(expense.amount or 0):.2f}"
        )
    return lines


@bp.get("/report")
@require_auth
def api_report():
    """Выгрузка истории обычным текстом — как отчёт.

    ?car_id=N — история одной фуры;
    ?barrel=diesel|petrol|all — история бочки;
    без параметров — вся история по всем фурам.

    Доступно у суперадмина (уровень 3).
    """
    if not _is_super_admin(_level()):
        return _fail("выгружать историю может только супер-админ", 403)

    vehicle_id = request.args.get("car_id", type=int)
    barrel = _clean_text(request.args.get("barrel"), 20).lower()
    filename = "history.txt"

    if vehicle_id:
        vehicle, error = _car_for_user(vehicle_id)
        if error:
            return error
        lines = _history_lines_for_vehicle(vehicle)
    elif barrel:
        if barrel not in ("all",) + BARREL_TYPES:
            return _fail("неизвестный вид топлива")
        lang = current_lang()
        lines = [t("Бочка:", lang), ""]
        for item in _barrel_rows():
            if barrel != "all" and item["fuel_type"] != barrel:
                continue
            fuel_name = t(BARREL_TYPE_NAME.get(item["fuel_type"], item["fuel_type"]), lang)
            action_name = t(BARREL_ACTION_NAME.get(item["action"], item["action"]), lang)
            lines.append(
                f"  {_iso(item['created_at'])} | {fuel_name} | "
                f"{action_name} | {item['liters']:.1f} л | {item['car_plate']}"
            )
        filename = "bochka.txt"
    else:
        lines = []
        for vehicle in Vehicle.query.order_by(Vehicle.id.asc()).all():
            lines.extend(_history_lines_for_vehicle(vehicle))
            lines.append("")

    # UTF-8 с меткой порядка байтов (BOM): без неё Excel и «Блокнот»
    # показывают русский текст нечитаемыми символами.
    report = "\n".join(lines)
    response = Response(
        report.encode("utf-8-sig"), mimetype="text/plain; charset=utf-8"
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.get("/reports")
@require_auth
def api_reports():
    """Список отчётов с фильтрацией.

    Доступно только у суперадмина (уровень 3).
    """
    if not _is_super_admin(_level()):
        return _fail("отчёты доступны только супер-админу", 403)

    driver_id = request.args.get("driver_id", type=int)
    customer_id = request.args.get("customer_id", type=int)
    days = request.args.get("days", type=int)

    query = Report.query.order_by(Report.created_at.desc(), Report.id.desc())
    if driver_id:
        query = query.filter_by(driver_id=driver_id)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    if days:
        since = datetime.utcnow() - timedelta(days=days)
        query = query.filter(Report.created_at >= since)

    rows = query.all()
    reports = []
    for row in rows:
        driver = db.session.get(Driver, row.driver_id) if row.driver_id else None
        customer = (
            db.session.get(Customer, row.customer_id) if row.customer_id else None
        )
        reports.append(
            {
                "id": row.id,
                "driver": driver.name if driver else (row.driver or ""),
                "customer": customer.name if customer else (row.client or ""),
                "client": row.client or "",
                "mileage": row.mileage,
                "paid": 1 if row.paid else 0,
                "created_at": _iso(row.created_at),
            }
        )
    return jsonify({"ok": True, "reports": reports})


@bp.post("/reports")
@require_auth
def api_report_add():
    """Добавить отчёт.

    Доступно только у суперадмина (уровень 3).
    """
    if not _is_super_admin(_level()):
        return _fail("отчёты доступны только супер-админу", 403)

    data = request.get_json(silent=True) or {}
    driver_id = data.get("driver_id")
    customer_id = data.get("customer_id")
    mileage = data.get("mileage")
    paid = data.get("paid", 0)

    if driver_id is None or customer_id is None or mileage is None:
        return _fail("недостаточно данных")

    driver = db.session.get(Driver, driver_id)
    customer = db.session.get(Customer, customer_id)
    if driver is None or customer is None:
        return _fail("недостаточно данных")

    mileage_value = _whole_number(mileage)
    if mileage_value is None:
        return _fail("недостаточно данных")

    report = Report(
        vehicle_id=data.get("vehicle_id"),
        customer_id=customer.id,
        driver_id=driver.id,
        client=customer.name,
        driver=driver.name,
        mileage=mileage_value,
        paid=bool(paid),
        created_at=datetime.utcnow(),
    )
    db.session.add(report)
    db.session.commit()
    return jsonify({"ok": True, "id": report.id})


@bp.delete("/reports/<int:report_id>")
@require_auth
def api_report_delete(report_id: int):
    """Удалить отчёт.

    Доступно только у суперадмина (уровень 3).
    """
    if not _is_super_admin(_level()):
        return _fail("отчёты доступны только супер-админу", 403)

    report = db.session.get(Report, report_id)
    if report is None:
        return _fail("отчёт не найден", 404)
    db.session.delete(report)
    db.session.commit()
    return jsonify({"ok": True, "message": "Отчёт удалён"})


@bp.patch("/reports/<int:report_id>/paid")
@require_auth
def api_report_paid(report_id: int):
    """Отметить отчёт оплаченным или снять отметку.

    Доступно только у суперадмина (уровень 3).
    """
    if not _is_super_admin(_level()):
        return _fail("отчёты доступны только супер-админу", 403)

    report = db.session.get(Report, report_id)
    if report is None:
        return _fail("отчёт не найден", 404)
    data = request.get_json(silent=True) or {}
    paid = data.get("paid", True)
    report.paid = bool(paid)
    db.session.commit()
    return jsonify({"ok": True, "paid": report.paid})
