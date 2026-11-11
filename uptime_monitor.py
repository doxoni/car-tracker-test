# -*- coding: utf-8 -*-
"""Управление мониторами UptimeRobot (пинг днём, пауза ночью).

Команды (PowerShell, из папки проекта):
    python uptime_monitor.py setup    # создать оба монитора, если их нет
    python uptime_monitor.py status   # показать состояние мониторов
    python uptime_monitor.py pause    # поставить основной монитор на паузу
    python uptime_monitor.py start    # снять основной монитор с паузы
    python uptime_monitor.py auto     # включить/выключить по киевскому времени

Ключ API берётся из переменной окружения UPTIME_API_KEY или из файла
uptime_key.txt (файл в .gitignore - в Git ключ не попадает).

Зачем два монитора:
    Бесплатный Render даёт 750 инстанс-часов в месяц, а монитор с
    включённым пингом держал бы контейнер awake круглые сутки (744 часа
    в 31-дневный месяц). С паузой ночью контейнер спит и часы не тратятся.
    Дежурный монитор (раз в час) будит контейнер ночью, а утром контейнер
    сам включает основной пинг - так сервис просыпается без участия
    GitHub Actions (его расписание на этом репозитории опаздывает на часы).
"""

import argparse
import os
import sys
from pathlib import Path

# Консоль Windows по умолчанию cp1251 - эмодзи в ней не печатаются.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ROOT = Path(__file__).resolve().parent

# Импортируем модуль из папки app как обычный файл: так скрипт работает
# без Flask и остальных зависимостей приложения (он запускается в
# GitHub Actions, где установлены только стандартные библиотеки).
sys.path.insert(0, str(ROOT / "app"))

from uptime import (  # noqa: E402 - путь добавили выше
    CHECK_INTERVAL,
    MONITOR_NAME,
    NIGHT_CHECK_INTERVAL,
    NIGHT_MONITOR_NAME,
    UptimeClient,
    UptimeError,
    desired_active,
    monitor_url,
    night_monitor_url,
    sync_all,
    sync_monitor,
)


def read_api_key() -> str:
    """Ключ UptimeRobot: переменная окружения, затем uptime_key.txt."""
    key = (os.getenv("UPTIME_API_KEY") or "").strip()
    if key:
        return key

    key_file = ROOT / "uptime_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8-sig").strip()

    env_file = ROOT / "render_env.txt"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("UPTIME_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def make_client() -> UptimeClient:
    """Клиент API. Если ключа нет - понятная ошибка и выход."""
    key = read_api_key()
    if not key:
        print("НЕТ КЛЮЧА UPTIMEROBOT")
        print("")
        print("Ключ лежит в аккаунте UptimeRobot: Integrations -> API -> Create API key.")
        print("Положи его в файл uptime_key.txt (одна строка) или в переменную")
        print("окружения UPTIME_API_KEY и запусти команду ещё раз.")
        raise SystemExit(1)
    return UptimeClient(key)


def show_monitor(monitor: dict) -> None:
    """Напечатать состояние монитора."""
    print(f"  имя:     {monitor.get('friendlyName')}")
    print(f"  адрес:   {monitor.get('url')}")
    print(f"  статус:  {monitor.get('status')}")
    print(f"  интервал:{monitor.get('interval')} с")
    print(f"  id:      {monitor.get('id')}")


def cmd_setup(client: UptimeClient, args) -> int:
    """Создать мониторы, если таких ещё нет."""
    url = args.url or monitor_url()

    day = client.ensure_monitor(MONITOR_NAME, url, CHECK_INTERVAL)
    if day:
        print("Основной монитор (5 минут, днём):")
        show_monitor(day)
    else:
        print("Основной монитор не удалось создать.")

    night = client.ensure_monitor(
        NIGHT_MONITOR_NAME, night_monitor_url(), NIGHT_CHECK_INTERVAL
    )

    if night:
        print("")
        print("Дежурный монитор (1 час, работает всегда):")
        show_monitor(night)
    else:
        print("")
        print("Дежурный монитор не удалось создать.")
    return 0


def cmd_status(client: UptimeClient, args) -> int:
    """Показать состояние мониторов."""
    day = client.find_by_name(MONITOR_NAME)
    if not day:
        print("Основной монитор не найден. Создай его: python uptime_monitor.py setup")
        return 1

    print("Основной монитор (5 минут, днём):")
    show_monitor(day)

    night = client.find_by_name(NIGHT_MONITOR_NAME)
    print("")
    if night:
        print("Дежурный монитор (1 час, работает всегда):")
        show_monitor(night)
    else:
        print("Дежурный монитор не найден. Создай его: python uptime_monitor.py setup")

    print("")
    print(f"  сейчас:  {'день - пинг нужен' if desired_active() else 'ночь - пинг не нужен'}")
    return 0


def cmd_pause(client: UptimeClient, args) -> int:
    """Поставить основной монитор на паузу."""
    action = sync_monitor(
        client, False, args.url or monitor_url(), name=MONITOR_NAME
    )
    print(f"Основной монитор: {action}")
    return 0


def cmd_start(client: UptimeClient, args) -> int:
    """Снять основной монитор с паузы."""
    action = sync_monitor(client, True, args.url or monitor_url(), name=MONITOR_NAME)
    print(f"Основной монитор: {action}")
    return 0


def cmd_auto(client: UptimeClient, args) -> int:
    """Включить или выключить мониторы по киевскому времени."""
    active = desired_active()
    actions = sync_all(client, active, args.url or monitor_url())
    print(f"{'день' if active else 'ночь'}:")
    print(f"  основной монитор: {actions.get('day')}")
    print(f"  дежурный монитор: {actions.get('night')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Управление мониторами UptimeRobot")
    parser.add_argument(
        "command",
        choices=["setup", "status", "pause", "start", "auto"],
        help="что сделать",
    )
    parser.add_argument("--url", default="", help="адрес монитора (по умолчанию - health)")
    args = parser.parse_args()

    client = make_client()
    handlers = {
        "setup": cmd_setup,
        "status": cmd_status,
        "pause": cmd_pause,
        "start": cmd_start,
        "auto": cmd_auto,
    }
    try:
        return handlers[args.command](client, args)
    except UptimeError as error:
        print(f"ОШИБКА UptimeRobot: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
