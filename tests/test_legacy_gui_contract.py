# -*- coding: utf-8 -*-
"""Проверка совместимости старого интерфейса с новым сервером.

Старая GUI (app/static/index.html) обращается к API по фиксированным
адресам. Тест собирает эти адреса прямо из HTML и проверяет, что
сервер умеет их обслуживать. Так ломается заранее, если кто-то
переименует или уберёт эндпоинт.

Запуск:
    python -m pytest tests/test_legacy_gui_contract.py -q
"""

import os
import re
import tempfile

import pytest

# Тесты работают на временной SQLite, чтобы не трогать рабочую БД.
_TMP_DB = os.path.join(tempfile.gettempdir(), "car_tracker_gui_contract.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["DEV_MODE"] = "true"
os.environ["DEV_USER_ID"] = "1"

INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app",
    "static",
    "index.html",
)


@pytest.fixture()
def app():
    """Приложение на временной SQLite."""
    from app import create_app, db

    application = create_app()
    with application.app_context():
        db.drop_all()
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


def _gui_api_paths() -> set:
    """Адреса API, которые вызывает старая GUI."""
    with open(INDEX_PATH, encoding="utf-8") as file:
        html = file.read()

    # api("/api/cars") и api("/api/cars/" + carId + "/fuel")
    found = set()
    for match in re.finditer(r"""api\(\s*["'`]([^"'`]+)""", html):
        path = match.group(1)
        if path.startswith("/api/"):
            found.add(path)
    return found


def _server_paths(app) -> set:
    """Адреса API, которые умеет отдавать сервер (без параметров)."""
    paths = set()
    for rule in app.url_map.iter_rules():
        path = str(rule.rule)
        if path.startswith("/api/"):
            paths.add(path)
    return paths


def test_gui_uses_api():
    """GUI действительно обращается к API (иначе тест ниже не имеет смысла)."""
    paths = _gui_api_paths()
    assert len(paths) > 10, paths
    assert "/api/cars" in paths
    assert "/api/catalog" in paths
    assert "/api/month-costs" in paths


def test_all_gui_endpoints_exist(app):
    """Каждый адрес из GUI есть в сервере."""
    server = _server_paths(app)
    missing = []
    for path in sorted(_gui_api_paths()):
        # Адреса с переменной частью проверяем по началу до первого "/",
        # вставленного в строку после кавычки.
        if path in server:
            continue
        # В шаблоне GUI после закрывающей кавычки идёт + carId + "/fuel".
        # Такие адреса проверяем по префиксу до переменной части.
        prefix = path.split('"')[0].split("'")[0]
        if any(rule.startswith(prefix) for rule in server):
            continue
        missing.append(path)

    assert not missing, f"GUI ждёт эти адреса, а сервер их не отдаёт: {missing}"


def test_gui_page_is_served(app):
    """Старая GUI отдаётся по /app и /."""
    client = app.test_client()
    for path in ("/app", "/"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"screen-cars" in response.data
