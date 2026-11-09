# -*- coding: utf-8 -*-
"""Показать клиентские строки, которые не изменились при переводе.

Если строка осталась как есть, значит она уже была на украинском (или
одинакова в обоих языках). Такие строки нужно проверить вручную: если
украинская - нужен обратный перевод в русский.

Запуск:
    python tools/check_client_same.py
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

src = json.load(open(os.path.join(ROOT, "app", "static", "i18n_source.json"), encoding="utf-8"))
merged = json.load(open(os.path.join(ROOT, "tools", "i18n_merged_uk.json"), encoding="utf-8"))
u2r = json.load(open(os.path.join(ROOT, "tools", "i18n_uk_to_ru.json"), encoding="utf-8"))

lines = []
for item in src:
    text = item if isinstance(item, str) else item.get("text", "")
    if not text or len(text) < 3:
        continue
    if merged.get(text) == text:
        mark = "ЕСТЬ_ОБРАТНО" if text in u2r else "НЕТ_ОБРАТНО"
        lines.append(f"{mark} | {text}")

path = os.path.join(os.environ.get("TEMP", "."), "i18n_client_same.txt")
with open(path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines))
print(f"Строк без изменений: {len(lines)} -> {path}")
