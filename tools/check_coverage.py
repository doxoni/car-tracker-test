# -*- coding: utf-8 -*-
"""Проверка: все ли строки интерфейса есть в словаре переводов.

Берём список кандидатов из app/static/i18n_source.json (его собирает
tools/extract_i18n.py) и проверяем, что для каждой строки есть перевод
в словаре или она покрывается куском строки (tools/i18n_fragments.json).

Запуск: python tools/check_coverage.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(name, base=ROOT):
    path = os.path.join(base, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    """Показать строки, для которых нет перевода."""
    messages = load_json(os.path.join("tools", "i18n_dict.json"))
    fragments = load_json(os.path.join("tools", "i18n_fragments.json")) or []
    candidates = load_json(os.path.join("app", "static", "i18n_source.json")) or []

    missing = []
    for text in candidates:
        if text in messages:
            continue
        if any(frag in text for frag in fragments):
            continue
        missing.append(text)

    out = sys.stdout
    try:
        out.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    for text in missing:
        print("НЕТ ПЕРЕВОДА:", repr(text))
    print(f"строк-кандидатов: {len(candidates)}")
    print(f"ключей в словаре: {len(messages)}, кусков: {len(fragments)}")
    print(f"без перевода: {len(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
