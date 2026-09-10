"""Run metadata, keyset history, and append-only actor evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("analysis_runs", sa.Column("note", sa.Text(), nullable=True))
    op.add_column(
        "analysis_runs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "analysis_runs", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    for name, expression in {
        "version_positive": "version > 0",
        "title_length": "title IS NULL OR length(title) <= 120",
        "note_length": "note IS NULL OR length(note) <= 4000",
        "archive_time": "archived_at IS NULL OR archived_at >= created_at",
    }.items():
        op.create_check_constraint(op.f(f"ck_analysis_runs_{name}"), "analysis_runs", expression)
    op.create_index(
        "ix_analysis_runs_history",
        "analysis_runs",
        ["organization_id", "archived_at", "created_at", "id"],
    )
    op.create_index(
        "ix_analysis_runs_mode_history",
        "analysis_runs",
        ["organization_id", "analysis_mode", "archived_at", "created_at", "id"],
    )
    op.create_table(
        "audit_events",
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
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "ANALYSIS_COMPLETED",
                "RUN_METADATA_UPDATED",
                "RUN_ARCHIVED",
                "RUN_RESTORED",
                name="auditeventtype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("resource_type", sa.Text(), nullable=False, server_default="ANALYSIS_RUN"),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "resource_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
            name="fk_resource_id_analysis_runs_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("resource_type = 'ANALYSIS_RUN'", name="resource_type"),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 2048",
            name="metadata_bound",
        ),
    )
    op.create_index(
        "ix_audit_events_resource", "audit_events", ["organization_id", "resource_id", "created_at"]
    )
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_events TO reconcile_runtime "
        "USING (organization_id = "
        "NULLIF(current_setting('app.current_organization_id', true), '')::uuid) "
        "WITH CHECK (organization_id = "
        "NULLIF(current_setting('app.current_organization_id', true), '')::uuid)"
    )
    op.execute("GRANT SELECT, INSERT ON audit_events TO reconcile_runtime")
    op.execute(
        "REVOKE UPDATE ON source_files, purchase_orders, purchase_order_lines, "
        "goods_receipts, goods_receipt_lines, invoices, invoice_lines, analysis_sources, findings "
        "FROM reconcile_runtime"
    )
    op.execute("REVOKE UPDATE ON analysis_runs FROM reconcile_runtime")
    op.execute(
        "GRANT UPDATE (title, note, archived_at, version) ON analysis_runs TO reconcile_runtime"
    )
    op.execute("""
        CREATE FUNCTION protect_audit_event() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        BEGIN RAISE EXCEPTION 'Audit events are immutable'; END $body$;
    """)
    op.execute(
        "CREATE TRIGGER protect_audit_event BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION protect_audit_event()"
    )


def downgrade() -> None:
    op.execute(
        "GRANT UPDATE ON source_files, purchase_orders, purchase_order_lines, "
        "goods_receipts, goods_receipt_lines, invoices, invoice_lines, analysis_sources, findings "
        "TO reconcile_runtime"
    )
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION protect_audit_event()")
    op.execute(
        "REVOKE UPDATE (title, note, archived_at, version) ON analysis_runs FROM reconcile_runtime"
    )
    op.execute("GRANT UPDATE ON analysis_runs TO reconcile_runtime")
    op.drop_index("ix_analysis_runs_mode_history", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_history", table_name="analysis_runs")
    for name in ("version_positive", "title_length", "note_length", "archive_time"):
        op.drop_constraint(op.f(f"ck_analysis_runs_{name}"), "analysis_runs", type_="check")
    for column in ("title", "note", "archived_at", "version"):
        op.drop_column("analysis_runs", column)
