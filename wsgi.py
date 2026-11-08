# -*- coding: utf-8 -*-
"""WSGI-точка входа для gunicorn (Render).

Запуск (Render, в команде сервиса):
    gunicorn -c gunicorn.conf.py --workers 1 --threads 4 --bind 0.0.0.0:$PORT wsgi:app

Почему один воркер: на бесплатном плане Render у сервиса один процесс.
Telegram-бот работает long polling - если воркеров несколько, бот будет
пытаться опрашивать Telegram несколько раз одновременно и получит конфликт.

Бота здесь НЕ поднимаем: если модуль импортируется до создания воркера
(так бывает при preload), поток бота не переживёт fork и бот не будет
работать. Запуск делает gunicorn.conf.py (хук post_worker_init) - это
уже тот процесс, который обслуживает запросы.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()
