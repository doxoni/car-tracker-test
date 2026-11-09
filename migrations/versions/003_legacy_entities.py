"""Migration 003: сущности старой системы учёта.

Добавляет таблицы, которых не было в новой схеме, но которые нужны
старому интерфейсу: drivers (водители по имени), customers (клиенты),
fuel_entries (заправки по фурам), service_entries (ТО по фурам),
reports (акты). Также связывает фуру с водителем по имени.

Все ограничения названы: batch_alter_table пересоздаёт таблицу на SQLite
и безымянные ограничения туда не переносит.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003_legacy_entities"
down_revision = "002_admin_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- drivers: водители по имени ---
    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_drivers_user_id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # --- customers: клиенты (заказчики) ---
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # --- fuel_entries: заправки фур ---
    op.create_table(
        "fuel_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id", name="fk_fuel_entries_vehicle_id"),
            nullable=False,
        ),
        sa.Column("liters", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("odometer", sa.Integer(), nullable=True),
        sa.Column("is_full", sa.Boolean(), nullable=True),
        sa.Column("location", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # --- service_entries: техническое обслуживание ---
    op.create_table(
        "service_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id", name="fk_service_entries_vehicle_id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("odometer", sa.Integer(), nullable=True),
        sa.Column("next_km", sa.Integer(), nullable=True),
        sa.Column("next_date", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # --- reports: акты по фурам ---
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id", name="fk_reports_vehicle_id"),
            nullable=True,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", name="fk_reports_customer_id"),
            nullable=True,
        ),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("drivers.id", name="fk_reports_driver_id"),
            nullable=True,
        ),
        sa.Column("client", sa.String(120), nullable=True),
        sa.Column("driver", sa.String(120), nullable=True),
        sa.Column("mileage", sa.Integer(), nullable=True),
        sa.Column("paid", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # --- vehicles: привязка к водителю по имени ---
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.add_column(sa.Column("assigned_driver_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_vehicles_assigned_driver_id",
            "drivers",
            ["assigned_driver_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.drop_constraint("fk_vehicles_assigned_driver_id", type_="foreignkey")
        batch_op.drop_column("assigned_driver_id")

    op.drop_table("reports")
    op.drop_table("service_entries")
    op.drop_table("fuel_entries")
    op.drop_table("customers")
    op.drop_table("drivers")
