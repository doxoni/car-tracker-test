"""Migration 004: язык пользователя.

Добавляет в таблицу users колонку lang - язык интерфейса (ru или uk).
Значение NULL означает "язык ещё не выбран" - при первом входе показываем
выбор языка. Старые строки остаются рабочими как есть.

Колонка добавляется только если её ещё нет - миграцию можно запускать
повторно, не ломая базу.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004_user_lang"
down_revision = "003_legacy_entities"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Есть ли колонка в таблице (проверка перед ALTER TABLE)."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    # --- users.lang: язык интерфейса ---
    if not _has_column("users", "lang"):
        op.add_column(
            "users",
            sa.Column(
                "lang",
                sa.String(2),
                nullable=True,
            ),
        )


def downgrade() -> None:
    if _has_column("users", "lang"):
        op.drop_column("users", "lang")
