# -*- coding: utf-8 -*-
"""UptimeRobot: дневной пинг сервиса и ночная пауза монитора.

Зачем это нужно:
    Бесплатный Render усыпляет веб-сервис после 15 минут без входящих
    запросов. Пока контейнер работает - идут инстанс-часы, а лимит
    бесплатного тарифа - 750 часов в месяц (31 день x 24 часа = 744,
    поэтому сервис, работающий круглые сутки, в конце месяца исчерпывает
    лимит). Поэтому:
      - днём монитор UptimeRobot пингует /api/health раз в 5 минут и держит
        контейнер awake - Mini App открывается сразу;
      - ночью монитор стоит на паузе - пингов нет, контейнер засыпает сам
        и часы не тратятся.

Кто управляет паузой:
    Сам контейнер (фоновый поток в app/uptime.py): в 23:00 по Киеву он
    снимает монитор с паузы... точнее - ставит на паузу, а когда контейнер
    просыпается днём (по запросу пользователя или по пингу) - включает
    монитор обратно. Поэтому сервис спит ночью и просыпается по команде.

Ключ API живёт только в переменной окружения UPTIME_API_KEY (на Render) или
в файле uptime_key.txt (локально, файл в .gitignore). В коде и Git его
быть не должно.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------- Настройки ----------

API_BASE = "https://api.uptimerobot.com/v3"
DEFAULT_MONITOR_URL = "https://car-tracker-test.onrender.com/api/health"
MONITOR_NAME = "car-tracker-test"

# Минимальный интервал проверки на бесплатном плане UptimeRobot - 5 минут.
CHECK_INTERVAL = 300

# Таймаут запросов к API, секунды.
REQUEST_TIMEOUT = 30

# Как часто фоновый поток сверяет состояние монитора с нужным, секунды.
WORKER_INTERVAL = 300


class UptimeError(Exception):
    """Ошибка при обращении к API UptimeRobot."""


# ---------- Клиент API ----------


class UptimeClient:
    """Клиент API UptimeRobot (версия 3).

    Авторизация - заголовком Authorization: Bearer <ключ>.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = API_BASE,
        timeout: int = REQUEST_TIMEOUT,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        """Один запрос к API. Ошибки превращаются в UptimeError."""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.api_key}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise UptimeError(f"{method} {path} -> {error.code}: {detail}") from error
        except Exception as error:  # noqa: BLE001 - сеть может отвалиться
            raise UptimeError(
                f"{method} {path} -> {type(error).__name__}: {error}"
            ) from error

        if not payload.strip():
            return {}
        try:
            return json.loads(payload)
        except ValueError as error:
            raise UptimeError(f"{method} {path} -> ответ не в JSON") from error

    def list_monitors(self) -> list[dict]:
        """Все мониторы аккаунта."""
        data = self._request("GET", "/monitors?limit=200")
        monitors = data.get("data")
        if monitors is None:
            monitors = data.get("result") or []
        return list(monitors)

    def find_monitor(
        self, url: str | None = None, name: str | None = None
    ) -> dict | None:
        """Найти монитор по адресу или по имени. None - если не найден."""
        for monitor in self.list_monitors():
            if url and monitor.get("url") == url:
                return monitor
            if name and monitor.get("friendlyName") == name:
                return monitor
        return None

    def create_monitor(
        self,
        url: str = DEFAULT_MONITOR_URL,
        name: str = MONITOR_NAME,
        interval: int = CHECK_INTERVAL,
    ) -> dict:
        """Создать HTTP-монитор."""
        body = {
            "type": "HTTP",
            "friendlyName": name,
            "url": url,
            "interval": interval,
            "httpMethodType": "GET",
            "timeout": 60,
            # Несколько минут на то, чтобы сервис проснулся после сна.
            "gracePeriod": 300,
        }
        return self._request("POST", "/monitors", body)

    def pause_monitor(self, monitor_id) -> dict:
        """Поставить монитор на паузу (идемпотентно)."""
        return self._request("POST", f"/monitors/{monitor_id}/pause", {})

    def start_monitor(self, monitor_id) -> dict:
        """Снять монитор с паузы (идемпотентно)."""
        return self._request("POST", f"/monitors/{monitor_id}/start", {})

    def monitor_state(self, monitor: dict) -> str:
        """Состояние монитора: 'paused' или 'active'."""
        status = str(monitor.get("status") or "").upper()
        return "paused" if status == "PAUSED" else "active"


# ---------- Когда монитор должен работать ----------


def _env_int(name: str, default: int) -> int:
    """Число из переменной окружения (с запасным значением)."""
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def start_hour() -> int:
    """Час начала дневного окна (по умолчанию 07:00)."""
    return _env_int("UPTIME_START_HOUR", 7)


def end_hour() -> int:
    """Час конца дневного окна (по умолчанию 23:00)."""
    return _env_int("UPTIME_END_HOUR", 23)


def tz_name() -> str:
    """Часовой пояс для окна дня и ночи."""
    return (os.getenv("UPTIME_TZ") or "Europe/Kyiv").strip()


def desired_active(moment: datetime | None = None) -> bool:
    """Должен ли монитор работать в этот момент.

    Днём (по умолчанию 07:00-23:00 по Киеву) - да: пинг держит контейнер
    awake. Ночью - нет: контейнер должен спать и не тратить часы тарифа.
    """
    tz = ZoneInfo(tz_name())
    moment = moment or datetime.now(tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    else:
        moment = moment.astimezone(tz)

    start = start_hour()
    end = end_hour()
    hour = moment.hour

    if start <= end:
        return start <= hour < end
    # Окно переходит через полночь (например, 23:00-07:00).
    return hour >= start or hour < end


def monitor_url() -> str:
    """Адрес, который проверяет монитор."""
    return (os.getenv("UPTIME_MONITOR_URL") or DEFAULT_MONITOR_URL).strip()


def sync_monitor(
    client: UptimeClient,
    active: bool,
    url: str | None = None,
) -> str:
    """Привести монитор в нужное состояние.

    Возвращает: 'started' (сняли с паузы), 'paused' (поставили на паузу),
    'unchanged' (уже в нужном состоянии), 'missing' (монитора нет).
    """
    monitor = client.find_monitor(url=url or monitor_url())
    if not monitor:
        return "missing"

    paused = client.monitor_state(monitor) == "paused"
    monitor_id = monitor.get("id")

    if active and paused:
        client.start_monitor(monitor_id)
        return "started"
    if not active and not paused:
        client.pause_monitor(monitor_id)
        return "paused"
    return "unchanged"


# ---------- Фоновый поток в контейнере ----------

_worker_thread = None
_worker_lock = threading.Lock()

# Состояние для /api/health: логи Render через API не читаются,
# поэтому состояние монитора видно только здесь.
STATE = {
    "enabled": False,
    "status": "disabled",
    "monitor_status": "",
    "last_action": "",
    "updated_at": "",
    "error": "",
}


def state() -> dict:
    """Состояние монитора для /api/health."""
    return dict(STATE)


def _worker_loop(client: UptimeClient, url: str, interval: int) -> None:
    """Следить за состоянием монитора, пока жив контейнер."""
    from datetime import datetime

    while True:
        action = "missing"
        try:
            active = desired_active()
            monitor = client.find_monitor(url=url)
            if monitor:
                STATE["monitor_status"] = monitor.get("status") or ""
                action = sync_monitor(client, active, url)
                STATE["status"] = "active" if active else "paused"
                if action in ("started", "paused"):
                    state_text = "включён" if active else "на паузе"
                    print(f"⏱ UptimeRobot: монитор {state_text}", flush=True)
            else:
                STATE["status"] = "missing"
            STATE["last_action"] = action
            STATE["error"] = ""
        except Exception as exc:  # noqa: BLE001 - поток не должен умирать
            STATE["status"] = "error"
            STATE["error"] = f"{type(exc).__name__}: {exc}"[:200]
            print(f"⚠️ UptimeRobot: {exc}", flush=True)
        STATE["updated_at"] = datetime.now().isoformat(timespec="seconds")
        time.sleep(interval)


def start_worker(
    api_key: str | None = None,
    url: str | None = None,
    interval: int = WORKER_INTERVAL,
) -> bool:
    """Запустить фоновый поток, который управляет паузой монитора.

    Без ключа API (UPTIME_API_KEY) ничего не запускается - сервис работает
    как раньше. Возвращает True, если поток запущен.
    """
    global _worker_thread

    key = (api_key or os.getenv("UPTIME_API_KEY") or "").strip()
    if not key:
        return False

    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return True
        _worker_thread = threading.Thread(
            target=_worker_loop,
            args=(UptimeClient(key), url or monitor_url(), interval),
            name="uptime-monitor",
            daemon=True,
        )
        STATE["enabled"] = True
        STATE["status"] = "starting"
        _worker_thread.start()
    return True


def reset_after_fork() -> None:
    """Сбросить состояние после форка.

    Потоки при форке не переносятся, а замок мог остаться запертым в
    дочернем процессе - поэтому делаем новый.
    """
    global _worker_thread, _worker_lock

    _worker_thread = None
    _worker_lock = threading.Lock()
