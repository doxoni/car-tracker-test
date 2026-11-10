# -*- coding: utf-8 -*-
"""Keepalive сервиса car-tracker-test: днём не даём контейнеру уснуть.

Зачем это нужно:
- на бесплатном тарифе Render контейнер засыпает после 15 минут
  простоя, и первый запрос после сна поднимает его заново (30-60 секунд);
- если сервис спит круглые сутки, Render намотает 750 инстанс-часов
  в месяц (31 день x 24 часа) и убьёт все бесплатные сервисы аккаунта
  в последний день месяца;
- ночью держать сервис включённым незачем: он всё равно должен спать.

Поэтому пинг идёт только в дневное окно (по умолчанию 07:00-23:00
по Europe/Kyiv). Ночью пинга нет - контейнер засыпает сам, часы не
тратятся, а утром его поднимет любое обращение (Mini App или сообщение
в боте).

Запуск (PowerShell, из папки проекта):
    python keepalive.py

Полезные переменные окружения:
    KEEPALIVE_START_HOUR - начало окна (по умолчанию 7)
    KEEPALIVE_END_HOUR   - конец окна (по умолчанию 23)
    KEEPALIVE_TZ         - часовой пояс (по умолчанию Europe/Kyiv)
    KEEPALIVE_URL        - адрес проверки (по умолчанию Render)
"""

import os
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HEALTH_URL = "https://car-tracker-test.onrender.com/api/health"
TZ_NAME = os.getenv("KEEPALIVE_TZ", "Europe/Kyiv")
START_HOUR = int(os.getenv("KEEPALIVE_START_HOUR", "7"))
END_HOUR = int(os.getenv("KEEPALIVE_END_HOUR", "23"))


def now_local() -> datetime:
    """Текущее время в нужном часовом поясе."""
    return datetime.now(ZoneInfo(TZ_NAME))


def in_window(moment: datetime) -> bool:
    """Входит ли момент в дневное окно.

    Окно может переходить через полночь (например, 22:00-06:00).
    """
    hour = moment.hour
    if START_HOUR == END_HOUR:
        return True
    if START_HOUR < END_HOUR:
        return START_HOUR <= hour < END_HOUR
    return hour >= START_HOUR or hour < END_HOUR


def ping(url: str = HEALTH_URL, timeout: int = 60) -> bool:
    """Проверить, что сервис отвечает."""
    request = urllib.request.Request(url, headers={"User-Agent": "car-tracker-keepalive"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 500
    except urllib.error.HTTPError as error:
        # Сервис отвечает, пусть и с ошибкой - значит он живой.
        return error.code < 500
    except Exception:
        return False


def main() -> None:
    """Пинговать сервис, если сейчас дневное окно."""
    moment = now_local()
    if not in_window(moment):
        print(
            f"🌙 Ночь ({moment.strftime('%H:%M')} по {TZ_NAME}) - пинг пропущен, "
            "сервис спит."
        )
        return
    ok = ping()
    state = "отвечает" if ok else "не отвечает"
    print(f"☀️ День ({moment.strftime('%H:%M')} по {TZ_NAME}) - сервис {state}.")


if __name__ == "__main__":
    main()
