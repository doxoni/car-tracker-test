"""Migration 006: проверка заправок и обслуживания третьим уровнем.

В таблицы fuel_entries и service_entries добавляются поля такой же
схемы одобрения, какая уже есть у расходов (expenses):

- status — pending | approved | rejected;
- submitted_by — кто прислал запись;
- approved_by — кто принял или отклонил;
- approved_at — когда приняли или отклонили.

Старые записи остаются подтверждёнными (server_default="approved"),
поэтому уже накопленная история не требует ручной правки.

Колонки добавляются по одной и только если их ещё нет - миграцию
можно запускать повторно, не ломая базу.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006_entry_review"
down_revision = "005_user_vehicles"
branch_labels = None
depends_on = None


# Таблицы, куда добавляем поля одобрения.
REVIEW_TABLES = ("fuel_entries", "service_entries")


def _has_column(table: str, column: str) -> bool:
    """Есть ли колонка в таблице (проверка перед добавлением)."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    names = {col["name"] for col in inspector.get_columns(table)}
    return column in names


def _add_review_columns(table: str) -> None:
    """Добавить поля одобрения в таблицу заправок или обслуживания."""
    columns = []
    if not _has_column(table, "status"):
        columns.append(
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="approved",
            )
        )
    if not _has_column(table, "submitted_by"):
        columns.append(
            sa.Column(
                "submitted_by",
                sa.Integer(),
                sa.ForeignKey("users.id", name=f"fk_{table}_submitted_by"),
                nullable=True,
            )
        )
    if not _has_column(table, "approved_by"):
        columns.append(
            sa.Column(
                "approved_by",
                sa.Integer(),
                sa.ForeignKey("users.id", name=f"fk_{table}_approved_by"),
                nullable=True,
            )
        )
    if not _has_column(table, "approved_at"):
        columns.append(sa.Column("approved_at", sa.DateTime(), nullable=True))

    if not columns:
        return

    # batch_alter_table на PostgreSQL делает обычный ALTER, а на SQLite
    # пересоздаёт таблицу. Ограничения называем явно - безымянные при
    # пересоздании теряются.
    with op.batch_alter_table(table) as batch_op:
        for column in columns:
            batch_op.add_column(column)


def upgrade() -> None:
    for table in REVIEW_TABLES:
        _add_review_columns(table)


def downgrade() -> None:
    for table in reversed(REVIEW_TABLES):
        with op.batch_alter_table(table) as batch_op:
            for column in ("approved_at", "approved_by", "submitted_by", "status"):
                if _has_column(table, column):
                    batch_op.drop_column(column)
