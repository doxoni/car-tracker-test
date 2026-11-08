# -*- coding: utf-8 -*-
"""Настройки gunicorn для Render.

Gunicorn подхватывает этот файл автоматически (имя по умолчанию -
gunicorn.conf.py в рабочей папке).

Зачем нужен хук post_worker_init:
    gunicorn сначала импортирует приложение в главном процессе
    (master), а потом создаёт воркеры форком. Потоки при форке не
    переносятся - бот, поднятый при импорте, в воркере не существует.
    Поэтому бота запускаем здесь: post_worker_init вызывается уже в
    том процессе, который обслуживает запросы.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def post_worker_init(worker):
    """Запустить Telegram-бота в воркере, который обслуживает запросы."""
    from app.bot_runner import ensure_bot_started

    ensure_bot_started()
