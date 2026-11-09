# -*- coding: utf-8 -*-
"""Ночная пауза сервиса: ночью бот не отвечает, днём работает.

Окно паузы задаётся по часовому поясу Europe/Kyiv (по умолчанию
с 02:00 до 05:00). Внутри окна:
- бот Telegram не стартует (app/bot_runner.py);
- /api/health показывает блок "night" (app/routes.py).

Запуск не требуется: модуль импортируется приложением.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Config

# ---------- Ночное окно ----------


def _tz() -> ZoneInfo:
    """Часовой пояс ночного окна."""
    return ZoneInfo(Config.NIGHT_TZ)


def is_night(now: datetime | None = None) -> bool:
    """Сейчас ночь (окно паузы) по времени Киева.

    Окно: [NIGHT_START_HOUR, NIGHT_END_HOUR) по местному времени,
    то есть в 05:00 пауза уже заканчивается.
    """
    if not Config.NIGHT_MODE_ENABLED:
        return False

    tz = _tz()
    if now is None:
        local_now = datetime.now(tz)
    else:
        # Наивное время считаем местным, aware - переводим в нужный пояс.
        if now.tzinfo is None:
            local_now = now.replace(tzinfo=tz)
        else:
            local_now = now.astimezone(tz)

    start = Config.NIGHT_START_HOUR
    end = Config.NIGHT_END_HOUR
    hour = local_now.hour
    if start <= end:
        return start <= hour < end
    # Окно переходит через полночь (например, 23:00 - 05:00).
    return hour >= start or hour < end


def _next_change(now: datetime) -> datetime:
    """Ближайший момент смены состояния (начало или конец окна)."""
    tz = _tz()
    local_now = now.astimezone(tz)
    start = Config.NIGHT_START_HOUR
    end = Config.NIGHT_END_HOUR

    candidates = []
    for base in (local_now, local_now + timedelta(days=1)):
        for hour in (start, end):
            moment = base.replace(hour=hour, minute=0, second=0, microsecond=0)
            if moment > local_now:
                candidates.append(moment)

    return min(candidates) if candidates else local_now


def night_info(now: datetime | None = None) -> dict:
    """Сводка о ночном режиме - попадает в /api/health."""
    tz = _tz()
    if now is None:
        local_now = datetime.now(tz)
    elif now.tzinfo is None:
        local_now = now.replace(tzinfo=tz)
    else:
        local_now = now.astimezone(tz)

    active = is_night(local_now)
    return {
        "active": active,
        "enabled": bool(Config.NIGHT_MODE_ENABLED),
        "tz": Config.NIGHT_TZ,
        "start_hour": Config.NIGHT_START_HOUR,
        "end_hour": Config.NIGHT_END_HOUR,
        "local_time": local_now.strftime("%Y-%m-%d %H:%M:%S"),
        "next_change": _next_change(local_now).strftime("%Y-%m-%d %H:%M:%S"),
    }
