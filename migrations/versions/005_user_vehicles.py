"""Migration 005: личный список машин пользователя.

Добавляет таблицу user_vehicles - аналог car_users старой системы.
В ней хранится, какие машины водитель добавил себе в список: одна фура
может быть в списках нескольких водителей, поэтому связь many-to-many.

Таблица создаётся только если её ещё нет - миграцию можно запускать
повторно, не ломая базу.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "005_user_vehicles"
down_revision = "004_user_lang"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    """Есть ли таблица в базе (проверка перед созданием)."""
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def upgrade() -> None:
    # --- user_vehicles: личный список машин ---
    if not _has_table("user_vehicles"):
        op.create_table(
            "user_vehicles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], name="fk_user_vehicles_user_id_users"
            ),
            sa.ForeignKeyConstraint(
                ["vehicle_id"],
                ["vehicles.id"],
                name="fk_user_vehicles_vehicle_id_vehicles",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_user_vehicles"),
            sa.UniqueConstraint(
                "user_id",
                "vehicle_id",
                name="uq_user_vehicles_user_vehicle",
            ),
        )


def downgrade() -> None:
    if _has_table("user_vehicles"):
        op.drop_table("user_vehicles")
