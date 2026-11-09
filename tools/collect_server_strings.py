# -*- coding: utf-8 -*-
"""Собрать русские строки сервера (сообщения API и бота) для перевода.

Запуск:
    python tools/collect_server_strings.py

Результат:
    tools/i18n_server_ru.json - строки, которые видит пользователь
"""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CYR = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")

SOURCES = [
    os.path.join(ROOT, "app", "legacy_routes.py"),
    os.path.join(ROOT, "app", "routes.py"),
    os.path.join(ROOT, "bot", "bot.py"),
    os.path.join(ROOT, "app", "i18n.py"),
]

# Строки, которые не переводим (служебные, имена, единицы).
SKIP = {
    "водитель",
    "оператор",
    "суперадмин",
}


def main() -> int:
    """Собрать строки сервера."""
    result: dict[str, str] = {}
    for path in SOURCES:
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        for match in re.finditer(r'"([^"\n]*)"|\'([^\'\n]*)\'', source):
            value = match.group(1) if match.group(1) is not None else match.group(2)
            if not value or len(value) > 200:
                continue
            if not CYR.search(value):
                continue
            if "<" in value or ">" in value or "{" in value or "}" in value:
                continue
            if value.strip() != value:
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
