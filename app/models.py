# -*- coding: utf-8 -*-
"""Модели SQLAlchemy для car-tracker.

Таблицы:
- users — пользователи бота (роли: admin, driver)
- vehicles — фуры (связь: водитель → пользователь)
- expenses — расходы (категория, сумма, дата, фото)
- fuel_barrels — емкости топлива (дизель/бензин)
- fuel_inflow — приход топлива в бочку
- fuel_outflow — расход топлива из бочки (заправка фуры)
"""

from datetime import datetime
from . import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(120), unique=True, nullable=True)
    role = db.Column(db.String(20), default="driver")  # admin | driver
    is_whitelisted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    vehicles = db.relationship("Vehicle", backref="driver", lazy=True)
    fuel_outflows = db.relationship("FuelOutflow", backref="driver", lazy=True)

    def is_admin(self):
        return self.role == "admin" and self.is_whitelisted

    def can_manage_vehicles(self):
        return self.is_admin()

    def can_manage_expenses(self, vehicle=None):
        if self.is_admin():
            return True
        if vehicle and vehicle.driver_id == self.id:
            return True
        return False

    def can_view_vehicle(self, vehicle):
        if self.is_admin():
            return True
        return vehicle.driver_id == self.id

    def can_add_expense_to_vehicle(self, vehicle):
        if self.is_admin():
            return True
        return vehicle.driver_id == self.id

    def __repr__(self):
        return f"<User tg_id={self.tg_id} role={self.role}>"


class Vehicle(db.Model):
    __tablename__ = "vehicles"

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(20), nullable=False)  # гос. номер
    brand = db.Column(db.String(80), nullable=False)  # марка
    vin = db.Column(db.String(50), unique=True, nullable=True)  # VIN
    driver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
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


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # категория расхода
    amount = db.Column(db.Float, nullable=False)  # сумма
    date = db.Column(db.DateTime, default=datetime.utcnow)
    comment = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)  # ссылка на фото чека

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
        return f"<Expense {self.amount} {self.category}>"

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