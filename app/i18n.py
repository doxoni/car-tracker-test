# -*- coding: utf-8 -*-
"""Переводы интерфейса: русский и украинский.

Исходники проекта на русском (так требует AGENTS.md), украинский появляется
только через словарь app/i18n_dict.py, который собирается из
tools/i18n_dict.json скриптом tools/build_i18n_dict.py.

Язык пользователя хранится в users.lang: его выбирают в боте (команда
/language) или в Mini App (кнопка смены языка).

Запуск (из папки проекта):
    python app/main.py
"""

import json

from flask import g, request

from app.i18n_dict import MESSAGES

DEFAULT_LANG = "ru"
LANGS = ("ru", "uk")
LANG_NAMES = {"ru": "Русский", "uk": "Українська"}


def normalize_lang(value) -> str:
    """Привести значение к 'ru' или 'uk'; всё остальное - русский."""
    text = str(value or "").strip().lower()
    return text if text in LANGS else DEFAULT_LANG


def t(text: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Перевести строку с русского на украинский.

    В kwargs можно передать значения для подстановки: {plate}, {count}.
    """
    result = MESSAGES.get(text, text)
    if kwargs:
        try:
            result = result.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            try:
                result = text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                pass
    return result


def current_lang() -> str:
    """Язык текущего запроса.

    Берём язык из базы (поле users.lang). Если язык ещё не выбран,
    смотрим параметр ?lang= в адресе - так бот передаёт выбранный язык
    при первом открытии Mini App.
    """
    user = getattr(g, "current_user", None)
    lang = getattr(user, "lang", None)
    if not lang:
        try:
            lang = request.args.get("lang")
        except RuntimeError:
            # Вне контекста запроса (например, в потоке бота).
            lang = None
    return normalize_lang(lang)


def translate_response(response):
    """Перевести текстовые поля ответа ("error", "message") на язык пользователя.

    Файл отчёта (text/plain) здесь не трогаем - его переводит сам отчёт.
    """
    if response.mimetype != "application/json":
        return response
    lang = current_lang()
    if lang == DEFAULT_LANG:
        return response
    data = response.get_json(silent=True)
    if not isinstance(data, dict):
        return response
    changed = False
    for key in ("error", "message"):
        value = data.get(key)
        if isinstance(value, str):
            translated = t(value, lang)
            if translated != value:
                data[key] = translated
                changed = True
    if not changed:
        return response
    response.set_data(json.dumps(data, ensure_ascii=False))
    return response
