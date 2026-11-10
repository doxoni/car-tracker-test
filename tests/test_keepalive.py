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


def test_ping_retries_after_503(monkeypatch):
    """Спящий контейнер отдаёт 503 - пинг должен повториться."""
    import urllib.error

    calls = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(request, timeout=None):
        calls.append(1)
        if len(calls) < 2:
            raise urllib.error.HTTPError("url", 503, "sleeping", {}, None)
        return _Response()

    monkeypatch.setattr(keepalive.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(keepalive, "_sleep", lambda seconds: None)

    assert keepalive.ping(attempts=3) is True
    assert len(calls) == 2


def test_ping_gives_up_after_all_attempts(monkeypatch):
    """Если сервис так и не проснулся - пинг считаем неудачным."""
    import urllib.error

    calls = []

    def _fake_urlopen(request, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError("url", 503, "sleeping", {}, None)

    monkeypatch.setattr(keepalive.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(keepalive, "_sleep", lambda seconds: None)

    assert keepalive.ping(attempts=3) is False
    assert len(calls) == 3
