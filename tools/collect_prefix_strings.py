# -*- coding: utf-8 -*-
"""Собрать строки с пробелами по краям и префиксы (они склеиваются в JS).

Запуск:
    python tools/collect_prefix_strings.py
"""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CYR = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")

FILES = [
    os.path.join(ROOT, "app", "static", "index.html"),
    os.path.join(ROOT, "app", "static", "new.html"),
    os.path.join(ROOT, "app", "static", "js", "app.js"),
]


def main() -> int:
    """Найти строки, которых ещё нет в основном словаре."""
    with open(
        os.path.join(ROOT, "tools", "i18n_all_ru.json"), encoding="utf-8"
    ) as handle:
        known = set(json.load(handle))

    extra = set()
    for path in FILES:
        source = open(path, encoding="utf-8").read()
        for match in re.finditer(r'"([^"\n]*)"|\'([^\'\n]*)\'', source):
            value = match.group(1) if match.group(1) is not None else match.group(2)
            if not value or len(value) > 200 or not CYR.search(value):
                continue
            if any(ch in value for ch in "<>{}`$"):
                continue
            trimmed = value.strip()
            if not trimmed or trimmed in known:
                continue
            extra.add(trimmed)

    result = sorted(extra)
    out_path = os.path.join(ROOT, "tools", "i18n_extra_ru.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    print(f"Дополнительных строк: {len(result)}")
    for item in result:
        print(f"  {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
