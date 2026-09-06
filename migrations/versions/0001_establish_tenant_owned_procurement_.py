"""establish tenant owned procurement schema"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


_TENANT_TABLES = (
    "organizations",
    "organization_memberships",
    "suppliers",
    "items",
    "source_files",
    "purchase_orders",
    "purchase_order_lines",
    "goods_receipts",
    "goods_receipt_lines",
    "invoices",
    "invoice_lines",
    "analysis_runs",
    "analysis_sources",
    "findings",
    "result_snapshots",
)


def _install_security() -> None:
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO reconcile_runtime")
    for table in _TENANT_TABLES:
        column = "id" if table == "organizations" else "organization_id"
        predicate = (
            f"{column} = NULLIF(current_setting('app.current_organization_id', true), '')::uuid"
        )
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
        permissions = "SELECT, INSERT" if table == "result_snapshots" else "SELECT, INSERT, UPDATE"
        if table in {"organizations", "organization_memberships"}:
            permissions = "SELECT"
        op.execute(f'GRANT {permissions} ON "{table}" TO reconcile_runtime')
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        BEGIN
            NEW.updated_at = statement_timestamp();
            RETURN NEW;
        END $body$;
    """)
    for table in (*_TENANT_TABLES, "users"):
        if table != "result_snapshots":
            op.execute(
                f'CREATE TRIGGER touch_updated_at BEFORE UPDATE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION touch_updated_at()"
            )
    op.execute("""
        CREATE FUNCTION protect_result_snapshot() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Result snapshots are immutable';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.analysis_runs
                WHERE id = NEW.analysis_run_id AND organization_id = NEW.organization_id
                  AND status = 'COMPLETED'
                  AND analysis_mode = NEW.report->>'mode'
            ) THEN
                RAISE EXCEPTION 'Snapshot requires a completed run with the same mode';
            END IF;
            RETURN NEW;
        END $body$;
    """)
    op.execute("""
        CREATE TRIGGER protect_result_snapshot
        BEFORE INSERT OR UPDATE OR DELETE ON result_snapshots
        FOR EACH ROW EXECUTE FUNCTION protect_result_snapshot()
    """)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "ARCHIVED", name="recordstatus", native_enum=False, create_constraint=True
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "name = btrim(name) AND name <> ''", name=op.f("ck_organizations_name_nonempty")
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_organizations_slug_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "ARCHIVED", name="recordstatus", native_enum=False, create_constraint=True
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND email ~ '^[^@[:space:]]+@[^@[:space:]]+$'",
            name=op.f("ck_users_email_normalized"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "items",
        sa.Column("item_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "ARCHIVED", name="recordstatus", native_enum=False, create_constraint=True
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "item_code <> '' AND item_code = btrim(item_code)", name=op.f("ck_items_code_nonempty")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_items_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_items_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "item_code", name=op.f("uq_items_organization_id_item_code")
        ),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "MEMBER",
                "AP_MANAGER",
                "ORG_ADMIN",
                name="membershiprole",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "ARCHIVED", name="recordstatus", native_enum=False, create_constraint=True
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_memberships_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_memberships_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_memberships")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_organization_memberships_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name=op.f("uq_organization_memberships_organization_id_user_id"),
        ),
    )
    op.create_table(
        "source_files",
        sa.Column(
            "source_type",
            sa.Enum(
                "purchase_orders",
                "receipts",
                "invoices",
                name="sourcetype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "original_filename <> '' AND original_filename !~ '[/\\\\]'",
            name=op.f("ck_source_files_filename_not_path"),
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_source_files_sha256_format")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_source_files_size_nonnegative")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_source_files_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_files")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_source_files_organization_id_id")
        ),
    )
    op.create_table(
        "suppliers",
        sa.Column("supplier_code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "ARCHIVED", name="recordstatus", native_enum=False, create_constraint=True
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "supplier_code <> '' AND supplier_code = btrim(supplier_code)",
            name=op.f("ck_suppliers_code_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_suppliers_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_suppliers_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id",
            "supplier_code",
            name=op.f("uq_suppliers_organization_id_supplier_code"),
        ),
    )
    op.create_table(
        "analysis_runs",
        sa.Column(
            "analysis_mode",
            sa.Enum(
                "invoice-po",
                "invoice-receipt",
                "po-receipt",
                "three-way",
                name="analysismode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="runstatus",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR completed_at IS NOT NULL",
            name=op.f("ck_analysis_runs_completed_timestamp"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name=op.f("ck_analysis_runs_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name=op.f("fk_analysis_runs_organization_id_organization_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_analysis_runs_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_analysis_runs_organization_id_id")
        ),
    )
    op.create_index(
        "ix_analysis_runs_chronology",
        "analysis_runs",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "goods_receipts",
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_number", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "receipt_number <> ''", name=op.f("ck_goods_receipts_receipt_number_nonempty")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_file_id"],
            ["source_files.organization_id", "source_files.id"],
            name="fk_source_file_id_source_files_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_goods_receipts_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goods_receipts")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_goods_receipts_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_file_id",
            "receipt_number",
            name=op.f("uq_goods_receipts_organization_id_source_file_id_receipt_number"),
        ),
    )
    op.create_table(
        "invoices",
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_number", sa.Text(), nullable=False),
        sa.Column("source_supplier_code", sa.Text(), nullable=False),
        sa.Column("resolved_supplier_id", sa.Uuid(), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_invoices_currency_code")),
        sa.CheckConstraint(
            "invoice_number <> '' AND source_supplier_code <> ''",
            name=op.f("ck_invoices_source_identity_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_supplier_id"],
            ["suppliers.organization_id", "suppliers.id"],
            name="fk_resolved_supplier_id_suppliers_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_file_id"],
            ["source_files.organization_id", "source_files.id"],
            name="fk_source_file_id_source_files_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invoices_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_invoices_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id",
            "source_file_id",
            "source_supplier_code",
            "invoice_number",
            name=op.f(
                "uq_invoices_organization_id_source_file_id_source_supplier_code_invoice_number"
            ),
        ),
    )
    op.create_index(
        "ix_invoices_logical_identity",
        "invoices",
        ["organization_id", "source_supplier_code", "invoice_number"],
        unique=False,
    )
    op.create_table(
        "purchase_orders",
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("po_number", sa.Text(), nullable=False),
        sa.Column("source_supplier_code", sa.Text(), nullable=False),
        sa.Column("resolved_supplier_id", sa.Uuid(), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_purchase_orders_currency_code")
        ),
        sa.CheckConstraint(
            "po_number <> '' AND source_supplier_code <> ''",
            name=op.f("ck_purchase_orders_source_identity_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_supplier_id"],
            ["suppliers.organization_id", "suppliers.id"],
            name="fk_resolved_supplier_id_suppliers_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_file_id"],
            ["source_files.organization_id", "source_files.id"],
            name="fk_source_file_id_source_files_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_purchase_orders_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_orders")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_purchase_orders_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_file_id",
            "po_number",
            name=op.f("uq_purchase_orders_organization_id_source_file_id_po_number"),
        ),
    )
    op.create_table(
        "analysis_sources",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["organization_id", "analysis_run_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
            name="fk_analysis_run_id_analysis_runs_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_file_id"],
            ["source_files.organization_id", "source_files.id"],
            name="fk_source_file_id_source_files_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_analysis_sources_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_sources")),
        sa.UniqueConstraint(
            "organization_id",
            "analysis_run_id",
            "source_file_id",
            name=op.f("uq_analysis_sources_organization_id_analysis_run_id_source_file_id"),
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_analysis_sources_organization_id_id")
        ),
    )
    op.create_table(
        "purchase_order_lines",
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.BigInteger(), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=False),
        sa.Column("source_item_code", sa.Text(), nullable=False),
        sa.Column("resolved_item_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(), nullable=False),
        sa.Column("unit_price", sa.Numeric(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "ordered_quantity > 0 AND ordered_quantity < 'Infinity'::numeric",
            name=op.f("ck_purchase_order_lines_ordered_quantity_positive"),
        ),
        sa.CheckConstraint(
            "source_item_code <> ''", name=op.f("ck_purchase_order_lines_item_nonempty")
        ),
        sa.CheckConstraint(
            "unit_price >= 0 AND unit_price < 'Infinity'::numeric",
            name=op.f("ck_purchase_order_lines_unit_price_nonnegative"),
        ),
        sa.CheckConstraint(
            "line_number > 0 AND source_row_number > 1",
            name=op.f("ck_purchase_order_lines_line_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "purchase_order_id"],
            ["purchase_orders.organization_id", "purchase_orders.id"],
            name="fk_purchase_order_id_purchase_orders_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_item_id"],
            ["items.organization_id", "items.id"],
            name="fk_resolved_item_id_items_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_purchase_order_lines_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order_lines")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_purchase_order_lines_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "purchase_order_id",
            "line_number",
            name=op.f("uq_purchase_order_lines_organization_id_purchase_order_id_line_number"),
        ),
    )
    op.create_table(
        "result_snapshots",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "jsonb_typeof(report) = 'object' AND report ? 'mode' "
            "AND report ? 'summary' AND report ? 'results'",
            name=op.f("ck_result_snapshots_report_envelope"),
        ),
        sa.CheckConstraint(
            "schema_version > 0 AND engine_version <> ''",
            name=op.f("ck_result_snapshots_versions_present"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "analysis_run_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
            name="fk_analysis_run_id_analysis_runs_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_result_snapshots_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_result_snapshots")),
        sa.UniqueConstraint(
            "organization_id",
            "analysis_run_id",
            name=op.f("uq_result_snapshots_organization_id_analysis_run_id"),
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_result_snapshots_organization_id_id")
        ),
    )
    op.create_table(
        "goods_receipt_lines",
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.BigInteger(), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("received_quantity", sa.Numeric(), nullable=False),
        sa.Column("source_po_number", sa.Text(), nullable=False),
        sa.Column("source_po_line_number", sa.BigInteger(), nullable=False),
        sa.Column("source_item_code", sa.Text(), nullable=False),
        sa.Column("resolved_purchase_order_line_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_item_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "received_quantity > 0 AND received_quantity < 'Infinity'::numeric",
            name=op.f("ck_goods_receipt_lines_received_quantity_positive"),
        ),
        sa.CheckConstraint(
            "source_po_number <> '' AND source_item_code <> '' AND source_po_line_number > 0",
            name=op.f("ck_goods_receipt_lines_source_reference_valid"),
        ),
        sa.CheckConstraint(
            "line_number > 0 AND source_row_number > 1",
            name=op.f("ck_goods_receipt_lines_line_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "goods_receipt_id"],
            ["goods_receipts.organization_id", "goods_receipts.id"],
            name="fk_goods_receipt_id_goods_receipts_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_item_id"],
            ["items.organization_id", "items.id"],
            name="fk_resolved_item_id_items_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_purchase_order_line_id"],
            ["purchase_order_lines.organization_id", "purchase_order_lines.id"],
            name="fk_resolved_purchase_order_line_id_purchase_order_lines_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_goods_receipt_lines_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goods_receipt_lines")),
        sa.UniqueConstraint(
            "organization_id",
            "goods_receipt_id",
            "line_number",
            name=op.f("uq_goods_receipt_lines_organization_id_goods_receipt_id_line_number"),
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_goods_receipt_lines_organization_id_id")
        ),
    )
    op.create_table(
        "invoice_lines",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.BigInteger(), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=False),
        sa.Column("invoiced_quantity", sa.Numeric(), nullable=False),
        sa.Column("unit_price", sa.Numeric(), nullable=False),
        sa.Column("source_po_number", sa.Text(), nullable=False),
        sa.Column("source_po_line_number", sa.BigInteger(), nullable=False),
        sa.Column("source_item_code", sa.Text(), nullable=False),
        sa.Column("resolved_purchase_order_line_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_item_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "invoiced_quantity > 0 AND invoiced_quantity < 'Infinity'::numeric",
            name=op.f("ck_invoice_lines_invoiced_quantity_positive"),
        ),
        sa.CheckConstraint(
            "source_po_number <> '' AND source_item_code <> '' AND source_po_line_number > 0",
            name=op.f("ck_invoice_lines_source_reference_valid"),
        ),
        sa.CheckConstraint(
            "unit_price >= 0 AND unit_price < 'Infinity'::numeric",
            name=op.f("ck_invoice_lines_unit_price_nonnegative"),
        ),
        sa.CheckConstraint(
            "line_number > 0 AND source_row_number > 1", name=op.f("ck_invoice_lines_line_positive")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_invoice_id_invoices_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_item_id"],
            ["items.organization_id", "items.id"],
            name="fk_resolved_item_id_items_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_purchase_order_line_id"],
            ["purchase_order_lines.organization_id", "purchase_order_lines.id"],
            name="fk_resolved_purchase_order_line_id_purchase_order_lines_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invoice_lines_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_lines")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_invoice_lines_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "invoice_id",
            "source_row_number",
            name=op.f("uq_invoice_lines_organization_id_invoice_id_source_row_number"),
        ),
    )
    op.create_index(
        "ix_invoice_lines_duplicate_key",
        "invoice_lines",
        ["organization_id", "invoice_id", "line_number"],
        unique=False,
    )
    op.create_table(
        "findings",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "code",
            sa.Enum(
                "UNKNOWN_PO",
                "UNKNOWN_ITEM",
                "SUPPLIER_MISMATCH",
                "CURRENCY_MISMATCH",
                "QUANTITY_EXCEEDS_RECEIPT",
                "QUANTITY_EXCEEDS_PO",
                "MISSING_RECEIPT",
                "PRICE_MISMATCH",
                "DUPLICATE_INVOICE",
                "RECEIPT_ITEM_MISMATCH",
                "OVER_RECEIVED",
                name="issuecode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "REFERENCE",
                "DUPLICATE",
                "COMMERCIAL",
                "QUANTITY",
                name="findingcategory",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN", "RESOLVED", name="findingstatus", native_enum=False, create_constraint=True
            ),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("invoice_line_id", sa.Uuid(), nullable=True),
        sa.Column("purchase_order_line_id", sa.Uuid(), nullable=True),
        sa.Column("goods_receipt_line_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "num_nonnulls(invoice_line_id, purchase_order_line_id, goods_receipt_line_id) > 0",
            name=op.f("ck_findings_subject_required"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "analysis_run_id"],
            ["analysis_runs.organization_id", "analysis_runs.id"],
            name="fk_analysis_run_id_analysis_runs_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "goods_receipt_line_id"],
            ["goods_receipt_lines.organization_id", "goods_receipt_lines.id"],
            name="fk_goods_receipt_line_id_goods_receipt_lines_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "invoice_line_id"],
            ["invoice_lines.organization_id", "invoice_lines.id"],
            name="fk_invoice_line_id_invoice_lines_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "purchase_order_line_id"],
            ["purchase_order_lines.organization_id", "purchase_order_lines.id"],
            name="fk_purchase_order_line_id_purchase_order_lines_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_findings_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_findings_organization_id_id")),
    )
    op.create_index(
        "ix_findings_run_status",
        "findings",
        ["organization_id", "analysis_run_id", "status"],
        unique=False,
    )

    _install_security()


def downgrade() -> None:
    op.drop_index("ix_findings_run_status", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_invoice_lines_duplicate_key", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_table("goods_receipt_lines")
    op.drop_table("result_snapshots")
    op.drop_table("purchase_order_lines")
    op.drop_table("analysis_sources")
    op.drop_table("purchase_orders")
    op.drop_index("ix_invoices_logical_identity", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("goods_receipts")
    op.drop_index("ix_analysis_runs_chronology", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_table("suppliers")
    op.drop_table("source_files")
    op.drop_table("organization_memberships")
    op.drop_table("items")
    op.drop_table("users")
    op.drop_table("organizations")
    op.execute("DROP FUNCTION protect_result_snapshot()")
    op.execute("DROP FUNCTION touch_updated_at()")
