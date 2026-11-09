# -*- coding: utf-8 -*-
"""Собрать список русских строк интерфейса для перевода.

Запуск:
    python tools/extract_i18n.py

Результат:
    app/static/i18n_source.json - строки-кандидаты (по ним делается словарь)
"""

import json
import os
import re
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_FILES = [
    os.path.join(ROOT, "app", "static", "index.html"),
    os.path.join(ROOT, "app", "static", "new.html"),
]
JS_FILES = [os.path.join(ROOT, "app", "static", "js", "app.js")]

CYR = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")

# Строки, которые переводить не нужно:
#  - названия языков (в buttons и подсказках) остаются как есть;
#  - примеры данных (советы для полей) - это названия вымышленных фирм.
IGNORE = {
    "🇷🇺 Русский",
    "🇺🇦 Українська",
    "Выберите язык / Виберіть мову",
    "ТОВ Рома",
}


class TextCollector(HTMLParser):
    """Собрать видимый текст и подписи атрибутов из HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.texts = []
        self.attrs = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if value and CYR.search(value):
                self.attrs.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        text = " ".join(data.split())
        if text and CYR.search(text):
            self.texts.append(text)


TAG = re.compile(r"<[^>]*>")
ATTR = re.compile(r"""([a-zA-Z-]+)\s*=\s*["']([^"']*)["']""")
ATTR_NAMES = ("placeholder", "title", "aria-label")


def collect_template_parts(value: str) -> tuple[set[str], set[str]]:
    """Текст и подписи атрибутов из куска HTML-разметки.

    Из '<button aria-label="Удалить">Отмена</button>' получаем
    текст 'Отмена' и подпись 'Удалить'.
    """
    texts: set[str] = set()
    attrs: set[str] = set()
    plain = TAG.sub(" ", value)
    for piece in re.split(r"\s{2,}|\n", plain):
        piece = " ".join(piece.split()).strip("<>")
        if not piece or not CYR.search(piece):
            continue
        # Остатки недописанного тега - не текст для человека.
        if any(ch in piece for ch in "<=\""):
            continue
        # Одиночные буквы - это таблицы замен, не текст.
        if len(piece) < 2:
            continue
        texts.add(piece)
    for name, attr_value in ATTR.findall(value):
        if name in ATTR_NAMES and attr_value and CYR.search(attr_value):
            attrs.add(attr_value)
    return texts, attrs


def scan_template(source: str, index: int) -> tuple[list[str], int]:
    """Разобрать шаблонный литерал JS начиная с открывающей кавычки.

    Возвращает (статичные куски, позиция после закрывающей кавычки).
    Подстановки ${...} пропускаются, вложенные шаблоны разбираются рекурсивно.
    """
    parts: list[str] = []
    current: list[str] = []
    length = len(source)
    while index < length:
        char = source[index]
        if char == "\\":
            current.append(source[index : index + 2])
            index += 2
            continue
        if char == "`":
            index += 1
            break
        if source[index : index + 2] == "${":
            parts.append("".join(current))
            current = []
            index += 2
            depth = 1
            while index < length and depth:
                inner = source[index]
                if inner == "\\":
                    index += 2
                    continue
                if inner == "{":
                    depth += 1
                elif inner == "}":
                    depth -= 1
                elif inner == "`":
                    nested, index = scan_template(source, index + 1)
                    parts.extend(nested)
                elif inner in "\"'":
                    quote = inner
                    index += 1
                    while index < length and source[index] != quote:
                        if source[index] == "\\":
                            index += 1
                        index += 1
                index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts, index


def collect_template_literals(path: str) -> set[str]:
    """Статичные куски шаблонных литералов JS (строки в обратных кавычках).

    В шаблоне подставляются значения через ${...}, поэтому берём только
    текст между подстановками: 'порог уведомления: ${x} л' ->
    'порог уведомника:' и ' л'.
    """
    source = open(path, encoding="utf-8").read()
    result: set[str] = set()
    index = 0
    while index < len(source):
        if source[index] != "`":
            index += 1
            continue
        parts, index = scan_template(source, index + 1)
        for piece in parts:
            piece = piece.strip()
            if not piece or not CYR.search(piece):
                continue
            if "<" in piece or ">" in piece or '="' in piece:
                texts, attrs = collect_template_parts(piece)
                result |= texts | attrs
                continue
            if len(piece) >= 2 and not any(ch in piece for ch in "=<"):
                result.add(piece)
    return result


def collect_js_strings(path: str) -> tuple[set[str], list[str]]:
    """Строки-кандидаты из JS: простой текст и куски HTML-разметки.

    Возвращает (подходящие строки, отброшенные со спецсимволами).
    """
    source = open(path, encoding="utf-8").read()
    result: set[str] = set()
    dropped: list[str] = []
    for match in re.finditer(r'"([^"\n]*)"|\'([^\'\n]*)\'', source):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        if not value or len(value) > 200 or not CYR.search(value):
            continue
        if len(value.strip()) < 2:
            # Одиночные буквы - это таблицы замен (номера, раскладка), не текст.
            continue
        if "<" in value or ">" in value or '="' in value:
            # Разметка (возможно, кусок): берём видимый текст и подписи атрибутов.
            texts, attrs = collect_template_parts(value)
            result |= texts | attrs
            continue
        bad = [ch for ch in "<>{}`$" if ch in value]
        if chr(92) in value:
            bad.append(chr(92))
        if bad:
            dropped.append(f"{''.join(bad)} | {value[:120]}")
            continue
        if value.strip() != value:
            continue
        result.add(value)
    return result, dropped


def main() -> int:
    """Собрать строки и записать их в JSON."""
    candidates: set[str] = set()
    dropped: list[str] = []
    for path in HTML_FILES:
        collector = TextCollector()
        collector.feed(open(path, encoding="utf-8").read())
        candidates.update(collector.texts)
        candidates.update(collector.attrs)
    for path in JS_FILES + HTML_FILES:
        found, skipped = collect_js_strings(path)
        candidates.update(found)
        candidates.update(collect_template_literals(path))
        dropped.extend(f"{os.path.basename(path)}: {item}" for item in skipped)

    result = sorted(candidates - IGNORE)
    out_path = os.path.join(ROOT, "app", "static", "i18n_source.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)

    temp = os.environ.get("TEMP", ".")
    dump = os.path.join(temp, "i18n_candidates.txt")
    with open(dump, "w", encoding="utf-8") as handle:
        handle.write(f"Всего строк: {len(result)}\n\n")
        for item in result:
            handle.write(item + "\n")
    dump_dropped = os.path.join(temp, "i18n_dropped.txt")
    with open(dump_dropped, "w", encoding="utf-8") as handle:
        handle.write(f"Отброшено со спецсимволами: {len(dropped)}\n\n")
        for item in dropped:
            handle.write(item + "\n")
    print(f"Строк-кандидатов: {len(result)}")
    print(f"Список: {dump}")
    print(f"Отброшено: {dump_dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
