# -*- coding: utf-8 -*-
"""Проверить, что в исходниках не осталось украинских букв.

Запуск:
    python tools/check_uk_leftovers.py
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    os.path.join(ROOT, "app", "static", "index.html"),
    os.path.join(ROOT, "app", "static", "new.html"),
    os.path.join(ROOT, "app", "static", "js", "app.js"),
    os.path.join(ROOT, "app", "legacy_routes.py"),
    os.path.join(ROOT, "app", "routes.py"),
    os.path.join(ROOT, "bot", "bot.py"),
]

UK = re.compile(r"[іїєґІЇЄҐ]")


def main() -> int:
    """Показать строки с украинскими буквами."""
    total = 0
    for path in FILES:
        if not os.path.exists(path):
            continue
        name = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if UK.search(line):
                    total += 1
                    print(f"{name}:{number}: {line.rstrip()}")
    print(f"Строк с украинскими буквами: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
