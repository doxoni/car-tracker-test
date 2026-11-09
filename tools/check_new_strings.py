# -*- coding: utf-8 -*-
"""Найти строки, для которых ещё нет перевода на украинский.

Берёт уже переведённые файлы и новые батчи, показывает разницу.

Запуск:
    python tools/check_new_strings.py
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

merged = json.load(open(os.path.join(TOOLS, "i18n_merged_uk.json"), encoding="utf-8"))
uk_to_ru = json.load(open(os.path.join(TOOLS, "i18n_uk_to_ru.json"), encoding="utf-8"))
extra = json.load(open(os.path.join(TOOLS, "i18n_uk_to_ru_extra.json"), encoding="utf-8"))

# Переводы, которые уже есть: старое украинское -> русское даёт нам русский -> украинский.
known = {}
for uk, ru in uk_to_ru.items():
    if uk != ru:
        known[ru] = uk
for uk, ru in extra.items():
    if uk != ru:
        known[ru] = uk

batch = []
for index in range(1, 5):
    with open(os.path.join(TOOLS, f"i18n_batch_{index}.json"), encoding="utf-8") as handle:
        batch.extend(json.load(handle))

rows = []
for text in batch:
    if text in merged:
        continue
    if text in known:
        rows.append(f"ЕСТЬ_ОБРАТНО | {text} | {known[text]}")
    else:
        rows.append(f"НУЖЕН_ПЕРЕВОД | {text} |")

out = os.path.join(os.environ.get("TEMP", "."), "i18n_new_strings.txt")
with open(out, "w", encoding="utf-8") as handle:
    handle.write("\n".join(rows))
print(f"Новых строк: {len(rows)} -> {out}")
