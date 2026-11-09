# -*- coding: utf-8 -*-
"""Проверить, что все сообщения сервера есть в словаре переводов.

Запуск:
    python tools/check_server_msgs.py
"""

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


def collect(path: str) -> set:
    """Собрать строковые литералы, которые уходят пользователю."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
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
    for name in ("legacy_routes.py", "routes.py", "notifications.py"):
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
