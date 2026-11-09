# -*- coding: utf-8 -*-
"""Импорт машин из архива Wialon (.wlp) в новую базу.

Архив с файлами *.wlp - это выгрузка объектов мониторинга из Wialon.
Внутри каждого файла - JSON, в котором есть имя объекта (`general.n`).
Имя объекта устроено как «номер + описание» или «марка + номер»:

    AB4840IM MAN-сідл.тягач
    MAN ВІ1055ІТ Маніпулятор
    RENAULT BI 2721IC
    VOLVO BI 0133 IH
    ВІ1033ІР цистерна-10м3, VOLVO

Из имени берём номер машины и марку (MAN, DAF, RENAULT, VOLVO). Модель
не уточняем - в названии объекта её нет.

Запуск:
    python -m app.import_wlp --zip "C:\\Downloads\\Объекты (1).zip"

Ключ: в новую баду скрипт идёт по DATABASE_URL (тот же, что у сервиса).
"""

import argparse
import json
import re
import sys
import zipfile

from app import create_app, db
from app.models import User, Vehicle
from app.legacy_plates import normalize_plate

# ---------- Правила разбора имени объекта ----------

# Кириллица -> латиница. В госномерах кириллическая Р означает
# латинскую P, У - Y, Х - X и так далее (украинские номера).
_CYR_TO_LAT = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Д": "D",
        "Е": "E",
        "Є": "E",
        "Ж": "ZH",
        "З": "Z",
        "И": "I",
        "І": "I",
        "Ї": "YI",
        "Й": "J",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "H",
        "О": "O",
        "П": "P",
        "Р": "P",
        "Т": "T",
        "У": "Y",
        "Ф": "F",
        "Х": "X",
        "Ц": "TS",
        "Ч": "CH",
        "Ш": "SH",
        "Щ": "SH",
        "Ъ": "",
        "Ь": "",
        "Ы": "Y",
        "Э": "E",
        "Ю": "YU",
        "Я": "YA",
        "Ґ": "G",
    }
)

# Марки в базе и как они могут быть написаны в имени объекта.
# Варианты кириллицей транслитерируются при загрузке модуля.
_BRAND_ALIASES = {
    "VOLVO": ("VOLVO", "ВОЛЬВО"),
    "DAF": ("DAF", "ДАФ"),
    "RENAULT": ("RENAULT", "RENAUT", "RENO", "РЕНО"),
    # "MAH" - это кириллическое «МАН» после перевода в латиницу (Н -> H).
    "MAN": ("MAN", "МАН"),
}

# Коды моделей тягачей MAN: в базе их записываем маркой MAN.
MAN_MODEL_CODES = ("TC40L", "TC45L")

# Слова-описания в имени объекта (тип кузова) - их отбрасываем.
_BODY_WORDS = ("СІДЛ", "ТЯГАЧ", "ЦИСТЕРНА", "МАНІПУЛЯТОР", "MANIPULATOR")

_TOKEN_RE = re.compile(r"[A-Z0-9]+")
_VOLUME_RE = re.compile(r"\d{0,3}\s*M3\b")


def _translit(text: str) -> str:
    """Кириллицу привести к латинице."""
    return (text or "").upper().translate(_CYR_TO_LAT)


# Варианты марок и слова-описания - в латинице, чтобы искать по одному виду.
BRAND_ALIASES = {
    brand: tuple(_translit(alias) for alias in aliases)
    for brand, aliases in _BRAND_ALIASES.items()
}
BODY_WORDS = tuple(_translit(word) for word in _BODY_WORDS)


def say(text: str) -> None:
    """Печать без падения на старой кодировке консоли (cp1251)."""
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe + "\n")


def plate_key(plate: str) -> str:
    """Ключ для сравнения номеров: латиница, верхний регистр, без пробелов."""
    return re.sub(r"[\s\-.]+", "", _translit(plate))


def detect_brand(name: str) -> tuple[str, str]:
    """Марка и её вариант из имени объекта. Пустая марка - не нашли."""
    upper = _translit(name)
    for brand, aliases in BRAND_ALIASES.items():
        for alias in aliases:
            if alias in upper:
                return brand, alias
    for code in MAN_MODEL_CODES:
        if code in upper:
            return "MAN", code
    return "", ""


def extract_plate(name: str) -> str:
    """Вытащить номер машины из имени объекта Wialon.

    Убираем слова-описания и марку, потом берём первый кусок с цифрами -
    это номер. К нему приклеиваем соседние короткие буквенные куски
    («BI 0133 IH» -> «BI0133IH»).
    """
    upper = _translit(name)
    upper = _VOLUME_RE.sub(" ", upper)
    for word in BODY_WORDS:
        upper = upper.replace(word, " ")

    brand, alias = detect_brand(upper)
    if alias:
        upper = upper.replace(alias, " ")
    upper = upper.replace("MAGNUM", " ")

    tokens = _TOKEN_RE.findall(upper)

    number_at = None
    for index, token in enumerate(tokens):
        if any(ch.isdigit() for ch in token):
            number_at = index
            break
    if number_at is None:
        return ""

    parts = [tokens[number_at]]
    # Короткий буквенный кусок перед номером - часть номера («BI 0133 IH»).
    if number_at > 0:
        previous = tokens[number_at - 1]
        if previous.isalpha() and 1 < len(previous) <= 3:
            parts.insert(0, previous)
    # Короткий буквенный кусок после номера - тоже часть номера.
    if number_at + 1 < len(tokens):
        following = tokens[number_at + 1]
        if following.isalpha() and 1 < len(following) <= 3:
            parts.append(following)
    return "".join(parts)


def parse_object(name: str) -> tuple[str, str]:
    """Номер и марка из имени объекта Wialon."""
    brand, _ = detect_brand(name)
    plate = extract_plate(name)
    return normalize_plate(plate), brand


# ---------- Импорт ----------


def read_objects(zip_path: str) -> list[dict]:
    """Прочитать объекты из архива .wlp."""
    objects: list[dict] = []
    with zipfile.ZipFile(zip_path, "r") as archive:
        for entry in archive.infolist():
            if not entry.filename.lower().endswith(".wlp"):
                continue
            raw = archive.read(entry.filename)
            data = None
            for encoding in ("utf-8", "cp1251"):
                try:
                    data = json.loads(raw.decode(encoding))
                    break
                except (UnicodeDecodeError, json.JSONDecodeError):
                    data = None
            if data is None:
                continue
            general = data.get("general", {}) or {}
            objects.append(
                {
                    "file": entry.filename,
                    "name": general.get("n") or entry.filename[:-4],
                    "uid": general.get("uid") or "",
                }
            )
    return objects


def _pick_user(user_id: int | None) -> User | None:
    """Пользователь-владелец импортированных машин (по умолчанию суперадмин)."""
    if user_id:
        user = User.query.filter_by(tg_id=user_id).first()
        if user:
            return user
        say(f"Пользователя с tg_id={user_id} нет в базе - создаю его")
        user = User(tg_id=user_id, level=3)
        db.session.add(user)
        db.session.flush()
        return user
    return User.query.order_by(User.level.desc(), User.id.asc()).first()


def import_wlp_vehicles(zip_path: str, user: User) -> dict:
    """Завести машины из архива .wlp. Уже имеющиеся номера пропускаются."""
    result = {"total": 0, "added": 0, "skipped": 0, "no_plate": 0, "no_brand": 0}
    existing = {plate_key(v.plate) for v in Vehicle.query.all()}

    for item in read_objects(zip_path):
        result["total"] += 1
        plate, brand = parse_object(item["name"])
        if not plate:
            result["no_plate"] += 1
            continue
        key = plate_key(plate)
        if key in existing:
            result["skipped"] += 1
            continue
        if not brand:
            result["no_brand"] += 1
        db.session.add(
            Vehicle(
                plate=plate,
                brand=brand,
                driver_id=user.id,
                current_mileage=0,
                status="active",
            )
        )
        existing.add(key)
        result["added"] += 1

    db.session.commit()
    return result


# ---------- Точка входа ----------


def main() -> int:
    """Импортировать машины из архива .wlp."""
    parser = argparse.ArgumentParser(description="Импорт машин из архива .wlp")
    parser.add_argument("--zip", required=True, help="путь к архиву с .wlp файлами")
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Telegram-номер владельца машин (по умолчанию - суперадмин)",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        user = _pick_user(args.user_id)
        if user is None:
            say("В базе нет ни одного пользователя - нечего импортировать")
            return 1

        say("Читаю архив...")
        result = import_wlp_vehicles(args.zip, user)
        say("Готово:")
        say(f"  объектов в архиве: {result['total']}")
        say(f"  добавлено машин:    {result['added']}")
        say(f"  уже были в базе:    {result['skipped']}")
        say(f"  без номера:         {result['no_plate']}")
        say(f"  без марки в имени:  {result['no_brand']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
