"""Migration 002: трёхуровневая админ-система.

Заменяет role (String) на level (Integer: 1, 2, 3) в таблице users.
Добавляет статус одобрения расходов и таблицу аудит-лога audit_logs.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "002_admin_levels"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users: добавить level, заполнить, удалить role ---
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("level", sa.Integer(), nullable=False, server_default="1"))

    # Заполнить level на основе существующих ролей
    op.execute("UPDATE users SET level = 3 WHERE role = 'admin'")
    op.execute("UPDATE users SET level = 1 WHERE role != 'admin' OR role IS NULL")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("role")

    # --- expenses: добавить поля одобрения ---
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
        batch_op.add_column(sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))

    # --- audit_logs: создать таблицу ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("old_values", sa.Text(), nullable=True),
        sa.Column("new_values", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_column("approved_at")
        batch_op.drop_column("approved_by")
        batch_op.drop_column("submitted_by")
        batch_op.drop_column("status")

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(20), nullable=False, server_default="driver"))

    op.execute("UPDATE users SET role = 'admin' WHERE level = 3")
    op.execute("UPDATE users SET role = 'driver' WHERE level != 3 OR level IS NULL")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("level")