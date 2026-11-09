# -*- coding: utf-8 -*-
"""Тесты ночной паузы сервиса: команда auto и решение по киевскому времени.

Проверяем, что:
- ночью сервис усыпляется;
- днём усыпленный сервис разбужается;
- в любое время суток состояние сервиса приводится к правильному.

Запуск:
    python -m pytest tests/test_night_sleep.py -q
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import night_sleep  # noqa: E402
import pytest  # noqa: E402

KEY = "тестовый-ключ"


class FakeRender:
    """Подмена Render API: запоминает вызовы и отдаёт заданное состояние."""

    def __init__(self, suspended: bool = False) -> None:
        self.suspended = suspended
        self.calls: list[tuple[str, str]] = []

    def api(self, method: str, path: str, key: str, payload=None):
        self.calls.append((method, path))
        if path.endswith("/suspend"):
            self.suspended = True
            return 202, {}
        if path.endswith("/resume"):
            self.suspended = False
            return 202, {}
        if path.startswith("/services/") and "deploys" not in path:
            return 200, {"suspended": "suspended" if self.suspended else "not_suspended"}
        return 200, {}

    def service_state(self, key: str) -> dict:
        return self.api("GET", f"/services/{night_sleep.SERVICE_ID}", key)[1]

    def last_deploy(self, key: str) -> dict:
        return {
            "status": "live",
            "commit": {"id": night_sleep.github_head_commit()},
        }


@pytest.fixture
def fake(monkeypatch):
    """Подменяем API Render и время: время задаётся в каждом тесте."""
    render = FakeRender()
    monkeypatch.setattr(night_sleep, "api", render.api)
    monkeypatch.setattr(night_sleep, "service_state", render.service_state)
    monkeypatch.setattr(night_sleep, "last_deploy", render.last_deploy)
    monkeypatch.setattr(night_sleep, "github_head_commit", lambda: "abc123")

    # Проверка живости сервиса идёт по сети - в тестах отвечаем сразу.
    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(night_sleep.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    return render


def _set_time(monkeypatch, moment: datetime) -> None:
    """Задаём "текущее" киевское время."""
    monkeypatch.setattr(night_sleep, "local_now", lambda: moment)


def test_is_night_window(monkeypatch) -> None:
    """Ночное окно - с 02:00 до 05:00 по Киеву."""
    tz = night_sleep.TZ
    assert night_sleep.is_night(datetime(2026, 1, 15, 1, 59, tzinfo=tz)) is False
    assert night_sleep.is_night(datetime(2026, 1, 15, 2, 0, tzinfo=tz)) is True
    assert night_sleep.is_night(datetime(2026, 1, 15, 4, 59, tzinfo=tz)) is True
    assert night_sleep.is_night(datetime(2026, 1, 15, 5, 0, tzinfo=tz)) is False


def test_auto_suspends_at_night(fake, monkeypatch) -> None:
    """Ночью сервис усыпляется."""
    tz = night_sleep.TZ
    _set_time(monkeypatch, datetime(2026, 1, 15, 2, 30, tzinfo=tz))
    monkeypatch.setattr(night_sleep, "cmd_wait_until_morning", lambda key: 0)

    result = night_sleep.cmd_auto(KEY)

    assert result == 0
    assert fake.suspended is True
    assert ("POST", f"/services/{night_sleep.SERVICE_ID}/suspend") in fake.calls


def test_auto_resumes_in_the_morning(fake, monkeypatch) -> None:
    """Днём усыпленный сервис разбужается."""
    tz = night_sleep.TZ
    fake.suspended = True
    _set_time(monkeypatch, datetime(2026, 1, 15, 6, 0, tzinfo=tz))

    result = night_sleep.cmd_auto(KEY)

    assert result == 0
    assert fake.suspended is False
    assert ("POST", f"/services/{night_sleep.SERVICE_ID}/resume") in fake.calls


def test_auto_keeps_awake_service_awake(fake, monkeypatch) -> None:
    """Днём работающий сервис не трогаем."""
    tz = night_sleep.TZ
    _set_time(monkeypatch, datetime(2026, 1, 15, 12, 0, tzinfo=tz))

    result = night_sleep.cmd_auto(KEY)

    assert result == 0
    assert fake.suspended is False
    # Усыплять и разбужать нельзя - только чтение состояния.
    assert not [call for call in fake.calls if call[0] == "POST"]


def test_auto_at_night_waits_for_morning(fake, monkeypatch) -> None:
    """Ночью после усыпления ждём утра, чтобы разбудить сервис."""
    tz = night_sleep.TZ
    _set_time(monkeypatch, datetime(2026, 1, 15, 2, 30, tzinfo=tz))
    waited = {"value": False}

    def fake_wait(key: str) -> int:
        waited["value"] = True
        return 0

    monkeypatch.setattr(night_sleep, "cmd_wait_until_morning", fake_wait)

    night_sleep.cmd_auto(KEY)

    assert waited["value"] is True


if __name__ == "__main__":
    sys.exit(0)
