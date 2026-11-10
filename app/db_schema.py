# -*- coding: utf-8 -*-
"""Приведение схемы БД в порядок при старте приложения.

Зачем это нужно:
- на новой облачной базе таблиц ещё нет - их создают миграции alembic
  (вместе с таблицей alembic_version, без которой следующая миграция
  упадёт с ошибкой "таблица уже существует");
- если схему создал db.create_all() (например, локальная SQLite),
  alembic_version не появляется, и будущие миграции не пойдут.

Здесь одна функция: посмотреть, что с базой, и привести к порядку.
"""

import os
from pathlib import Path

from sqlalchemy import inspect


def _has_table(engine, name: str) -> bool:
    """Есть ли таблица в базе."""
    return name in inspect(engine).get_table_names()


def _run_alembic_upgrade(app) -> None:
    """Применить миграции alembic до последней версии."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    from app import db

    root = Path(__file__).resolve().parent.parent
    ini_path = root / "alembic.ini"
    if not ini_path.exists():
        # alembic.ini нет - тогда схему создаст create_all.
        db.create_all()
        return

    # Адрес берём у движка приложения: он уже разрешён (для SQLite
    # относительный путь превращается в путь внутри instance/).
    # Через переменную окружения, а не через ini - так пароль с
    # спецсимволами не ломает разбор ini-файла.
    url = db.engine.url.render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = url

    config = AlembicConfig(str(ini_path))
    config.set_main_option("script_location", str(root / "migrations"))

    command.upgrade(config, "head")


def ensure_schema(app) -> None:
    """Привести схему БД к актуальному состоянию.

    Порядок такой:
    1. есть таблица alembic_version - доводим миграции до текущей версии;
    2. таблиц нет вообще - применяем миграции с нуля;
    3. таблицы есть, но alembic_version нет - схему создал create_all
       (локальная база). Добираем недостающее, историю alembic не
       восстановить, но и базу ломать не надо.

    Если миграции не прошли - приложение всё равно должно подняться,
    поэтому падаем на db.create_all() и продолжаем работу.
    """
    from app import db

    engine = db.engine

    if _has_table(engine, "alembic_version"):
        _upgrade_or_fallback(app)
        return

    if _has_table(engine, "users"):
        db.create_all()
        _add_missing_columns()
        return

    _upgrade_or_fallback(app)


def _default_sql(default) -> str:
    """Значение по умолчанию для ALTER TABLE ADD COLUMN."""
    if isinstance(default, bool):
        return "1" if default else "0"
    if isinstance(default, (int, float)):
        return str(default)
    text_value = str(default)
    if text_value.startswith("'") and text_value.endswith("'"):
        return text_value
    return f"'{text_value}'"


def _add_missing_columns() -> None:
    """Дописать колонки, которых нет в таблицах.

    Нужно для баз, созданных через db.create_all(): у них нет истории
    alembic, поэтому миграции к ним не применяются, а новых колонок
    (например, статуса проверки) в таблицах не появляется.
    """
    from sqlalchemy import text

    from app import db

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    dialect = db.engine.dialect

    for table in db.metadata.sorted_tables:
        if table.name not in tables:
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = column.type.compile(dialect=dialect)
            default = column.server_default
            if default is None:
                default = column.default
            if not column.nullable:
                # NOT NULL без значения по умолчанию добавить нельзя.
                if default is None:
                    continue
                ddl += " DEFAULT " + _default_sql(default.arg if hasattr(default, "arg") else default)
            db.session.execute(
                text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl}')
            )
    db.session.commit()


def _upgrade_or_fallback(app) -> None:
    """Применить миграции; если не вышло - создать таблицы по моделям."""
    from app import db

    try:
        _run_alembic_upgrade(app)
    except Exception as exc:
        print(f"⚠️ Миграции не применились ({exc}). Создаю таблицы по моделям.")
        db.create_all()
        _add_missing_columns()
