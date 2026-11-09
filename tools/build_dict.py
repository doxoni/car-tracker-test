# -*- coding: utf-8 -*-
"""Собрать финальный словарь переводов и отчёт о покрытии.

Берёт слитые переводы RU->UK, добавляет обратные пары из украинских
исходников, чинит известные ошибки и дополняет словарь фрагментами
(составные подписи вроде "Заправки:").

Запуск:
    python tools/build_dict.py
"""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

# ---------- Исправления известных ошибок перевода ----------
FIXES = {
    "Март": "Березень",
    "Май": "Травень",
    "Ноябрь": "Листопад",
    "В бочке: —": "В бочці: —",
    "В бочке: …": "В бочці: …",
    "Загрузка…": "Завантаження…",
    "Загружаю…": "Завантажую…",
    "Сохранено": "Збережено",
    "Пробег": "Пробіг",
    "за всё время": "за весь час",
    "Добавить": "Додати",
    "Удалить": "Видалити",
    "Сохранить": "Зберегти",
    "Отмена": "Скасувати",
}

# ---------- Фрагменты составных подписей ----------
# Ключ - как в исходнике, значение - украинский перевод.
FRAGMENTS = {
    ", одометр": ", одометр",
    "· Заправки:": "· Заправки:",
    "· Обслуживание:": "· Обслуговування:",
    "· полный бак": "· повний бак",
    "· следующее до": "· наступне до",
    "· следующее через": "· наступне через",
    "· частично": "· частково",
    "В бочке:": "В бочці:",
    "В бочке: минус": "В бочці: мінус",
    "Всего машин:": "Всього машин:",
    "Записано, но не выложено:": "Записано, але не викладено:",
    "Машина:": "Машина:",
    "Не удалось удалить:": "Не вдалося видалити:",
    "Общие расходы:": "Загальні витрати:",
    "Ошибка сети:": "Помилка мережі:",
    "Ошибка:": "Помилка:",
    "Пробег:": "Пробіг:",
    "л · из бочки (": "л · з бочки (",
    "минус": "мінус",
    "осталось": "залишилося",
    "ошибка": "помилка",
    "раз(ов),": "раз(ів),",
    "ушла в минус:": "увійшла в мінус:",
    "номер": "номер",
    "до": "до",
    "через": "через",
    "грн": "грн",
}

# Строки-шаблоны сервера: подставляется номер машины.
TEMPLATES = {
    "Машина с номером {plate} уже есть в базе": "Машина з номером {plate} вже є в базі",
    "Номер {plate} уже занят другой машиной": "Номер {plate} вже зайнятий іншою машиною",
}

CYR = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")


def load(name):
    """Загрузить JSON-файл из папки tools."""
    with open(os.path.join(TOOLS, name), encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    """Собрать словарь и записать отчёт."""
    merged = load("i18n_merged_uk.json")
    uk_to_ru = load("i18n_uk_to_ru.json")

    dictionary = dict(merged)
    dictionary.update(FIXES)

    # Украинские исходники -> русские: обратная пара даёт русский ключ.
    for uk, ru in uk_to_ru.items():
        if uk == ru:
            continue
        dictionary[ru] = uk

    dictionary.update(FRAGMENTS)
    dictionary.update(TEMPLATES)

    with open(os.path.join(TOOLS, "i18n_dict.json"), "w", encoding="utf-8") as handle:
        json.dump(dictionary, handle, ensure_ascii=False, indent=1, sort_keys=True)

    # ---------- Отчёт о покрытии ----------
    client = json.load(
        open(os.path.join(ROOT, "app", "static", "i18n_source.json"), encoding="utf-8")
    )
    server = load("i18n_server_ru.json")

    missing_client = [s for s in client if s and s not in dictionary]
    missing_server = [s for s in server if s and s not in dictionary]

    report = []
    report.append(f"В словаре ключей: {len(dictionary)}")
    report.append(f"Не переведено в клиенте: {len(missing_client)}")
    for item in missing_client:
        report.append(f"  CLIENT | {item}")
    report.append(f"Не переведено на сервере: {len(missing_server)}")
    for item in missing_server:
        report.append(f"  SERVER | {item}")

    path = os.path.join(os.environ.get("TEMP", "."), "i18n_dict_report.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(report))

    print(f"Слов в словаре: {len(dictionary)}")
    print(f"Отчёт: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
