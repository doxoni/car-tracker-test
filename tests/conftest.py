# -*- coding: utf-8 -*-
"""Общие настройки тестов car-tracker.

Тесты работают на временной SQLite, чтобы не трогать рабочую БД.
Переменные окружения выставляются до импорта app.config - конфиг
читает их в момент импорта.
"""

import os
import tempfile

_TMP_DB = os.path.join(tempfile.gettempdir(), "car_tracker_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["DEV_MODE"] = "true"
os.environ["DEV_USER_ID"] = "1"
os.environ["BOT_ENABLED"] = "0"
