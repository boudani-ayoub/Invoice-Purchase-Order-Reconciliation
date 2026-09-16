"""Index the occurred-time window used by inventory intelligence."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_inventory_operations_intelligence_window",
        "inventory_operations",
        ["organization_id", "occurred_at", "operation_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_operations_intelligence_window",
        table_name="inventory_operations",
    )
