# -*- coding: utf-8 -*-
"""Найти украинские строки во всех исходниках проекта.

Исходники должны быть на русском (так требует AGENTS.md), а украинский
появляется только через словарь перевода. Этот скрипт показывает, что
ещё нужно перевести на русский.

Запуск:
    python tools/collect_uk_sources.py
"""

import json
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

# Слова, которые есть только в украинском (без і/ї/є/ґ).
UK_ONLY = re.compile(
    r"\b(Водій|Звіт|Звіти|Видалити|Замовник|Замовника|звіт|звіти|звітів|"
    r"Ні|Так|Дата|Час|Бочка|бочка|Заправка|Заправки|Заправку|Дизель|Бензин|"
    r"Додано|Записано|Оплачено|Шиномонтаж|Назад|Файл|збережено|знято|"
    r"додати|додано|видалено|видалити|видалив|зберег|завантаж|звітів)\b"
)
UK_MARK = re.compile(r"[іїєґІЇЄҐ]")
LITERAL = re.compile(r'"([^"\n]*)"|\'([^\'\n]*)\'')


def main() -> int:
    """Собрать украинские строки по файлам."""
    rows = []
    for path in FILES:
        name = os.path.relpath(path, ROOT)
        source = open(path, encoding="utf-8").read()
        found = set()
        for match in LITERAL.finditer(source):
            value = match.group(1) if match.group(1) is not None else match.group(2)
            if not value or len(value) > 120:
                continue
            if UK_MARK.search(value) or UK_ONLY.search(value):
                found.add(value)
        for value in sorted(found):
            rows.append(f"{name} | {value}")

    out = os.path.join(os.environ.get("TEMP", "."), "i18n_uk_sources.txt")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(rows))
    print(f"Строк: {len(rows)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
