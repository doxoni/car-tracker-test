# -*- coding: utf-8 -*-
"""Проверка окна keepalive: днём пингуем, ночью - нет.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_keepalive.py -q
"""

from datetime import datetime

import keepalive
from zoneinfo import ZoneInfo


def _moment(hour: int) -> datetime:
    """Момент времени в киевском поясе."""
    return datetime(2026, 11, 10, hour, 0, tzinfo=ZoneInfo("Europe/Kyiv"))


def test_daytime_hours_are_inside_window():
    """Днём пинг идёт."""
    assert keepalive.in_window(_moment(7))
    assert keepalive.in_window(_moment(12))
    assert keepalive.in_window(_moment(22))


def test_night_hours_are_outside_window():
    """Ночью пинга нет - сервис спит."""
    assert not keepalive.in_window(_moment(2))
    assert not keepalive.in_window(_moment(4))
    assert not keepalive.in_window(_moment(23))
    assert not keepalive.in_window(_moment(6))


def test_window_edges():
    """На границах окна: начало включительно, конец исключительно."""
    assert keepalive.in_window(_moment(7))
    assert not keepalive.in_window(_moment(23))
