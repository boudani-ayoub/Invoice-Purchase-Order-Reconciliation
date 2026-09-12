"""Support tenant-scoped period activity reads without scanning comment history."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_finding_events_activity",
        "finding_events",
        ["organization_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_finding_events_activity", table_name="finding_events")
