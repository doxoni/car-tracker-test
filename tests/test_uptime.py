# -*- coding: utf-8 -*-
"""Проверка интеграции с UptimeRobot: окно дня/ночи и работа с монитором.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_uptime.py -q
"""

import json
from datetime import datetime

import pytest
from zoneinfo import ZoneInfo

from app import uptime
from app.uptime import UptimeClient, UptimeError

KYIV = ZoneInfo("Europe/Kyiv")


def _moment(hour: int) -> datetime:
    """Момент времени в киевском поясе."""
    return datetime(2026, 11, 10, hour, 0, tzinfo=KYIV)


class _Response:
    """Заглушка ответа urllib."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def read(self):
        if isinstance(self._payload, (dict, list)):
            return json.dumps(self._payload).encode("utf-8")
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_urlopen(monkeypatch, handler):
    """Подменить urlopen на функцию-обработчик (request, timeout)."""
    calls = []

    def _fake_urlopen(request, timeout=None):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(uptime.urllib.request, "urlopen", _fake_urlopen)
    return calls


# ---------- Окно дня и ночи ----------


def test_daytime_is_active():
    """Днём монитор должен работать."""
    assert uptime.desired_active(_moment(7)) is True
    assert uptime.desired_active(_moment(12)) is True
    assert uptime.desired_active(_moment(22)) is True


def test_nighttime_is_inactive():
    """Ночью монитор должен стоять на паузе."""
    assert uptime.desired_active(_moment(2)) is False
    assert uptime.desired_active(_moment(6)) is False
    assert uptime.desired_active(_moment(23)) is False


def test_window_edges():
    """На границах окна: начало включительно, конец исключительно."""
    assert uptime.desired_active(_moment(7)) is True
    assert uptime.desired_active(_moment(23)) is False


# ---------- Клиент API ----------


def test_client_sends_bearer_token(monkeypatch):
    """Ключ уходит в заголовке Authorization."""
    calls = _patch_urlopen(monkeypatch, lambda request: _Response({"data": []}))

    UptimeClient("secret-key").list_monitors()

    assert len(calls) == 1
    assert calls[0].get_header("Authorization") == "Bearer secret-key"


def test_list_monitors_reads_data(monkeypatch):
    """Список мониторов приходит в поле data."""
    payload = {"data": [{"id": 1, "url": "https://example.com", "status": "PAUSED"}]}
    _patch_urlopen(monkeypatch, lambda request: _Response(payload))

    monitors = UptimeClient("key").list_monitors()

    assert len(monitors) == 1
    assert monitors[0]["id"] == 1


def test_list_monitors_asks_for_50(monkeypatch):
    """Больше 50 мониторов API не отдаёт - с limit=200 список пустой."""
    calls = _patch_urlopen(monkeypatch, lambda request: _Response({"data": []}))

    UptimeClient("key").list_monitors()

    assert "limit=50" in calls[0].full_url


def test_client_repeats_after_rate_limit(monkeypatch):
    """Ответ "слишком много запросов" - ждём и повторяем."""
    import urllib.error

    attempts = []

    def _handler(request):
        attempts.append(1)
        if len(attempts) < 2:
            raise urllib.error.HTTPError("url", 429, "too many requests", {}, None)
        return _Response({"data": []})

    _patch_urlopen(monkeypatch, _handler)
    monkeypatch.setattr(uptime.time, "sleep", lambda seconds: None)

    UptimeClient("key").list_monitors()

    assert len(attempts) == 2


def test_find_monitor_takes_status_from_by_id(monkeypatch):
    """В списке статус - это результат проверки (UP), а пауза видна по id."""
    urls = []

    def _handler(request):
        urls.append(request.full_url)
        if "/monitors/1" in request.full_url:
            return _Response({"id": 1, "url": "https://example.com", "status": "PAUSED"})
        return _Response(
            {"data": [{"id": 1, "url": "https://example.com", "status": "UP"}]}
        )

    _patch_urlopen(monkeypatch, _handler)

    monitor = UptimeClient("key").find_monitor(url="https://example.com")

    assert monitor["status"] == "PAUSED"
    assert any("/monitors/1" in url for url in urls)


def test_find_monitor_remembers_id(monkeypatch):
    """Найденный монитор запоминаем - список больше не переспрашиваем."""
    urls = []

    def _handler(request):
        urls.append(request.full_url)
        if "/monitors/1" in request.full_url:
            return _Response({"id": 1, "url": "https://example.com", "status": "UP"})
        return _Response(
            {"data": [{"id": 1, "url": "https://example.com", "status": "UP"}]}
        )

    _patch_urlopen(monkeypatch, _handler)
    client = UptimeClient("key")

    client.find_monitor(url="https://example.com")
    list_calls = len([url for url in urls if url.endswith("limit=50")])
    client.find_monitor(url="https://example.com")

    assert list_calls == 1


def test_create_monitor_sends_http_type(monkeypatch):
    """Монитор создаётся как HTTP с интервалом 5 минут."""
    calls = _patch_urlopen(monkeypatch, lambda request: _Response({"id": 7}))

    UptimeClient("key").create_monitor(url="https://example.com/health")

    body = json.loads(calls[0].data.decode("utf-8"))
    assert body["type"] == "HTTP"
    assert body["url"] == "https://example.com/health"
    assert body["interval"] == 300
    assert body["httpMethodType"] == "GET"


def test_http_error_becomes_uptime_error(monkeypatch):
    """Ошибка API превращается в UptimeError с кодом ответа."""
    import urllib.error

    def _handler(request):
        raise urllib.error.HTTPError(
            "url", 401, "unauthorized", {}, None
        )

    _patch_urlopen(monkeypatch, _handler)

    with pytest.raises(UptimeError) as error:
        UptimeClient("bad-key").list_monitors()

    assert "401" in str(error.value)


# ---------- Синхронизация состояния ----------


class _FakeClient:
    """Клиент-заглушка: запоминает вызовы паузы и запуска."""

    def __init__(self, monitor=None, night=None):
        self.monitor = monitor
        self.night = night
        self.paused = []
        self.started = []

    def find_by_name(self, name):
        if name == uptime.MONITOR_NAME:
            return self.monitor
        if name == uptime.NIGHT_MONITOR_NAME:
            return self.night
        return None

    def find_monitor(self, url=None, name=None):
        return self.find_by_name(name) if name else self.monitor

    def ensure_monitor(self, name, url, interval):
        found = self.find_by_name(name)
        if found:
            return found
        created = {"id": 99, "friendlyName": name, "status": "UP", "interval": interval}
        if name == uptime.MONITOR_NAME:
            self.monitor = created
        else:
            self.night = created
        return created

    def monitor_state(self, monitor):
        return "paused" if monitor.get("status") == "PAUSED" else "active"

    def pause_monitor(self, monitor_id):
        self.paused.append(monitor_id)
        return {}

    def start_monitor(self, monitor_id):
        self.started.append(monitor_id)
        return {}


def test_sync_pauses_monitor_at_night():
    """Ночью активный монитор ставится на паузу."""
    client = _FakeClient({"id": 5, "status": "UP"})

    action = uptime.sync_monitor(client, False, "https://example.com")

    assert action == "paused"
    assert client.paused == [5]


def test_sync_starts_paused_monitor_in_day():
    """Днём монитор снимается с паузы."""
    client = _FakeClient({"id": 5, "status": "PAUSED"})

    action = uptime.sync_monitor(client, True, "https://example.com")

    assert action == "started"
    assert client.started == [5]


def test_sync_leaves_monitor_alone():
    """Если состояние уже нужное - ничего не делаем."""
    client = _FakeClient({"id": 5, "status": "UP"})

    action = uptime.sync_monitor(client, True, "https://example.com")

    assert action == "unchanged"
    assert client.paused == []
    assert client.started == []


def test_sync_without_monitor_reports_missing():
    """Если монитора нет - сообщаем об этом."""
    client = _FakeClient(None)

    assert uptime.sync_monitor(client, True, "https://example.com") == "missing"


def test_apply_state_uses_already_found_monitor():
    """Найденный монитор обрабатываем без повторного запроса списка."""
    client = _FakeClient({"id": 9, "status": "UP"})
    calls = []
    client.find_monitor = lambda url=None, name=None: calls.append(1)

    action = uptime.apply_state(client, {"id": 9, "status": "UP"}, False)

    assert action == "paused"
    assert client.paused == [9]
    assert calls == []


# ---------- Два монитора: поиск по имени и синхронизация ----------

DAY_ID = 111
NIGHT_ID = 222


def _two_monitors_handler(request):
    """Ответ API для двух мониторов с одинаковым адресом."""
    url = request.full_url
    if f"/monitors/{DAY_ID}" in url:
        return _Response(
            {
                "id": DAY_ID,
                "friendlyName": uptime.MONITOR_NAME,
                "url": "https://example.com/health",
                "status": "PAUSED",
                "interval": 300,
            }
        )
    if f"/monitors/{NIGHT_ID}" in url:
        return _Response(
            {
                "id": NIGHT_ID,
                "friendlyName": uptime.NIGHT_MONITOR_NAME,
                "url": "https://example.com/health",
                "status": "UP",
                "interval": 3600,
            }
        )
    return _Response(
        {
            "data": [
                {
                    "id": DAY_ID,
                    "friendlyName": uptime.MONITOR_NAME,
                    "url": "https://example.com/health",
                    "status": "UP",
                },
                {
                    "id": NIGHT_ID,
                    "friendlyName": uptime.NIGHT_MONITOR_NAME,
                    "url": "https://example.com/health",
                    "status": "UP",
                },
            ]
        }
    )


def test_find_by_name_separates_monitors_with_same_url(monkeypatch):
    """Мониторы с одинаковым адресом различаются по имени."""
    _patch_urlopen(monkeypatch, _two_monitors_handler)
    client = UptimeClient("key")

    day = client.find_by_name(uptime.MONITOR_NAME)
    night = client.find_by_name(uptime.NIGHT_MONITOR_NAME)

    assert day["id"] == DAY_ID
    assert night["id"] == NIGHT_ID
    assert day["status"] == "PAUSED"


def test_find_by_name_remembers_id(monkeypatch):
    """Найденный id запоминаем - список больше не переспрашиваем."""
    urls = []
    handler = _two_monitors_handler

    def _handler(request):
        urls.append(request.full_url)
        return handler(request)

    _patch_urlopen(monkeypatch, _handler)
    client = UptimeClient("key")

    client.find_by_name(uptime.MONITOR_NAME)
    list_calls = len([url for url in urls if url.endswith("limit=50")])
    client.find_by_name(uptime.MONITOR_NAME)

    assert list_calls == 1


def test_ensure_monitor_creates_missing(monkeypatch):
    """Если монитора нет - он создаётся с нужным интервалом."""
    calls = _patch_urlopen(monkeypatch, lambda request: _Response({"data": []}))

    client = UptimeClient("key")
    monitor = client.ensure_monitor(
        uptime.NIGHT_MONITOR_NAME, "https://example.com/health", 3600
    )

    assert monitor is not None
    body = json.loads(calls[-1].data.decode("utf-8"))
    assert body["friendlyName"] == uptime.NIGHT_MONITOR_NAME
    assert body["interval"] == 3600


def test_ensure_monitor_keeps_existing(monkeypatch):
    """Существующий монитор не пересоздаём."""
    _patch_urlopen(monkeypatch, _two_monitors_handler)
    calls = _patch_urlopen(monkeypatch, _two_monitors_handler)

    client = UptimeClient("key")
    monitor = client.ensure_monitor(
        uptime.MONITOR_NAME, "https://example.com/health", 300
    )

    assert monitor["id"] == DAY_ID
    assert not any(request.method == "POST" for request in calls)


def test_sync_all_day_and_night():
    """Днём основной включается, дежурный всегда работает."""
    client = _FakeClient(
        monitor={"id": 1, "status": "PAUSED"},
        night={"id": 2, "status": "UP"},
    )

    actions = uptime.sync_all(client, True)

    assert actions["day"] == "started"
    assert actions["night"] == "unchanged"
    assert client.started == [1]


def test_sync_all_at_night_pauses_day_only():
    """Ночью основной монитор на паузе, дежурный продолжает работать."""
    client = _FakeClient(
        monitor={"id": 1, "status": "UP"},
        night={"id": 2, "status": "UP"},
    )

    actions = uptime.sync_all(client, False)

    assert actions["day"] == "paused"
    assert actions["night"] == "unchanged"
    assert client.paused == [1]


def test_sync_all_creates_missing_monitors():
    """Нет мониторов - создаются и сразу приводятся в нужное состояние."""
    client = _FakeClient()

    actions = uptime.sync_all(client, True)

    assert actions["day"] == "unchanged"
    assert actions["night"] == "unchanged"
    assert client.monitor["friendlyName"] == uptime.MONITOR_NAME
    assert client.night["friendlyName"] == uptime.NIGHT_MONITOR_NAME
    assert client.night["interval"] == uptime.NIGHT_CHECK_INTERVAL


# ---------- Фоновый поток ----------


def test_worker_not_started_without_key(monkeypatch):
    """Без ключа API фоновый поток не запускается."""
    monkeypatch.delenv("UPTIME_API_KEY", raising=False)

    assert uptime.start_worker() is False


def test_worker_started_with_key(monkeypatch):
    """С ключом API фоновый поток запускается (без обращений к сети)."""
    monkeypatch.setenv("UPTIME_API_KEY", "test-key")
    started = {}

    class _FakeThread:
        def __init__(self, target, args, name, daemon):
            started["args"] = args

        def start(self):
            started["started"] = True

        def is_alive(self):
            return False

    monkeypatch.setattr(uptime.threading, "Thread", _FakeThread)
    uptime.reset_after_fork()

    assert uptime.start_worker() is True
    assert started.get("started") is True
