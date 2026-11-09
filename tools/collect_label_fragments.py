# -*- coding: utf-8 -*-
"""Собрать подписи-фрагменты: куски текста со двоеточием и скобками.

Они склеиваются с числами в одну строку, поэтому обычное совпадение целой
строки не срабатывает. Движок перевода ищет такие куски внутри текста.

Запуск:
    python tools/collect_label_fragments.py
"""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    os.path.join(ROOT, "app", "static", "index.html"),
    os.path.join(ROOT, "app", "static", "new.html"),
    os.path.join(ROOT, "app", "static", "js", "app.js"),
]

CYR = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
LITERAL = re.compile(r'"([^"\n]*)"|\'([^\'\n]*)\'')


def main() -> int:
    """Найти подписи, которые склеиваются с числами."""
    found = set()
    for path in FILES:
        source = open(path, encoding="utf-8").read()
        for match in LITERAL.finditer(source):
            value = match.group(1) if match.group(1) is not None else match.group(2)
            if not value or len(value) > 80:
                continue
            if not CYR.search(value):
                continue
            if any(ch in value for ch in "<>{}`$"):
                continue
            trimmed = value.strip()
            if not trimmed:
                continue
            # Подпись с двоеточием в конце или в середине, со скобками,
            # либо с отглагольным окончанием - такие и склеиваются.
            if ":" in trimmed or "(" in trimmed or trimmed.endswith("…"):
                found.add(trimmed)

    result = sorted(found)
    out = os.path.join(ROOT, "tools", "i18n_fragments.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    print(f"Фрагментов: {len(result)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
