# -*- coding: utf-8 -*-
"""Повтор запроса к БД, если облачная база была «спящей».

У Neon и similar compute засыпает после простоя и просыпается за
несколько сотен миллисекунд. Первый запрос в спящую базу падает с
OperationalError, хотя через мгновение всё работает.

Здесь один понятный помощник: повторить запрос один раз.
"""

from sqlalchemy.exc import OperationalError


def run_with_retry(func, *args, **kwargs):
    """Выполнить func, а при ошибке соединения - повторить один раз.

    func должна сама делать запрос к БД (например, db.session.execute).
    Повтор делаем на новой сессии, потому что после обрыва старая
    соединена в пуле уже непригодна.
    """
    from app import db

    try:
        return func(*args, **kwargs)
    except OperationalError:
        db.session.rollback()
        db.session.remove()
        return func(*args, **kwargs)
