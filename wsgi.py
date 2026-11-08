# -*- coding: utf-8 -*-
"""WSGI-точка входа для gunicorn (Render).

Запуск (Render, в команде сервиса):
    gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT wsgi:app

Почему один воркер: на бесплатном плане Render у сервиса один процесс.
Telegram-бот работает long polling - если воркеров несколько, бот будет
пытаться опрашивать Telegram несколько раз одновременно и получит конфликт.
Бот поднимается в потоке этого же процесса.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.bot_runner import start_bot_thread

app = create_app()

# Бот запускается при импорте модуля, то есть уже внутри воркера gunicorn.
start_bot_thread()
