# -*- coding: utf-8 -*-
"""Модели SQLAlchemy для car-tracker.

Таблицы:
- users — пользователи бота (уровни: 1, 2, 3)
- vehicles — фуры (связь: водитель → пользователь)
- user_vehicles — личный список машин пользователя (связь many-to-many)
- expenses — расходы (категория, сумма, дата, фото, статус approval)
- fuel_barrels — емкости топлива (дизель/бензин)
- fuel_inflow — приход топлива в бочку
- fuel_outflow — расход топлива из бочки (заправка фуры)
- audit_logs — аудит-история изменений
"""

from datetime import datetime
import json
from app import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(120), unique=True, nullable=True)
    level = db.Column(db.Integer, default=1)  # 1=user, 2=operator, 3=super_admin
    is_whitelisted = db.Column(db.Boolean, default=False)
    # Язык интерфейса: ru или uk. Выбирается в боте (/language) и в Mini App.
    # None - язык ещё не выбран (при первом входе показываем выбор).
    lang = db.Column(db.String(2), nullable=True, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    vehicles = db.relationship("Vehicle", backref="driver", lazy=True, foreign_keys="Vehicle.driver_id")
    fuel_outflows = db.relationship("FuelOutflow", backref="driver", lazy=True)
    submitted_expenses = db.relationship("Expense", backref="submitter", lazy=True, foreign_keys="Expense.submitted_by")
    approved_expenses = db.relationship("Expense", backref="approver", lazy=True, foreign_keys="Expense.approved_by")
    submitted_fuels = db.relationship("FuelEntry", backref="fuel_submitter", lazy=True, foreign_keys="FuelEntry.submitted_by")
    approved_fuels = db.relationship("FuelEntry", backref="fuel_approver", lazy=True, foreign_keys="FuelEntry.approved_by")
    submitted_services = db.relationship("ServiceEntry", backref="service_submitter", lazy=True, foreign_keys="ServiceEntry.submitted_by")
    approved_services = db.relationship("ServiceEntry", backref="service_approver", lazy=True, foreign_keys="ServiceEntry.approved_by")

    def is_level_1(self):
        return self.level == 1

    def is_level_2(self):
        return self.level == 2

    def is_level_3(self):
        return self.level == 3

    def can_manage_vehicles(self):
        return self.level in (2, 3)

    def can_manage_barrels(self):
        return self.level in (2, 3)

    def can_manage_expenses(self):
        return self.level in (2, 3)

    def can_view_vehicle(self, vehicle):
        """Уровень 1 видит только активные фуры, уровни 2/3 — все.

        При открытом доступе (Config.OPEN_ACCESS) видны все фуры.
        """
        from app.config import Config

        if Config.OPEN_ACCESS:
            return True
        if self.level in (2, 3):
            return True
        return vehicle.status == "active"

    def can_add_expense(self, vehicle=None):
        """Можно ли добавить расход по этой фуре."""
        from app.config import Config

        if Config.OPEN_ACCESS:
            return True
        if self.level in (2, 3):
            return True
        if self.level == 1 and vehicle and vehicle.status == "active":
            return True
        return False

    def can_view_logs(self):
        return self.level in (2, 3)

    def can_clear_logs(self):
        return self.level == 3

    def __repr__(self):
        return f"<User tg_id={self.tg_id} level={self.level}>"


class Vehicle(db.Model):
    __tablename__ = "vehicles"

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(20), nullable=False)  # гос. номер
    brand = db.Column(db.String(80), nullable=False)  # марка
    vin = db.Column(db.String(50), unique=True, nullable=True)  # VIN
    driver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    # Водитель по имени (из старой системы). Не обязателен: в новой системе
    # за фурой закреплён пользователь Telegram, а имя нужно для актов.
    assigned_driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)
    status = db.Column(db.String(20), default="active")  # active | archived | in_repair
    wialon_id = db.Column(db.BigInteger, unique=True, nullable=True)  # ID в Wialon
    current_mileage = db.Column(db.Integer, default=0)  # пробег (км)
    avg_fuel_consumption = db.Column(db.Float, default=30.0)  # норма расхода л/100км
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    expenses = db.relationship("Expense", backref="vehicle", lazy=True)

    def __repr__(self):
        return f"<Vehicle {self.plate}>"

    @property
    def display_name(self):
        return f"{self.brand} ({self.plate})"


class UserVehicle(db.Model):
    """Личный список машин пользователя.

    Аналог таблицы car_users старой системы: машина может принадлежать
    нескольким водителям (каждый добавляет её себе в список), поэтому
    связь хранится отдельной таблицей, а не в vehicles.driver_id.
    """

    __tablename__ = "user_vehicles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ограничение называем явно: на SQLite безымянные ограничения плохо
    # переживают пересоздание таблицы.
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "vehicle_id", name="uq_user_vehicles_user_vehicle"
        ),
    )

    user = db.relationship("User", backref="user_vehicles", lazy=True)
    vehicle = db.relationship("Vehicle", backref="user_vehicles", lazy=True)

    def __repr__(self):
        return f"<UserVehicle user={self.user_id} vehicle={self.vehicle_id}>"


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # категория расхода
    amount = db.Column(db.Float, nullable=False)  # сумма
    date = db.Column(db.DateTime, default=datetime.utcnow)
    comment = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)  # ссылка на фото чека
    status = db.Column(db.String(20), default="pending")  # pending | approved | rejected
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # кто создал
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # кто одобрил
    approved_at = db.Column(db.DateTime, nullable=True)  # когда одобрил

    CATEGORIES = [
        "топливо",
        "ремонт",
        "запчасти",
        "шины",
        "штрафы",
        "дорога/платные участки",
        "мойка",
        "прочее",
    ]

    def __repr__(self):
        return f"<Expense {self.amount} {self.category} status={self.status}>"

    @property
    def formatted_amount(self):
        return f"₴ {self.amount:,.0f}"


class FuelBarrel(db.Model):
    __tablename__ = "fuel_barrels"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    fuel_type = db.Column(db.String(20), nullable=False)  # diesel | petrol
    capacity_liters = db.Column(db.Float, nullable=False)
    current_liters = db.Column(db.Float, default=0.0)
    avg_price_per_liter = db.Column(db.Float, nullable=True)
    threshold_liters = db.Column(db.Float, default=100.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    inflows = db.relationship("FuelInflow", backref="barrel", lazy=True)
    outflows = db.relationship("FuelOutflow", backref="barrel", lazy=True)

    def __repr__(self):
        return f"<FuelBarrel {self.name}>"

    @property
    def remaining_pct(self):
        if self.capacity_liters == 0:
            return 0.0
        return round((self.current_liters / self.capacity_liters) * 100, 1)

    @property
    def is_low(self):
        return self.current_liters <= self.threshold_liters

    @property
    def formatted_current(self):
        return f"{self.current_liters:,.0f} / {self.capacity_liters:,.0f} л"

    @property
    def formatted_remaining(self):
        return f"{self.remaining_pct}%"


class FuelInflow(db.Model):
    __tablename__ = "fuel_inflow"

    id = db.Column(db.Integer, primary_key=True)
    barrel_id = db.Column(db.Integer, db.ForeignKey("fuel_barrels.id"), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    liters = db.Column(db.Float, nullable=False)
    price_per_liter = db.Column(db.Float, nullable=False)
    supplier = db.Column(db.String(100), nullable=True)
    total = db.Column(db.Float, nullable=False)  # liters * price_per_liter

    def __repr__(self):
        return f"<FuelInflow {self.liters}л @ {self.price_per_liter}>"

    @property
    def formatted_total(self):
        return f"₴ {self.total:,.0f}"


class FuelOutflow(db.Model):
    __tablename__ = "fuel_outflow"

    id = db.Column(db.Integer, primary_key=True)
    barrel_id = db.Column(db.Integer, db.ForeignKey("fuel_barrels.id"), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    liters = db.Column(db.Float, nullable=False)
    cost_per_liter = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)  # liters * cost_per_liter

    def __repr__(self):
        return f"<FuelOutflow {self.liters}л>"

    @property
    def formatted_total(self):
        return f"₴ {self.total:,.0f}"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False)  # create, update, delete, approve, reject
    entity_type = db.Column(db.String(50), nullable=False)  # vehicle, expense, barrel, etc.
    entity_id = db.Column(db.Integer, nullable=True)
    old_values = db.Column(db.Text, nullable=True)  # JSON
    new_values = db.Column(db.Text, nullable=True)  # JSON
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="audit_logs", lazy=True)

    def __repr__(self):
        return f"<AuditLog {self.action} {self.entity_type}#{self.entity_id}>"


class Driver(db.Model):
    """Водитель по имени (из старой системы учёта).

    В новой системе водитель - это пользователь Telegram (User). Но в
    актах и отчётах водитель указывается именем, и один водитель может
    вести несколько машин, поэтому имя храним отдельной записью.
    """

    __tablename__ = "drivers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="drivers")
    vehicles = db.relationship("Vehicle", backref="assigned_driver", lazy=True)

    def __repr__(self):
        return f"<Driver {self.name}>"


class Customer(db.Model):
    """Клиент (заказчик) - для актов и отчётов по фурам."""

    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Customer {self.name}>"


class FuelEntry(db.Model):
    """Заправка фуры: литры, цена, сумма, одометр, место заправки."""

    __tablename__ = "fuel_entries"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    liters = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    odometer = db.Column(db.Integer, nullable=True)
    is_full = db.Column(db.Boolean, default=True)
    location = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Проверка третьим уровнем: водитель присылает запись на проверку.
    status = db.Column(db.String(20), default="approved")  # pending | approved | rejected
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    vehicle = db.relationship("Vehicle", backref="fuel_entries", lazy=True)

    def __repr__(self):
        return f"<FuelEntry {self.liters}л status={self.status}>"


class ServiceEntry(db.Model):
    """Техническое обслуживание по фуре (ремонт, ТО)."""

    __tablename__ = "service_entries"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=True)
    details = db.Column(db.Text, nullable=True)
    odometer = db.Column(db.Integer, nullable=True)
    next_km = db.Column(db.Integer, nullable=True)
    next_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Проверка третьим уровнем: водитель присылает запись на проверку.
    status = db.Column(db.String(20), default="approved")  # pending | approved | rejected
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    vehicle = db.relationship("Vehicle", backref="service_entries", lazy=True)

    def __repr__(self):
        return f"<ServiceEntry {self.amount} status={self.status}>"


class Report(db.Model):
    """Акт по фуре: клиент, водитель, пробег, оплата."""

    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True)
    client = db.Column(db.String(120), nullable=True)
    driver = db.Column(db.String(120), nullable=True)
    mileage = db.Column(db.Integer, nullable=True)
    paid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vehicle = db.relationship("Vehicle", backref="reports", lazy=True)
    customer = db.relationship("Customer", backref="reports", lazy=True)
    driver_ref = db.relationship("Driver", backref="reports", lazy=True)

    def __repr__(self):
        return f"<Report #{self.id}>"


def log_audit(user_id, action, entity_type, entity_id=None, old_values=None, new_values=None):
    """Записать событие в аудит-лог."""
    from app import db
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=json.dumps(old_values, ensure_ascii=False) if old_values is not None else None,
        new_values=json.dumps(new_values, ensure_ascii=False) if new_values is not None else None,
    )
    db.session.add(log)
    return log