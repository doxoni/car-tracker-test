# -*- coding: utf-8 -*-
"""Тесты перевода интерфейса: русский и украинский.

Запуск (PowerShell, из папки проекта):
    python -m pytest tests/test_i18n.py -q
"""

import json
import os
import tempfile

import pytest

# Тесты работают на временной SQLite, чтобы не трогать рабочую БД.
_TMP_DB = os.path.join(tempfile.gettempdir(), "car_tracker_i18n_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["DEV_MODE"] = "true"
os.environ["DEV_USER_ID"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def client():
    """Клиент Flask с чистой БД и тестовым пользователем."""
    from app import create_app, db
    from app.models import User

    application = create_app()
    with application.app_context():
        db.drop_all()
        db.create_all()
        db.session.add(User(tg_id=1, level=1, is_whitelisted=True))
        db.session.commit()
    with application.test_client() as test_client:
        yield test_client
    with application.app_context():
        db.session.remove()
        db.drop_all()


# ---------- Словарь ----------

def test_dictionary_has_both_languages():
    """В словаре есть русский и украинский варианты."""
    from app.i18n_dict import MESSAGES

    assert MESSAGES
    for ru, uk in MESSAGES.items():
        assert ru and uk


def test_dictionary_covers_interface():
    """Все строки интерфейса переведены."""
    from app.i18n_dict import MESSAGES

    with open(os.path.join(ROOT, "app", "static", "i18n_source.json"), encoding="utf-8") as handle:
        candidates = json.load(handle)
    with open(os.path.join(ROOT, "tools", "i18n_fragments.json"), encoding="utf-8") as handle:
        fragments = json.load(handle)

    missing = [
        text
        for text in candidates
        if text not in MESSAGES
        and not any(fragment in text for fragment in fragments)
    ]
    assert missing == []


def test_server_strings_covered():
    """Строки сервера (ошибки API, сообщения бота) переведены."""
    from app.i18n_dict import MESSAGES

    with open(os.path.join(ROOT, "tools", "i18n_server_ru.json"), encoding="utf-8") as handle:
        server = json.load(handle)

    missing = [text for text in server if text not in MESSAGES]
    assert missing == []


# ---------- Перевод строк ----------

def test_normalize_lang():
    """Нормализация языка: пусто и неизвестное -> русский."""
    from app.i18n import normalize_lang

    assert normalize_lang("uk") == "uk"
    assert normalize_lang("ru") == "ru"
    assert normalize_lang("") == "ru"
    assert normalize_lang(None) == "ru"
    assert normalize_lang("de") == "ru"
    assert normalize_lang("UK") == "uk"


def test_t_russian_returns_source():
    """Для русского текст не меняется."""
    from app.i18n import t

    assert t("Заправки:", "ru") == "Заправки:"


def test_t_ukrainian_translates():
    """Для украинского текст переводится."""
    from app.i18n import t

    assert t("Пробег:", "uk") != "Пробег:"
    assert t("Пробег:", "uk") == "Пробіг:"


def test_t_keeps_unknown_text():
    """Неизвестная строка остаётся как есть."""
    from app.i18n import t

    assert t("Строка без перевода", "uk") == "Строка без перевода"


def test_t_formats_placeholders():
    """Подстановка {подсказка} работает."""
    from app.i18n import t

    text = t("✅ {action}: вам выдан {level} уровень ({name}).", "uk", action="Выдан", level=2, name="оператор")
    assert "{action}" not in text
    assert "2" in text


# ---------- API языка ----------

def test_get_language_default(client):
    """Без выбора язык не задан (None)."""
    response = client.get("/api/language")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["lang"] is None


def test_set_language_saves(client):
    """Выбор языка сохраняется."""
    response = client.post("/api/language", json={"lang": "uk"})
    assert response.status_code == 200
    assert response.get_json()["lang"] == "uk"

    response = client.get("/api/language")
    assert response.get_json()["lang"] == "uk"


def test_set_language_invalid(client):
    """Непонятный язык не сохраняется."""
    response = client.post("/api/language", json={"lang": "de"})
    assert response.status_code == 200
    assert response.get_json()["lang"] == "ru"


def test_response_translated_for_ukrainian(client):
    """Ошибка API переводится на язык пользователя."""
    client.post("/api/language", json={"lang": "uk"})
    response = client.get("/api/cars/999999")
    assert response.status_code in (404, 403)
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"] != "машина не найдена"


def test_response_russian_by_default(client):
    """Без выбора языка ответ остаётся русским."""
    response = client.get("/api/cars/999999")
    assert response.status_code in (404, 403)
    assert response.get_json()["error"] == "машина не найдена"
