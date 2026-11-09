# -*- coding: utf-8 -*-
"""Тесты импорта машин из архива Wialon (.wlp)."""

import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.import_wlp import (  # noqa: E402
    extract_plate,
    parse_object,
    plate_key,
    read_objects,
)
from app.legacy_plates import normalize_plate  # noqa: E402


def _make_zip(tmp_path, objects):
    """Собрать архив .wlp с указанными именами объектов."""
    path = tmp_path / "objects.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index, name in enumerate(objects):
            payload = json.dumps(
                {"type": "avl_unit", "general": {"n": name, "uid": f"86000000000{index:04d}"}},
                ensure_ascii=False,
            )
            archive.writestr(f"{index}.wlp", payload.encode("utf-8"))
    return str(path)


@pytest.mark.parametrize(
    "name, expected_plate",
    [
        ("AB4840IM MAN-сідл.тягач", "АВ4840ІМ"),
        ("BI0587HP DAF-сідл.тягач", "ВІ0587НР"),
        ("BI1033IT Сідл.тягач-MAN", "ВІ1033ІТ"),
        ("DAF BI9087НМ", "ВІ9087НМ"),
        ("MAN AB2598IM", "АВ2598ІМ"),
        ("RENAULT BI 2721IC", "ВІ2721ІС"),
        ("Reno Magnum BI6349CP", "ВІ6349СР"),
        ("VOLVO BI 0133 IH", "ВІ0133ІН"),
        ("VOLVO BI 9593BK", "ВІ9593ВК"),
        ("ВІ1033ІР цистерна-10м3, VOLVO", "ВІ1033ІР"),
        ("МАН КА2360РМ", "КА2360РМ"),
        ("СА5772НР", "СА5772НР"),
    ],
)
def test_extract_plate(name, expected_plate):
    """Номер вытаскивается из имени объекта."""
    assert normalize_plate(extract_plate(name)) == expected_plate


@pytest.mark.parametrize(
    "name, expected_brand",
    [
        ("AB4840IM MAN-сідл.тягач", "MAN"),
        ("BI0587HP DAF-сідл.тягач", "DAF"),
        ("RENAULT BI 2721IC", "RENAULT"),
        ("Reno Magnum BI6349CP", "RENAULT"),
        ("VOLVO BI 9593BK", "VOLVO"),
        ("TC45L 04724TKA", "MAN"),
        ("МАН ВІ0581НС", "MAN"),
        ("ДАФ ВІ9773НА", "DAF"),
    ],
)
def test_detect_brand(name, expected_brand):
    """Марка определяется по названию, модель не уточняется."""
    _, brand = parse_object(name)
    assert brand == expected_brand


def test_plate_key_ignores_cyrillic_and_spaces():
    """Кириллица и латиница - один и тот же номер."""
    assert plate_key("ВІ0133ІН") == plate_key("BI 0133 IH")


def test_read_objects(tmp_path):
    """Из архива читаются имена объектов."""
    path = _make_zip(tmp_path, ["MAN AB2598IM", "DAF BI9087НМ"])
    objects = read_objects(path)
    assert len(objects) == 2
    assert objects[0]["name"] == "MAN AB2598IM"
    assert objects[1]["name"] == "DAF BI9087НМ"


def test_import_skips_existing_and_adds_new(tmp_path):
    """Импорт не плодит дубли: уже имеющийся номер пропускается."""
    from app import create_app, db
    from app.models import User, Vehicle
    from app.import_wlp import import_wlp_vehicles

    app = create_app()
    with app.app_context():
        user = User.query.order_by(User.level.desc(), User.id.asc()).first()
        if user is None:
            user = User(tg_id=999999, level=3)
            db.session.add(user)
            db.session.commit()

        first = _make_zip(tmp_path, ["MAN AB2598IM"])
        result = import_wlp_vehicles(first, user)
        assert result["added"] == 1
        assert result["skipped"] == 0

        second = _make_zip(tmp_path, ["MAN AB2598IM", "DAF BI9087НМ"])
        result = import_wlp_vehicles(second, user)
        assert result["added"] == 1
        assert result["skipped"] == 1

        # Номер в латинице не плодит дубль кириллического.
        third = _make_zip(tmp_path, ["MAN AB 2598 IM"])
        result = import_wlp_vehicles(third, user)
        assert result["added"] == 0
        assert result["skipped"] == 1
