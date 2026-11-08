# -*- coding: utf-8 -*-
"""Создаёт бесплатную базу PostgreSQL в Neon (карта не нужна).

Что делает:
  1. Берёт API-ключ Neon из файла neon_key.txt (или из переменной
     окружения NEON_API_KEY).
  2. Находит организацию пользователя и создаёт проект "cars".
  3. Забирает пароль роли и собирает строку подключения.
  4. Сохраняет строку в .db_connection.txt.

Запуск (PowerShell, из папки проекта):
    python setup_neon.py

Где взять ключ (один раз, в браузере):
    https://console.neon.tech/app/settings/api-keys -> Create API key
Ключ выглядит как napi_xxxxx. Положи его в файл neon_key.txt
(файл в .gitignore, ключ наружу не печатается).
"""

import os
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

API = "https://console.neon.tech/api/v2"
ROOT = Path(__file__).resolve().parent

PROJECT_NAME = "cars"
# Регион ближе к нам - меньше задержка на запросы.
REGION_ID = "aws-eu-central-1"
PG_VERSION = 17
KEY_FILE = ROOT / "neon_key.txt"
OUT_FILE = ROOT / ".db_connection.txt"


def fail(message: str):
    """Остановить работу с понятным сообщением."""
    print(f"ОШИБКА: {message}")
    sys.exit(1)


def read_key() -> str:
    """API-ключ Neon: из переменной окружения или из neon_key.txt."""
    key = (os.getenv("NEON_API_KEY") or "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return key


def api(method: str, path: str, key: str, payload=None):
    """Запрос к Neon API с обработкой ошибок."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.request(method, f"{API}{path}", headers=headers, json=payload, timeout=60)
    if response.status_code >= 400:
        fail(f"Neon API {method} {path} -> {response.status_code}: {response.text[:500]}")
    if not response.content:
        return {}
    return response.json()


def find_org_id(key: str) -> str:
    """ID организации пользователя (нужен для персонального API-ключа)."""
    orgs = api("GET", "/users/me/organizations", key)
    if not orgs:
        fail("Не нашлась ни одна организация Neon в твоём аккаунте")
    return orgs[0]["id"]


def existing_project(key: str, org_id: str):
    """Проект с таким именем, если он уже есть."""
    projects = api("GET", "/projects", key)
    for project in projects.get("projects", []):
        if project.get("name") == PROJECT_NAME:
            return project
    return None


def extract_params(conn: dict) -> dict:
    """Достать параметры подключения из ответа Neon.

    API отдаёт их по-разному: либо списком connection_uris с полем
    connection_parameters, либо одной строкой uri. Разбираем оба случая.
    """
    uris = conn.get("connection_uris") or []
    if uris:
        params = uris[0].get("connection_parameters") or {}
        if params.get("host"):
            return params

    uri = conn.get("uri") or ""
    if not uri:
        for item in uris:
            uri = item.get("uri") or item.get("connection_uri") or ""
            if uri:
                break
    if not uri:
        fail("Neon не вернул строку подключения для проекта")

    parsed = urlparse(uri)
    params = {
        "host": (parsed.hostname or "").replace("-pooler.", "."),
        "database": (parsed.path or "").lstrip("/") or "neondb",
        "role": parsed.username or "neondb_owner",
    }
    return params


def build_url(data: dict, key: str) -> str:
    """Собрать строку подключения из ответа Neon.

    В connection_uri пароль может быть замаскирован, поэтому берём
    реальный пароль из roles[].password.
    """
    uris = data.get("connection_uris") or []
    if not uris:
        fail("Neon не вернул строку подключения")

    params = uris[0].get("connection_parameters") or {}
    roles = data.get("roles") or []
    password = ""
    for role in roles:
        if role.get("password") and role["password"] != "<password>":
            password = role["password"]
            break

    if not password:
        # Пароль не отдали - значит он не сохранён. Сбрасываем его заново.
        branch_id = roles[0].get("branch_id") if roles else None
        role_name = roles[0].get("name") if roles else None
        if not branch_id or not role_name:
            fail("Neon не вернул пароль роли и не дал данные для сброса")
        reset = api(
            "POST",
            f"/projects/{data['project']['id']}/branches/{branch_id}/roles/{role_name}/reset_password",
            key,
            {},
        )
        password = reset.get("password") or ""
        if not password:
            fail("Не удалось получить пароль роли Neon")

    host = params.get("host") or ""
    host = host.replace("-pooler.", ".")
    if not host:
        fail("Neon не вернул адрес хоста")
    database = params.get("database") or "neondb"
    role = params.get("role") or params.get("user") or "neondb_owner"

    return (
        f"postgresql://{quote(role, safe='')}:{quote(password, safe='')}"
        f"@{host}/{database}?sslmode=require"
    )


def main():
    key = read_key()
    if not key:
        fail(
            "Нет API-ключа Neon.\n"
            "  Создай его: https://console.neon.tech/app/settings/api-keys\n"
            "  и положи в файл neon_key.txt (одна строка, начиная с napi_)."
        )

    print("=== Neon: ищем организацию ===")
    org_id = find_org_id(key)
    print(f"  организация: {org_id}")

    print("=== Neon: создаём проект ===")
    project = existing_project(key, org_id)
    if project:
        print(f"  проект уже есть: {project['name']}")
        project_id = project["id"]
    else:
        response = api(
            "POST",
            "/projects",
            key,
            {
                "project": {
                    "name": PROJECT_NAME,
                    "region_id": REGION_ID,
                    "pg_version": PG_VERSION,
                    "org_id": org_id,
                }
            },
        )
        project = response["project"]
        project_id = project["id"]
        print(f"  создан проект: {project['name']} ({project_id})")

    # Ветка по умолчанию - к ней и относится строка подключения.
    branches = api("GET", f"/projects/{project_id}/branches", key)
    branch = None
    for item in branches.get("branches", []):
        if item.get("default"):
            branch = item
            break
    if branch is None and branches.get("branches"):
        branch = branches["branches"][0]
    if branch is None:
        fail("У проекта Neon нет ни одной ветки")

    # Параметры подключения берём у проекта - так надёжнее, чем
    # разбирать строку connection_uri вручную.
    conn = api(
        "GET",
        f"/projects/{project_id}/connection_uri?database_name=neondb&role_name=neondb_owner",
        key,
    )
    params = extract_params(conn)
    role_name = params.get("role") or params.get("user") or "neondb_owner"

    # Пароль роли не отдают в открытом виде - запрашиваем отдельно.
    role_data = api(
        "GET",
        f"/projects/{project_id}/branches/{branch['id']}/roles/{role_name}/reveal_password",
        key,
    )
    data = {
        "project": {"id": project_id},
        "connection_uris": [{"connection_parameters": params}],
        "roles": [
            {
                "branch_id": branch["id"],
                "name": role_name,
                "password": role_data.get("password", ""),
            }
        ],
    }
    url = build_url(data, key)

    OUT_FILE.write_text(
        "# Neon connection - car-tracker\n" f"DATABASE_URL={url}\n",
        encoding="utf-8",
    )

    print("")
    print("DONE. Подключение сохранено в .db_connection.txt" )
    print("Пароль в консоль не выводится.")


if __name__ == "__main__":
    main()
