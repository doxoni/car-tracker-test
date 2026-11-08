# -*- coding: utf-8 -*-
"""Telegram-бот для car-tracker.

Команды:
  /start — открыть Mini App (кнопка)
  /barrels — показать остатки топлива в бочках
  /today — расходы за сегодня

Уведомления:
  - бот уведомляет, когда остаток в бочке падает ниже порога
  - еженедельный отчёт по расходам

Запуск: `python bot/bot.py`  (long polling)
"""

import asyncio
import sys

# Python 3.14+ совместимость: Windows требует явной политики event loop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app import create_app
from app.config import Config
from app.db_retry import run_with_retry
from app.models import User, Vehicle, Expense, FuelBarrel

load_dotenv()

APP_URL = os.getenv("APP_URL", "https://localhost:5000")
TELEGRAM_TOKEN = Config.TELEGRAM_TOKEN


def miniapp_url() -> str:
    """Ссылка на Mini App.

    APP_URL на Render приходит как имя хоста (например car-tracker-test.onrender.com),
    поэтому приводим его к полному URL с адресом страницы /app.
    """
    url = APP_URL.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    url = url.rstrip("/")
    if not url.endswith("/app"):
        url = f"{url}/app"
    return url


_app = None


def app_context():
    """Flask-приложение для доступа к БД из бота.

    Создаётся один раз и переиспользуется: каждый create_app() поднимает
    свой пул соединений, а у облачной БД лимит на соединения ограничен.
    """
    global _app
    if _app is None:
        _app = create_app()
    return _app


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — приветствие и кнопка Mini App."""
    keyboard = [
        [InlineKeyboardButton("🚗 Открыть учёт фур", web_app={"url": miniapp_url()})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать в Car Tracker!\n\n"
        "📊 Учёт расходов фур\n"
        "⛽ Контроль бочек дизеля/бензина\n"
        "📈 Дашборд и графики\n\n"
        "Нажмите кнопку ниже, чтобы открыть Mini App:",
        reply_markup=reply_markup,
    )


async def barrels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /barrels — остатки в бочках."""
    application = app_context()
    with application.app_context():
        barrels = run_with_retry(
            lambda: FuelBarrel.query.filter_by(is_active=True).all()
        )

    if not barrels:
        await update.message.reply_text("Бочки не настроены.")
        return

    lines = ["⛽ Остаток топлива в бочках:\n"]
    for b in barrels:
        emoji = "🔴" if b.is_low else ("🟢" if b.remaining_pct > 50 else "🟡")
        lines.append(
            f"{emoji} {b.name} ({b.fuel_type}): "
            f"{b.current_liters:,.0f} / {b.capacity_liters:,.0f} л "
            f"({b.remaining_pct}%)"
        )

    await update.message.reply_text("\n".join(lines))


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /today — расходы за сегодня."""
    application = app_context()
    with application.app_context():
        today = datetime.utcnow().date()
        expenses = run_with_retry(
            lambda: Expense.query.filter(Expense.date == today)
            .order_by(Expense.date.desc())
            .all()
        )

    if not expenses:
        await update.message.reply_text("Сегодня расходов нет.")
        return

    lines = ["💸 Расходы за сегодня:\n"]
    total = 0.0
    for e in expenses:
        total += e.amount
        lines.append(f"  • {e.category}: {e.amount:,.0f} ₴")

    lines.append(f"\nИтого: {total:,.0f} ₴")
    await update.message.reply_text("\n".join(lines))


def build_app(on_ready=None, on_stop=None):
    """Создаёт Telegram-приложение (Application).

    on_ready - вызывается, когда бот подключился к Telegram (getMe прошёл);
    on_stop  - вызывается, когда опрос остановлен.
    Оба нужны, чтобы /api/health показывал реальное состояние бота.
    """
    builder = ApplicationBuilder().token(TELEGRAM_TOKEN)
    if on_ready is not None:
        builder = builder.post_init(on_ready)
    if on_stop is not None:
        builder = builder.post_stop(on_stop)
    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("barrels", barrels_cmd))
    application.add_handler(CommandHandler("today", today_cmd))
    return application


def main():
    """Запуск бота в режиме long polling."""
    application = build_app()
    print("🤖 Бот запущен (long polling)...")
    # Python 3.14+: гарантируем наличие event loop в текущем потоке
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    application.run_polling()


if __name__ == "__main__":
    main()