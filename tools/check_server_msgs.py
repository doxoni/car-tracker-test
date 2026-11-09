# -*- coding: utf-8 -*-
"""Проверить, что все сообщения сервера есть в словаре переводов.

Запуск:
    python tools/check_server_msgs.py
"""

import ast
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

STR = r'"((?:[^"\\]|\\.)*)"'

PATTERNS = [
    re.compile(r"_fail\(\s*" + STR),
    re.compile(r'"(?:message|error)":\s*' + STR),
]


def strip_docstrings(source: str) -> str:
    """Убрать докстринги: примеры в документации не сообщения пользователю.

    Текст режем по координатам ast - исходный код не переписывается,
    иначе кавычки поменяются и поиск по шаблону перестанет работать.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        value = first.value
        start = value.lineno - 1
        end = value.end_lineno
        for index in range(start, min(end, len(lines))):
            lines[index] = ""
    return "".join(lines)


def collect(path: str) -> set:
    """Собрать строковые литералы, которые уходят пользователю."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    text = strip_docstrings(text)
    found = set()
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            found.add(match.group(1))
    return found


def main() -> int:
    """Показать сообщения, для которых нет перевода."""
    with open(os.path.join(TOOLS, "i18n_dict.json"), encoding="utf-8") as handle:
        dictionary = json.load(handle)

    messages = set()
    for name in ("legacy_routes.py", "routes.py", "notifications.py", "auth.py"):
        path = os.path.join(ROOT, "app", name)
        if os.path.exists(path):
            messages |= collect(path)

    missing = sorted(text for text in messages if text not in dictionary)
    print(f"Сообщений: {len(messages)}; без перевода: {len(missing)}")
    for text in missing:
        print(f"  | {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
