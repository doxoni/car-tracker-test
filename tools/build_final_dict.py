# -*- coding: utf-8 -*-
"""Собрать финальный словарь русский -> украинский.

Берёт строки из актуальных исходников и находит для каждой перевод.
Источники переводов:
  - i18n_merged_uk.json - переводы, сделанные агентами;
  - i18n_uk_to_ru.json и i18n_uk_to_ru_extra.json - обратные пары
    (исходники были украинскими, теперь стали русскими);
  - i18n_manual.json - переводы, которые дописаны вручную.

Запуск:
    python tools/build_final_dict.py
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")


def load(name, folder=TOOLS):
    """Загрузить JSON-файл."""
    path = name if os.path.isabs(name) else os.path.join(folder, name)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    """Собрать словарь и показать, чего не хватает."""
    merged = load("i18n_merged_uk.json")
    uk_to_ru = load("i18n_uk_to_ru.json")
    uk_to_ru_extra = load("i18n_uk_to_ru_extra.json")
    manual = load("i18n_manual.json")

    dictionary = {}

    # 1. Переводы агентов: берём ключи, которые ещё есть в исходниках.
    client = load("i18n_source.json", os.path.join(ROOT, "app", "static"))
    server = load("i18n_server_ru.json")
    source_strings = set(client) | set(server)

    for ru, uk in merged.items():
        if ru in source_strings:
            dictionary[ru] = uk

    # 2. Обратные пары: украинский исходник -> русский -> украинский.
    for uk, ru in list(uk_to_ru.items()) + list(uk_to_ru_extra.items()):
        if uk == ru:
            continue
        if ru in source_strings:
            dictionary[ru] = uk

    # 3. Переводы вручную.
    dictionary.update(manual)

    with open(os.path.join(TOOLS, "i18n_dict.json"), "w", encoding="utf-8") as handle:
        json.dump(dictionary, handle, ensure_ascii=False, indent=1, sort_keys=True)

    missing = sorted(text for text in source_strings if text not in dictionary)

    lines = [f"В словаре: {len(dictionary)}", f"Без перевода: {len(missing)}"]
    for text in missing:
        lines.append(f"  | {text}")
    out = os.path.join(os.environ.get("TEMP", "."), "i18n_missing.txt")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    print(f"В словаре: {len(dictionary)}")
    print(f"Без перевода: {len(missing)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
