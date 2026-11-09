# -*- coding: utf-8 -*-
"""Подготовить батчи строк для перевода на украинский.

Запуск:
    python tools/build_translation_batches.py

Результат:
    tools/i18n_all_ru.json     - все уникальные русские строки
    tools/i18n_batch_N.json    - части для перевода
    tools/i18n_uk_source.json  - украинские строки (для обратного словаря)
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

# Односимвольные заглушки и служебные символы - переводить нечего.
DROP_EXACT = set("АВЕКМНОРСТУХІаегниыэєіїґ")

# Тестовые данные (примеры имён и клиентов) - это данные, не интерфейс.
DROP_PREFIXES = (
    "Іван Петренко",
    "Петро Іванов",
    "Олексій Ковальчук",
    "Мікола Шевчук",
    "Клієнт ",
    "Водій ",
    "Підприємство ",
    "ТОВ Рома",
    "ФОП Іванов",
)


def load(path: str):
    """Прочитать JSON-файл."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    """Собрать батчи."""
    client = load(os.path.join(ROOT, "app", "static", "i18n_source.json"))
    server = load(os.path.join(TOOLS, "i18n_server_ru.json"))

    all_ru = set(client) | set(server.keys())

    # Убираем мусор: одиночные буквы и тестовые данные.
    clean = set()
    for item in all_ru:
        if item in DROP_EXACT:
            continue
        if len(item) < 2:
            continue
        if any(item.startswith(prefix) for prefix in DROP_PREFIXES):
            continue
        clean.add(item)

    ru_list = sorted(clean)
    with open(os.path.join(TOOLS, "i18n_all_ru.json"), "w", encoding="utf-8") as handle:
        json.dump(ru_list, handle, ensure_ascii=False, indent=1)

    # Украинские строки - для обратного словаря (uk -> ru).
    uk_markers = ("і", "ї", "є", "ґ")
    uk_list = []
    for item in ru_list:
        low = item.lower()
        if any(mark in low for mark in uk_markers):
            uk_list.append(item)
    with open(os.path.join(TOOLS, "i18n_uk_source.json"), "w", encoding="utf-8") as handle:
        json.dump(uk_list, handle, ensure_ascii=False, indent=1)

    # Делим на 4 части.
    size = (len(ru_list) + 3) // 4
    for number in range(4):
        part = ru_list[number * size : (number + 1) * size]
        path = os.path.join(TOOLS, f"i18n_batch_{number + 1}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(part, handle, ensure_ascii=False, indent=1)
        print(f"Батч {number + 1}: {len(part)} строк -> {path}")

    print(f"Всего строк: {len(ru_list)}, украинских из них: {len(uk_list)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
