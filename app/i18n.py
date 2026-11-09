# -*- coding: utf-8 -*-
"""Перевод сообщений сервера на два языка: русский и украинский.

Словарь лежит в app/i18n_dict.py и устроен просто: ключ - русский текст,
значение - украинский. Ключом может быть и шаблон с подстановками,
например "Машина с номером {plate} уже есть в базе".

Использование:
    from app.i18n import t
    t("Машина добавлена", lang)
    t("Машина с номером {plate} уже есть в базе", lang, plate="АА1234ВВ")

Запуск (проверка словаря):
    python -m app.i18n
"""

from app.i18n_dict import MESSAGES

# Русский - язык по умолчанию, украинский - второй.
DEFAULT_LANG = "ru"
LANGS = ("ru", "uk")

LANG_NAMES = {
    "ru": "Русский",
    "uk": "Українська",
}


def normalize_lang(value) -> str:
    """Привести значение к 'ru' или 'uk'; всё остальное - русский."""
    text = str(value or "").strip().lower()
    return text if text in LANGS else DEFAULT_LANG


def t(text: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Перевести текст на язык пользователя.

    text - русский текст или шаблон с подстановками ({plate} и т.п.).
    kwargs - значения подстановок; подставляются уже в перевод.
    """
    result = MESSAGES.get(text, text)
    if kwargs:
        try:
            result = result.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # Перевод не подошёл под подстановки - показываем русский текст.
            try:
                result = text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                pass
    return result


def main() -> int:
    """Проверить словарь переводов."""
    print(f"Строк в словаре: {len(MESSAGES)}")
    missing = [text for text, value in MESSAGES.items() if not value]
    if missing:
        print(f"Без перевода: {len(missing)}")
        for text in missing[:20]:
            print(f"  {text}")
        return 1
    print("Все строки переведены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
