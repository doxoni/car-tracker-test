# -*- coding: utf-8 -*-
"""Сервис уведомлений для car-tracker.

Функции:
- check_low_fuel() — проверка остатков в бочках и отправка уведомлений
- send_weekly_report() — еженедельный отчёт по расходам
- Запуск через APScheduler или вручную
"""

from datetime import date, timedelta
from app import create_app, db
from app.i18n import normalize_lang, t
from app.models import FuelBarrel, Expense, Vehicle, User
from app.config import Config
import asyncio
from concurrent.futures import ThreadPoolExecutor
from telegram import Bot

# Названия видов топлива по-русски: в уведомлениях показываем словами.
FUEL_TYPE_NAME = {"diesel": "Дизель", "petrol": "Бензин"}


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


def send_message(chat_id: int, text: str) -> None:
    """Отправить сообщение из любого места кода.

    Из бота мы вызываем это внутри работающего event loop, где
    asyncio.run() запрещён - поэтому в таком случае отправка идёт
    в отдельном потоке со своим event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(send_telegram_message(chat_id, text))
        return

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, send_telegram_message(chat_id, text)).result()


def check_low_fuel():
    """Проверить остатки в бочках и уведомить админов, если ниже порога."""
    application = create_app()
    with application.app_context():
        low_barrels = FuelBarrel.query.filter(
            FuelBarrel.is_active == True,
            FuelBarrel.current_liters <= FuelBarrel.threshold_liters
        ).all()

        admins = User.query.filter_by(level=3, is_whitelisted=True).all()

    if not low_barrels or not admins:
        return

    for barrel in low_barrels:
        for admin in admins:
            lang = normalize_lang(admin.lang)
            fuel_name = t(FUEL_TYPE_NAME.get(barrel.fuel_type, barrel.fuel_type), lang)
            msg = (
                f"⚠️ {t('Низкий уровень топлива!', lang)}\n"
                f"{t('Бочка:', lang)} {barrel.name} ({fuel_name})\n"
                f"{t('Остаток:', lang)} {barrel.current_liters:,.0f} / "
                f"{barrel.capacity_liters:,.0f} л ({barrel.remaining_pct}%)\n"
                f"{t('Порог уведомления:', lang)} {barrel.threshold_liters:,.0f} л\n"
                f"👉 {t('Закажите поставку дизеля/бензина.', lang)}"
            )
            send_message(admin.tg_id, msg)


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

    if not admins:
        return

    for admin in admins:
        lang = normalize_lang(admin.lang)
        lines = [
            f"📊 {t('Еженедельный отчёт', lang)} "
            f"({week_ago.strftime('%d.%m')}–{today.strftime('%d.%m')})",
            f"",
            f"💰 {t('Итоговые затраты:', lang)} ₴ {float(total):,.0f}",
            f"",
            f"🏆 {t('Топ-5 фур по затратам:', lang)}",
        ]
        for v in top_vehicles:
            lines.append(f"  • {v.brand} {v.plate}: ₴ {float(v.total):,.0f}")

        lines.append("")
        lines.append(f"📦 {t('По категориям:', lang)}")
        for c in by_cat:
            lines.append(f"  • {c[0]}: ₴ {float(c[1]):,.0f}")

        lines.append("")
        lines.append(f"⛽ {t('Бочки:', lang)}")
        for b in barrels:
            status = "🔴" if b.is_low else "🟢"
            fuel_name = t(FUEL_TYPE_NAME.get(b.fuel_type, b.fuel_type), lang)
            lines.append(
                f"  {status} {b.name} ({fuel_name}): {b.current_liters:,.0f}/"
                f"{b.capacity_liters:,.0f} л ({b.remaining_pct}%)"
            )

        msg = "\n".join(lines)
        send_message(admin.tg_id, msg)


def notify_pending_expense(expense: Expense):
    """Уведомить всех уровней 3 о новом pending расходе от уровня 1."""
    application = create_app()
    with application.app_context():
        admins = User.query.filter_by(level=3, is_whitelisted=True).all()
        vehicle = expense.vehicle

    if not admins:
        return

    for admin in admins:
        lang = normalize_lang(admin.lang)
        msg = (
            f"🔔 {t('Новый расход на проверке!', lang)}\n"
            f"{t('Фура:', lang)} {vehicle.brand} ({vehicle.plate})\n"
            f"{t('Категория:', lang)} {expense.category}\n"
            f"{t('Сумма:', lang)} ₴ {expense.amount:,.0f}\n"
            f"{t('Комментарий:', lang)} {expense.comment or '-'}\n"
            f"{t('Отправитель: уровень 1', lang)}\n"
            f"👉 {t('Одобрите или отклоните в Mini App.', lang)}"
        )
        send_message(admin.tg_id, msg)


def _submitter_name(user) -> str:
    """Как показать отправителя записи."""
    if user is None:
        return "-"
    if user.username:
        return f"@{user.username}"
    return f"tg_id {user.tg_id}"


def notify_pending_entry(kind: str, entry) -> None:
    """Уведомить уровни 3 о новой заправке на проверке.

    kind - "fuel". Для обслуживания уведомление не присылается:
    записи обслуживания проверяются по команде /cheak без сообщений.
    """
    if kind != "fuel":
        return

    application = create_app()
    with application.app_context():
        admins = User.query.filter_by(level=3, is_whitelisted=True).all()
        vehicle = db.session.get(Vehicle, entry.vehicle_id)
        submitter = (
            db.session.get(User, entry.submitted_by) if entry.submitted_by else None
        )
        brand = vehicle.brand if vehicle else ""
        plate = vehicle.plate if vehicle else ""
        amount = float(entry.amount or 0)
        liters = float(getattr(entry, "liters", 0) or 0)
        who = _submitter_name(submitter)

    if not admins:
        return

    for admin in admins:
        lang = normalize_lang(admin.lang)
        lines = [
            f"🔔 {t('Новая заправка на проверке!', lang)}",
            f"{t('Фура:', lang)} {brand} ({plate})",
            f"{t('Литры:', lang)} {liters:,.1f}",
            f"{t('Сумма:', lang)} ₴ {amount:,.0f}",
        ]
        lines.append(f"{t('Отправитель:', lang)} {who}")
        lines.append(f"👉 {t('Проверьте по команде /cheak', lang)}")
        send_message(admin.tg_id, "\n".join(lines))


def notify_review_result(kind: str, entry, approved: bool) -> None:
    """Сообщить отправителю, приняли его запись или отклонили."""
    application = create_app()
    with application.app_context():
        submitter = (
            db.session.get(User, entry.submitted_by) if entry.submitted_by else None
        )
        vehicle = db.session.get(Vehicle, entry.vehicle_id)
        brand = vehicle.brand if vehicle else ""
        plate = vehicle.plate if vehicle else ""
        amount = float(entry.amount or 0)

    if submitter is None:
        return

    lang = normalize_lang(submitter.lang)
    if kind == "fuel":
        title = (
            t("✅ Ваша заправка принята", lang)
            if approved
            else t("❌ Ваша заправка отклонена", lang)
        )
    else:
        title = (
            t("✅ Ваше обслуживание принято", lang)
            if approved
            else t("❌ Ваше обслуживание отклонено", lang)
        )
    msg = (
        f"{title}\n"
        f"{t('Фура:', lang)} {brand} ({plate})\n"
        f"{t('Сумма:', lang)} ₴ {amount:,.0f}"
    )
    send_message(submitter.tg_id, msg)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "weekly":
        send_weekly_report()
    else:
        check_low_fuel()