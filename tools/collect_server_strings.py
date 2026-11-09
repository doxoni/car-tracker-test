# -*- coding: utf-8 -*-
"""Собрать русские строки сервера (сообщения API и бота) для перевода.

Строки берём через ast: так в список не попадают докстринги и комментарии,
которые видит только разработчик.

Запуск:
    python tools/collect_server_strings.py

Результат:
    tools/i18n_server_ru.json - строки, которые видит пользователь
"""

import ast
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CYR = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")

SOURCES = [
    os.path.join(ROOT, "app", "legacy_routes.py"),
    os.path.join(ROOT, "app", "routes.py"),
    os.path.join(ROOT, "app", "auth.py"),
    os.path.join(ROOT, "bot", "bot.py"),
    os.path.join(ROOT, "app", "i18n.py"),
    os.path.join(ROOT, "app", "notifications.py"),
]

# Строки, которые не переводим (служебные, имена, единицы, названия языков).
SKIP = {
    "водитель",
    "оператор",
    "суперадмин",
    "🇷🇺 Русский",
    "🇺🇦 Українська",
    "⚠️ TELEGRAM_TOKEN не задан, уведомление не отправлено",
}


def iter_strings(path):
    """Строковые литералы файла, кроме докстрингов и кусков f-строк."""
    source = open(path, encoding="utf-8").read()
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    docstrings.add(id(value))
    # Куски f-строк ("одометр меньше текущего пробега (") - это не готовая
    # фраза, переводить её отдельно бессмысленно.
    in_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                in_fstring.add(id(part))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings or id(node) in in_fstring:
                continue
            yield node.value


def main() -> int:
    """Собрать строки сервера."""
    result: dict[str, str] = {}
    for path in SOURCES:
        if not os.path.exists(path):
            continue
        for value in iter_strings(path):
            if not value or len(value) > 200:
                continue
            if not CYR.search(value):
                continue
            if "<" in value or ">" in value or "{" in value or "}" in value:
                continue
            if value.strip() != value:
                continue
            if len(value.strip()) < 2:
                continue
            if value in SKIP:
                continue
            result[value] = ""

    out_path = os.path.join(ROOT, "tools", "i18n_server_ru.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    print(f"Серверных строк: {len(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
