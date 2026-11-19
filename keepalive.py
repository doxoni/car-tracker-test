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

Пингуется сама страница Mini App (`/`) с браузерными заголовками, а не
`/api/health`: замечено, что Render free не будит контейнер по запросам
ботов (анти-абьюз), а реальный заход в Mini App - будит.

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

# Страница Mini App, а не /api/health (см. docstring).
PAGE_URL = "https://car-tracker-test.onrender.com/"

# Браузерные заголовки: с ними запрос проходит как заход настоящего
# пользователя, и Render будит контейнер.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
}

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


def _sleep(seconds: int) -> None:
    """Пауза между попытками."""
    import time

    time.sleep(seconds)


def ping(url: str = PAGE_URL, timeout: int = 90, attempts: int = 3) -> bool:
    """Проверить, что сервис отвечает.

    Первый запрос к спящему контейнеру обычно не доходит до приложения:
    Render показывает страницу "SERVICE WAKING UP" и отдаёт 503, пока
    контейнер поднимается (это занимает до минуты). Поэтому повторяем.
    """
    request = urllib.request.Request(url, headers=dict(BROWSER_HEADERS))
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if 200 <= response.status < 500:
                    return True
        except urllib.error.HTTPError as error:
            # 503 - контейнер ещё поднимается, попробуем ещё раз.
            if error.code < 500:
                return True
        except Exception:
            pass
        if attempt < attempts:
            _sleep(20)
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
