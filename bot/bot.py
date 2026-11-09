# -*- coding: utf-8 -*-
"""Telegram-бот для car-tracker.

Команды:
  /start — открыть Mini App (кнопка)
  /language — выбрать язык интерфейса (русский или украинский)
  /barrels — показать остатки топлива в бочках
  /today — расходы за сегодня

Выдача уровней доступа (названия команд нестандартные - это и есть защита,
кто не знает команду, тот и не выдаст себе права):
  /yuser_1 — выдать себе 1 уровень (водитель)
  /admunus2 — выдать себе 2 уровень (оператор)
  /fraeadmin3 — выдать себе 3 уровень (суперадмин)
  /admin 1|2|3 add <user_id> — выдать уровень другому человеку
  /admin 1|2|3 del <user_id> — снять уровень (вернуть 1)
  /admin list — список пользователей и их уровней

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
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app import create_app, db
from app.config import Config
from app.db_retry import run_with_retry
from app.i18n import DEFAULT_LANG, LANG_NAMES, normalize_lang, t
from app.models import User, Vehicle, Expense, FuelBarrel

load_dotenv()

APP_URL = os.getenv("APP_URL", "https://localhost:5000")
TELEGRAM_TOKEN = Config.TELEGRAM_TOKEN

# Названия уровней для сообщений бота.
LEVEL_NAMES = {1: "водитель", 2: "оператор", 3: "суперадмин"}

# Названия видов топлива по-русски: в сообщениях показываем словами.
FUEL_TYPE_NAME = {"diesel": "Дизель", "petrol": "Бензин"}


def miniapp_url(lang: str | None = None) -> str:
    """Ссылка на Mini App.

    APP_URL на Render приходит как имя хоста (например car-tracker-test.onrender.com),
    поэтому приводим его к полному URL с адресом страницы /app.
    Если язык пользователя выбран, передаём его в адресе - Mini App сразу
    откроется на нужном языке.
    """
    url = APP_URL.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    url = url.rstrip("/")
    if not url.endswith("/app"):
        url = f"{url}/app"
    if lang in ("ru", "uk"):
        url = f"{url}?lang={lang}"
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
    lang = _user_lang(update.effective_user.id)
    current = normalize_lang(lang)
    keyboard = [
        [
            InlineKeyboardButton(
                t("🚗 Открыть учёт фур", current),
                web_app={"url": miniapp_url(lang)},
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    lines = [
        "Добро пожаловать в Car Tracker!",
        "",
        "📊 Учёт расходов фур",
        "⛽ Контроль бочек дизеля/бензина",
        "📈 Дашборд и графики",
        "",
        "Нажмите кнопку ниже, чтобы открыть Mini App:",
        "",
        "🌐 Смена языка — команда /language",
    ]
    text = "\n".join(t(line, current) for line in lines)
    await update.message.reply_text(text, reply_markup=reply_markup)


async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /language — выбор языка: русский или украинский."""
    current = normalize_lang(_user_lang(update.effective_user.id))
    keyboard = [
        [
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton("🇺🇦 Українська", callback_data="lang:uk"),
        ]
    ]
    await update.message.reply_text(
        t("Выберите язык:", current),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопки выбора языка: сохраняем выбор в базе."""
    query = update.callback_query
    await query.answer()
    data = str(query.data or "")
    if not data.startswith("lang:"):
        return
    lang = data.split(":", 1)[1]
    if lang not in ("ru", "uk"):
        return
    _save_lang(query.from_user.id, lang)
    await query.edit_message_text(t("Язык сохранён.", lang))


async def barrels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /barrels — остатки в бочках."""
    current = normalize_lang(_user_lang(update.effective_user.id))
    application = app_context()
    with application.app_context():
        barrels = run_with_retry(
            lambda: FuelBarrel.query.filter_by(is_active=True).all()
        )

    if not barrels:
        await update.message.reply_text(t("Бочки не настроены.", current))
        return

    lines = [t("⛽ Остаток топлива в бочках:", current)]
    for b in barrels:
        emoji = "🔴" if b.is_low else ("🟢" if b.remaining_pct > 50 else "🟡")
        fuel_name = t(FUEL_TYPE_NAME.get(b.fuel_type, b.fuel_type), current)
        lines.append(
            f"{emoji} {b.name} ({fuel_name}): "
            f"{b.current_liters:,.0f} / {b.capacity_liters:,.0f} л "
            f"({b.remaining_pct}%)"
        )

    await update.message.reply_text("\n".join(lines))


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /today — расходы за сегодня."""
    current = normalize_lang(_user_lang(update.effective_user.id))
    application = app_context()
    with application.app_context():
        today = datetime.utcnow().date()
        expenses = run_with_retry(
            lambda: Expense.query.filter(Expense.date == today)
            .order_by(Expense.date.desc())
            .all()
        )

    if not expenses:
        await update.message.reply_text(t("Сегодня расходов нет.", current))
        return

    lines = [t("💸 Расходы за сегодня:", current)]
    total = 0.0
    for e in expenses:
        total += e.amount
        lines.append(f"  • {e.category}: {e.amount:,.0f} ₴")

    lines.append(f"\n{t('Итого: ', current)}{total:,.0f} ₴")
    await update.message.reply_text("\n".join(lines))


# ---------- Уровни доступа ----------

def _user_lang(tg_id: int) -> str | None:
    """Язык пользователя из БД (None - язык ещё не выбран)."""
    if not tg_id:
        return None
    application = app_context()
    with application.app_context():
        user = run_with_retry(lambda: User.query.filter_by(tg_id=tg_id).first())
        if user is None:
            return None
        return user.lang


def _save_lang(tg_id: int, lang: str) -> None:
    """Запомнить язык пользователя в базе."""
    application = app_context()
    with application.app_context():
        user = run_with_retry(lambda: User.query.filter_by(tg_id=tg_id).first())
        if user is None:
            user = User(tg_id=tg_id, level=1, is_whitelisted=True)
            db.session.add(user)
        user.lang = lang
        db.session.commit()


def _level_name(level: int, lang: str = DEFAULT_LANG) -> str:
    """Название уровня доступа на нужном языке."""
    return t(LEVEL_NAMES.get(level, "уровень " + str(level)), lang)


def _user_level(tg_id: int) -> int:
    """Уровень пользователя в БД (0 - человека нет)."""
    if not tg_id:
        return 0
    application = app_context()
    with application.app_context():
        user = run_with_retry(lambda: User.query.filter_by(tg_id=tg_id).first())
        return user.level if user else 0


def _is_owner(tg_id: int) -> bool:
    """Владелец бота - он указан в ADMIN_TELEGRAM_ID."""
    return bool(tg_id and Config.ADMIN_TELEGRAM_ID and tg_id == Config.ADMIN_TELEGRAM_ID)


def _set_level(user_id: int, level: int) -> str:
    """Поставить пользователю уровень. Возвращает, что произошло."""
    application = app_context()
    with application.app_context():
        user = run_with_retry(lambda: User.query.filter_by(tg_id=user_id).first())
        if user is None:
            user = User(tg_id=user_id, level=level, is_whitelisted=True)
            db.session.add(user)
            action = "Создан"
        else:
            old_level = user.level
            user.level = level
            user.is_whitelisted = True
            action = "Обновлён" if old_level != level else "Оставлен без изменений"
        db.session.commit()
    return action


def _target_user_id(update: Update, args) -> int | None:
    """Telegram ID, которому выдаём уровень.

    Берём из аргумента команды. Если аргумента нет - из сообщения,
    на которое пользователь ответил.
    """
    if args:
        try:
            return int(args[0])
        except (TypeError, ValueError):
            return None
    return _reply_user_id(update)


def _reply_user_id(update: Update) -> int | None:
    """Telegram ID автора сообщения, на которое пользователь ответил."""
    message = update.message
    if message and message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


def _parse_admin_args(args) -> tuple[str, int | None, int | None]:
    """Разобрать аргументы /admin: действие, уровень, Telegram ID.

    Понимает формы:
        /admin list
        /admin 2 add 123456789
        /admin 2 del 123456789
        /admin add 123456789 2
    """
    action = "add"
    level = None
    user_id = None
    for arg in args or []:
        low = str(arg).strip().lower()
        if low in ("add", "выдать", "+"):
            action = "add"
        elif low in ("del", "delete", "remove", "снять", "-"):
            action = "del"
        elif low == "list":
            action = "list"
        elif low in ("1", "2", "3"):
            level = int(low)
        else:
            try:
                user_id = int(arg)
            except (TypeError, ValueError):
                continue
    return action, level, user_id


async def _issue_level(update: Update, context: ContextTypes.DEFAULT_TYPE, level: int):
    """Выдать уровень отправителю команды (/yuser_1, /admin2, /admin3).

    Telegram ID вводить не нужно: бот берёт ID автора сообщения сам.
    Названия команд нестандартные - это и есть защита: кто не знает
    команду, тот и не выдаст себе права.
    """
    tg_id = update.effective_user.id
    action = _set_level(tg_id, level)
    lang = normalize_lang(_user_lang(tg_id))
    await update.message.reply_text(
        t(
            "✅ {action}: вам выдан {level} уровень ({name}).",
            lang,
            action=t(action, lang),
            level=level,
            name=_level_name(level, lang),
        )
        + "\n"
        + t("Откройте приложение - новые права заработают сразу.", lang)
    )


async def yuser1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /yuser_1 — выдать себе 1 уровень (водитель)."""
    await _issue_level(update, context, 1)


async def admin2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin2 — выдать себе 2 уровень (оператор)."""
    await _issue_level(update, context, 2)


async def admin3_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin3 — выдать себе 3 уровень (суперадмин)."""
    await _issue_level(update, context, 3)


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin — выдать уровень конкретному человеку.

    Формы:
        /admin 1|2|3 add <telegram_id> — выдать уровень
        /admin 1|2|3 del <telegram_id> — снять уровень (вернуть 1)
        /admin list — список пользователей и их уровней
    """
    if _user_level(update.effective_user.id) < 3 and not _is_owner(update.effective_user.id):
        lang = normalize_lang(_user_lang(update.effective_user.id))
        await update.message.reply_text(
            t(
                "⛔ Команда доступна только с 3 уровнем. Наберите /fraeadmin3 - и она откроется.",
                lang,
            )
        )
        return

    lang = normalize_lang(_user_lang(update.effective_user.id))
    action, level, user_id = _parse_admin_args(context.args)

    if action == "list":
        application = app_context()
        with application.app_context():
            users = run_with_retry(
                lambda: User.query.order_by(User.tg_id).all()
            )
        if not users:
            await update.message.reply_text(t("Пользователей пока нет.", lang))
            return
        lines = [t("👥 Пользователи и уровни:", lang)]
        for u in users:
            name = u.username or t("без имени", lang)
            lines.append(
                f"• {u.tg_id} — {name} — "
                f"{u.level} ({_level_name(u.level, lang)})"
            )
        await update.message.reply_text("\n".join(lines))
        return

    if level is None:
        lines = [
            t("Укажи уровень (1, 2 или 3) и действие, например:", lang),
            t("/admin 2 add 123456789 — выдать 2 уровень", lang),
            t("/admin 2 del 123456789 — снять уровень", lang),
            t("/admin list — список пользователей", lang),
        ]
        await update.message.reply_text("\n".join(lines))
        return

    if user_id is None:
        target = _target_user_id(update, context.args)
    else:
        target = user_id

    if target is None:
        lines = [
            t("Укажи Telegram ID, например:", lang),
            "/admin 2 add 123456789",
            t("Можно ответить на сообщение человека - тогда ID возьмётся сам.", lang),
        ]
        await update.message.reply_text("\n".join(lines))
        return

    if action == "del":
        # Снимаем особые права: остаётся обычный водитель (1 уровень).
        level = 1

    action_text = _set_level(target, level)
    await update.message.reply_text(
        t(
            "✅ {action}: пользователю {target} выдан {level} уровень ({name}).",
            lang,
            action=t(action_text, lang),
            target=target,
            level=level,
            name=_level_name(level, lang),
        )
    )


def _as_coroutine(callback):
    """Обернуть обычную функцию в корутину.

    python-telegram-bot ждёт из post_init/post_stop именно корутину:
    если вернуть обычный результат, он падает с ошибкой
    "An asyncio.Future, a coroutine or an awaitable is required".
    """
    import asyncio
    import inspect

    if callback is None:
        return None

    async def _wrapper(application):
        result = callback(application)
        if inspect.isawaitable(result):
            await result

    return _wrapper


def build_app(on_ready=None, on_stop=None):
    """Создаёт Telegram-приложение (Application).

    on_ready - вызывается, когда бот подключился к Telegram (getMe прошёл);
    on_stop  - вызывается, когда опрос остановлен.
    Оба нужны, чтобы /api/health показывал реальное состояние бота.
    Колбэки могут быть как обычными функциями, так и корутинами.
    """
    builder = ApplicationBuilder().token(TELEGRAM_TOKEN)
    ready = _as_coroutine(on_ready)
    stop = _as_coroutine(on_stop)
    if ready is not None:
        builder = builder.post_init(ready)
    if stop is not None:
        builder = builder.post_stop(stop)
    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("language", language_cmd))
    application.add_handler(CallbackQueryHandler(language_callback, pattern=r"^lang:"))
    application.add_handler(CommandHandler("barrels", barrels_cmd))
    application.add_handler(CommandHandler("today", today_cmd))
    application.add_handler(CommandHandler("yuser_1", yuser1_cmd))
    application.add_handler(CommandHandler("admunus2", admin2_cmd))
    application.add_handler(CommandHandler("fraeadmin3", admin3_cmd))
    application.add_handler(CommandHandler("admin", admin_cmd))
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