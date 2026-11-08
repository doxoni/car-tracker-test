# -*- coding: utf-8 -*-
"""Сервис уведомлений для car-tracker.

Функции:
- check_low_fuel() — проверка остатков в бочках и отправка уведомлений
- send_weekly_report() — еженедельный отчёт по расходам
- Запуск через APScheduler или вручную
"""

from datetime import date, timedelta
from app import create_app
from app.models import FuelBarrel, Expense, Vehicle, User
from app.config import Config
import asyncio
from telegram import Bot


async def send_telegram_message(chat_id: int, text: str):
    """Отправить сообщение в Telegram через Bot API."""
    if not Config.TELEGRAM_TOKEN:
        print("⚠️ TELEGRAM_TOKEN не задан, уведомление не отправлено")
        return
    bot = Bot(token=Config.TELEGRAM_TOKEN)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления: {e}")


def check_low_fuel():
    """Проверить остатки в бочках и уведомить админов, если ниже порога."""
    application = create_app()
    with application.app_context():
        low_barrels = FuelBarrel.query.filter(
            FuelBarrel.is_active == True,
            FuelBarrel.current_liters <= FuelBarrel.threshold_liters
        ).all()

        admins = User.query.filter_by(level=3, is_whitelisted=True).all()
        admin_ids = [a.tg_id for a in admins]

    if not low_barrels or not admin_ids:
        return

    for barrel in low_barrels:
        msg = (
            f"⚠️ Низкий уровень топлива!\n"
            f"Бочка: {barrel.name} ({barrel.fuel_type})\n"
            f"Остаток: {barrel.current_liters:,.0f} / {barrel.capacity_liters:,.0f} л "
            f"({barrel.remaining_pct}%)\n"
            f"Порог уведомления: {barrel.threshold_liters:,.0f} л\n"
            f"👉 Закажите поставку дизеля/бензина."
        )
        for admin_id in admin_ids:
            asyncio.run(send_telegram_message(admin_id, msg))


def send_weekly_report():
    """Сформировать и отправить еженедельный отчёт по расходам."""
    application = create_app()
    with application.app_context():
        today = date.today()
        week_ago = today - timedelta(days=7)

        # Итоговые затраты за неделю
        from sqlalchemy import func
        total = Expense.query.filter(Expense.date >= week_ago).with_entities(
            func.coalesce(func.sum(Expense.amount), 0)
        ).scalar()

        # Топ фур
        top_vehicles = Expense.query.join(Vehicle).filter(
            Expense.date >= week_ago
        ).with_entities(
            Vehicle.plate, Vehicle.brand, func.sum(Expense.amount).label("total")
        ).group_by(Vehicle.id).order_by(func.sum(Expense.amount).desc()).limit(5).all()

        # По категориям
        by_cat = Expense.query.filter(Expense.date >= week_ago).with_entities(
            Expense.category, func.sum(Expense.amount).label("total")
        ).group_by(Expense.category).all()

        # Бочки
        barrels = FuelBarrel.query.filter_by(is_active=True).all()

        admins = User.query.filter_by(level=3, is_whitelisted=True).all()
        admin_ids = [a.tg_id for a in admins]

    if not admin_ids:
        return

    lines = [
        f"📊 Еженедельный отчёт ({week_ago.strftime('%d.%m')}–{today.strftime('%d.%m')})",
        f"",
        f"💰 Итоговые затраты: ₴ {float(total):,.0f}",
        f"",
        f"🏆 Топ-5 фур по затратам:",
    ]
    for v in top_vehicles:
        lines.append(f"  • {v.brand} {v.plate}: ₴ {float(v.total):,.0f}")

    lines.append("")
    lines.append("📦 По категориям:")
    for c in by_cat:
        lines.append(f"  • {c[0]}: ₴ {float(c[1]):,.0f}")

    lines.append("")
    lines.append("⛽ Бочки:")
    for b in barrels:
        status = "🔴" if b.is_low else "🟢"
        lines.append(f"  {status} {b.name} ({b.fuel_type}): {b.current_liters:,.0f}/{b.capacity_liters:,.0f} л ({b.remaining_pct}%)")

    msg = "\n".join(lines)

    for admin_id in admin_ids:
        asyncio.run(send_telegram_message(admin_id, msg))


def notify_pending_expense(expense: Expense):
    """Уведомить всех уровней 3 о новом pending расходе от уровня 1."""
    application = create_app()
    with application.app_context():
        admins = User.query.filter_by(level=3, is_whitelisted=True).all()
        admin_ids = [a.tg_id for a in admins]
        vehicle = expense.vehicle

    if not admin_ids:
        return

    msg = (
        f"🔔 Новый расход на проверке!\n"
        f"Фура: {vehicle.brand} ({vehicle.plate})\n"
        f"Категория: {expense.category}\n"
        f"Сумма: ₴ {expense.amount:,.0f}\n"
        f"Комментарий: {expense.comment or '-'}\n"
        f"Отправитель: уровень 1\n"
        f"👉 Одобрите или отклоните в Mini App."
    )
    for admin_id in admin_ids:
        asyncio.run(send_telegram_message(admin_id, msg))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "weekly":
        send_weekly_report()
    else:
        check_low_fuel()