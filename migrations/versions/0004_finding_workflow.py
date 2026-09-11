"""Versioned finding workflow and immutable tenant-owned event history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

WORKFLOW_COLUMNS = (
    "status",
    "assignee_user_id",
    "due_at",
    "reminder_at",
    "resolved_at",
    "resolved_by_user_id",
    "resolution_note",
    "version",
)


def upgrade() -> None:
    # The validated resolution constraint rejects out-of-band legacy resolutions without actors.
    op.drop_constraint(op.f("ck_findings_findingstatus"), "findings", type_="check")
    op.alter_column("findings", "status", type_=sa.String(9), existing_type=sa.String(8))
    op.create_check_constraint(
        op.f("ck_findings_findingstatus"), "findings", "status IN ('OPEN', 'IN_REVIEW', 'RESOLVED')"
    )
    for name in ("assignee_user_id", "resolved_by_user_id"):
        op.add_column("findings", sa.Column(name, sa.Uuid(), nullable=True))
    for name in ("due_at", "reminder_at", "resolved_at"):
        op.add_column("findings", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("findings", sa.Column("resolution_note", sa.Text(), nullable=True))
    op.add_column(
        "findings", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    for name, column in (("assignee", "assignee_user_id"), ("resolver", "resolved_by_user_id")):
        op.create_foreign_key(
            f"fk_findings_{name}_membership",
            "findings",
            "organization_memberships",
            ["organization_id", column],
            ["organization_id", "user_id"],
            ondelete="RESTRICT",
        )
    for name, expression in {
        "version_positive": "version > 0",
        "resolution_note_length": (
            "resolution_note IS NULL OR (length(btrim(resolution_note)) BETWEEN 1 AND 4000)"
        ),
        "resolution_state": (
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL "
            "AND resolution_note IS NOT NULL) OR (status <> 'RESOLVED' AND resolved_at IS NULL "
            "AND resolved_by_user_id IS NULL AND resolution_note IS NULL)"
        ),
    }.items():
        op.create_check_constraint(op.f(f"ck_findings_{name}"), "findings", expression)
    for name, columns in {
        "queue": ["organization_id", "status", "assignee_user_id", "due_at"],
        "reminders": ["organization_id", "reminder_at"],
        "chronology": ["organization_id", "created_at", "id"],
    }.items():
        op.create_index(f"ix_findings_{name}", "findings", columns)
    op.create_table(
        "finding_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "COMMENT_ADDED",
                "ASSIGNEE_CHANGED",
                "DUE_DATE_CHANGED",
                "REMINDER_CHANGED",
                "STATUS_CHANGED",
                "RESOLVED",
                "REOPENED",
                name="findingeventtype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "finding_id"],
            ["findings.organization_id", "findings.id"],
            name="fk_finding_id_findings_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 2048",
            name="metadata_bound",
        ),
        sa.CheckConstraint(
            "message IS NULL OR length(btrim(message)) BETWEEN 1 AND 4000", name="message_length"
        ),
        sa.CheckConstraint(
            "(event_type IN ('COMMENT_ADDED', 'RESOLVED') AND message IS NOT NULL) OR "
            "(event_type NOT IN ('COMMENT_ADDED', 'RESOLVED') AND message IS NULL)",
            name="message_type",
        ),
    )
    op.create_index(
        "ix_finding_events_history",
        "finding_events",
        ["organization_id", "finding_id", "created_at", "id"],
    )
    op.execute("ALTER TABLE finding_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finding_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON finding_events TO reconcile_runtime "
        "USING (organization_id = "
        "NULLIF(current_setting('app.current_organization_id', true), '')::uuid) "
        "WITH CHECK (organization_id = "
        "NULLIF(current_setting('app.current_organization_id', true), '')::uuid)"
    )
    op.execute("GRANT SELECT, INSERT ON finding_events TO reconcile_runtime")
    op.execute(f"GRANT UPDATE ({', '.join(WORKFLOW_COLUMNS)}) ON findings TO reconcile_runtime")
    op.execute("""
        CREATE FUNCTION protect_finding_event() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        BEGIN RAISE EXCEPTION 'Finding events are immutable'; END $body$;
    """)
    op.execute(
        "CREATE TRIGGER protect_finding_event BEFORE UPDATE OR DELETE ON finding_events "
        "FOR EACH ROW EXECUTE FUNCTION protect_finding_event()"
    )


def downgrade() -> None:
    # Downgrade would erase persisted business comments and resolution history.
    raise RuntimeError(
        "Workflow history cannot be discarded by downgrade. Restore a reviewed backup."
    )
