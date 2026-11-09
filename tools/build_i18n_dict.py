# -*- coding: utf-8 -*-
"""Сгенерировать app/i18n_dict.py из tools/i18n_dict.json.

Словарь хранится в одном месте (JSON), оттуда делаются две копии:
  - app/i18n_dict.py - для сервера (бот, сообщения API);
  - app/static/i18n_dict.js - для браузера (Mini App).

Запуск:
    python tools/build_i18n_dict.py
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

PY_HEADER = '''# -*- coding: utf-8 -*-
"""Словарь переводов сервера: русский -> украинский.

Файл создаётся скриптом tools/build_i18n_dict.py из tools/i18n_dict.json.
Правь словарь там, потом запускай скрипт снова.
"""

MESSAGES = {
'''

JS_HEADER = """// Словарь переводов Mini App: русский -> украинский.
// Файл создаётся скриптом tools/build_i18n_dict.py из tools/i18n_dict.json.
// Правь словарь там, потом запускай скрипт снова.
window.CT_DICT = {
"""

JS_FRAG_HEADER = """
// Куски строк, которые в интерфейсе идут вместе со значением.
// Их переводим внутри длинной строки: "Заправок: 12" -> "Заправок: 12".
window.CT_FRAG = [
"""


def escape_python(value: str) -> str:
    """Подготовить строку для записи в Python-словарь."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def escape_js(value: str) -> str:
    """Подготовить строку для записи в JS-объект."""
    return json.dumps(value, ensure_ascii=False)


def main() -> int:
    """Записать оба файла словаря."""
    with open(os.path.join(TOOLS, "i18n_dict.json"), encoding="utf-8") as handle:
        messages = json.load(handle)

    lines = [PY_HEADER]
    for ru in sorted(messages):
        lines.append(f'    "{escape_python(ru)}": "{escape_python(messages[ru])}",\n')
    lines.append("}\n")
    py_path = os.path.join(ROOT, "app", "i18n_dict.py")
    with open(py_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(lines))

    lines = [JS_HEADER]
    for ru in sorted(messages):
        lines.append(f"  {escape_js(ru)}: {escape_js(messages[ru])},\n")
    lines.append("};\n")

    # Подписи, которые встречаются внутри длинных строк.
    fragments = []
    frag_path = os.path.join(TOOLS, "i18n_fragments.json")
    if os.path.exists(frag_path):
        with open(frag_path, encoding="utf-8") as handle:
            fragments = json.load(handle)
    lines.append(JS_FRAG_HEADER)
    for item in fragments:
        lines.append(f"  {escape_js(item)},\n")
    lines.append("];\n")

    js_path = os.path.join(ROOT, "app", "static", "i18n_dict.js")
    with open(js_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(lines))

    missing = [item for item in fragments if item not in messages]
    print(f"Записано: {py_path}")
    print(f"Записано: {js_path}")
    print(f"Строк: {len(messages)}; фрагментов: {len(fragments)}")
    if missing:
        print(f"Фрагментов без перевода: {len(missing)}")
        for item in missing:
            print(f"  | {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
