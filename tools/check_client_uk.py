# -*- coding: utf-8 -*-
"""Проверить, какие украинские строки есть в клиенте и не покрыты переводом.

Запуск:
    python tools/check_client_uk.py
"""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UK_MARK = re.compile(r"[іїєґІЇЄҐ]")

out = []
src = json.load(open(os.path.join(ROOT, "app", "static", "i18n_source.json"), encoding="utf-8"))
merged = json.load(open(os.path.join(ROOT, "tools", "i18n_merged_uk.json"), encoding="utf-8"))
u2r = json.load(open(os.path.join(ROOT, "tools", "i18n_uk_to_ru.json"), encoding="utf-8"))

for item in src:
    text = item if isinstance(item, str) else item.get("text", "")
    if not text:
        continue
    ru = merged.get(text)
    mark = bool(UK_MARK.search(text))
    if mark and text not in u2r:
        out.append(("НЕТ_ОБРАТНО", text, ru or ""))
    elif ru is None:
        out.append(("НЕТ_В_СЛОВАРЕ", text, ""))

with open(os.path.join(os.environ.get("TEMP", "."), "i18n_client_gaps.txt"), "w", encoding="utf-8") as handle:
    for kind, text, ru in out:
        handle.write(f"{kind} | {text} | {ru}\n")
print(f"Проблемных строк: {len(out)}")
