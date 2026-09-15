"""Add tenant-scoped inventory master data and an append-only stock ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_INVENTORY_TABLES = ("inventory_locations", "inventory_operations", "stock_movements")


def _record_columns():
    return (
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
    )


def _status():
    return sa.Enum(
        "ACTIVE", "ARCHIVED", name="recordstatus", native_enum=False, create_constraint=True
    )


def upgrade() -> None:
    op.add_column("items", sa.Column("base_uom", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.create_check_constraint(
        op.f("ck_items_base_uom_format"),
        "items",
        "base_uom IS NULL OR (length(base_uom) BETWEEN 1 AND 16 "
        "AND base_uom ~ '^[A-Z0-9][A-Z0-9._/-]*$')",
    )
    op.create_check_constraint(op.f("ck_items_version_positive"), "items", "version > 0")

    op.create_table(
        "inventory_locations",
        *_record_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", _status(), server_default="ACTIVE", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_locations")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_inventory_locations_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "location_code",
            name=op.f("uq_inventory_locations_organization_id_location_code"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
            name=op.f("fk_inventory_locations_organization_id_organizations"),
        ),
        sa.CheckConstraint(
            "length(location_code) BETWEEN 1 AND 64 AND location_code = btrim(location_code)",
            name=op.f("ck_inventory_locations_code_nonempty"),
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 200 AND name = btrim(name)",
            name=op.f("ck_inventory_locations_name_nonempty"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_inventory_locations_version_positive")),
    )
    op.create_index(
        "ix_inventory_locations_code",
        "inventory_locations",
        ["organization_id", "location_code"],
    )

    op.create_table(
        "inventory_operations",
        *_record_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "operation_type",
            sa.Enum(
                "OPENING_BALANCE",
                "STOCK_RECEIPT",
                "STOCK_ISSUE",
                "ADJUSTMENT_IN",
                "ADJUSTMENT_OUT",
                "TRANSFER",
                "REVERSAL",
                name="inventoryoperationtype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_reference", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("reverses_operation_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_operations")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_inventory_operations_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name=op.f("uq_inventory_operations_organization_id_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "reverses_operation_id",
            name=op.f("uq_inventory_operations_organization_id_reverses_operation_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
            name=op.f("fk_inventory_operations_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_inventory_operations_actor_membership",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "reverses_operation_id"],
            ["inventory_operations.organization_id", "inventory_operations.id"],
            ondelete="RESTRICT",
            name="fk_inventory_operations_reversal_tenant",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_inventory_operations_request_fingerprint_shape"),
        ),
        sa.CheckConstraint(
            "occurred_at <= created_at",
            name=op.f("ck_inventory_operations_occurred_not_future"),
        ),
        sa.CheckConstraint(
            "external_reference IS NULL OR length(external_reference) <= 200",
            name=op.f("ck_inventory_operations_external_reference_length"),
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(note) <= 1000",
            name=op.f("ck_inventory_operations_note_length"),
        ),
        sa.CheckConstraint(
            "(operation_type = 'REVERSAL' AND reverses_operation_id IS NOT NULL) OR "
            "(operation_type <> 'REVERSAL' AND reverses_operation_id IS NULL)",
            name=op.f("ck_inventory_operations_reversal_reference"),
        ),
    )
    op.create_index(
        "ix_inventory_operations_chronology",
        "inventory_operations",
        ["organization_id", "created_at", "id"],
    )
    op.create_index(
        "ix_inventory_operations_type_chronology",
        "inventory_operations",
        ["organization_id", "operation_type", "created_at", "id"],
    )

    op.create_table(
        "stock_movements",
        *_record_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_movements")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_stock_movements_organization_id_id")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
            name=op.f("fk_stock_movements_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "operation_id"],
            ["inventory_operations.organization_id", "inventory_operations.id"],
            ondelete="RESTRICT",
            name="fk_stock_movements_operation_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "item_id"],
            ["items.organization_id", "items.id"],
            ondelete="RESTRICT",
            name="fk_stock_movements_item_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "location_id"],
            ["inventory_locations.organization_id", "inventory_locations.id"],
            ondelete="RESTRICT",
            name="fk_stock_movements_location_tenant",
        ),
        sa.CheckConstraint(
            "quantity_delta <> 0 AND abs(quantity_delta) < 'Infinity'::numeric",
            name=op.f("ck_stock_movements_quantity_delta_nonzero"),
        ),
    )
    op.create_index(
        "ix_stock_movements_location_item",
        "stock_movements",
        ["organization_id", "location_id", "item_id"],
    )
    op.create_index(
        "ix_stock_movements_item_location",
        "stock_movements",
        ["organization_id", "item_id", "location_id"],
    )
    op.create_index(
        "ix_stock_movements_operation",
        "stock_movements",
        ["organization_id", "operation_id"],
    )

    for table in _INVENTORY_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            "USING (organization_id = NULLIF("
            "current_setting('app.current_organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF("
            "current_setting('app.current_organization_id', true), '')::uuid)"
        )

    op.execute("GRANT SELECT, INSERT ON inventory_locations TO reconcile_runtime")
    op.execute("GRANT UPDATE (name, status, version) ON inventory_locations TO reconcile_runtime")
    op.execute("GRANT SELECT, INSERT ON inventory_operations TO reconcile_runtime")
    op.execute("GRANT SELECT, INSERT ON stock_movements TO reconcile_runtime")
    op.execute("REVOKE UPDATE ON items FROM reconcile_runtime")
    op.execute(
        "GRANT UPDATE (description, base_uom, status, version) ON items TO reconcile_runtime"
    )
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON inventory_locations "
        "FOR EACH ROW EXECUTE FUNCTION touch_updated_at()"
    )
    op.execute("""
        CREATE FUNCTION protect_inventory_ledger() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        BEGIN RAISE EXCEPTION 'Inventory ledger records are immutable'; END $body$;
    """)
    for table in ("inventory_operations", "stock_movements"):
        op.execute(
            f'CREATE TRIGGER protect_inventory_ledger BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION protect_inventory_ledger()"
        )
    op.execute("""
        CREATE FUNCTION protect_inventory_master() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        DECLARE current_quantity numeric;
        BEGIN
            IF TG_TABLE_NAME = 'items' THEN
                IF NEW.item_code IS DISTINCT FROM OLD.item_code THEN
                    RAISE EXCEPTION 'Item code is immutable';
                END IF;
                IF NEW.base_uom IS DISTINCT FROM OLD.base_uom AND EXISTS (
                    SELECT 1 FROM public.stock_movements
                    WHERE organization_id = OLD.organization_id AND item_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'Base unit is immutable after the first stock movement';
                END IF;
                IF NEW.status = 'ARCHIVED' AND OLD.status <> 'ARCHIVED' THEN
                    SELECT COALESCE(sum(quantity_delta), 0) INTO current_quantity
                    FROM public.stock_movements
                    WHERE organization_id = OLD.organization_id AND item_id = OLD.id;
                    IF current_quantity <> 0 THEN
                        RAISE EXCEPTION 'An item with on-hand stock cannot be archived';
                    END IF;
                END IF;
            ELSE
                IF NEW.location_code IS DISTINCT FROM OLD.location_code THEN
                    RAISE EXCEPTION 'Location code is immutable';
                END IF;
                IF NEW.status = 'ARCHIVED' AND OLD.status <> 'ARCHIVED' THEN
                    SELECT COALESCE(sum(quantity_delta), 0) INTO current_quantity
                    FROM public.stock_movements
                    WHERE organization_id = OLD.organization_id AND location_id = OLD.id;
                    IF current_quantity <> 0 THEN
                        RAISE EXCEPTION 'A location with on-hand stock cannot be archived';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END $body$;
    """)
    op.execute(
        "CREATE TRIGGER protect_inventory_item BEFORE UPDATE ON items "
        "FOR EACH ROW EXECUTE FUNCTION protect_inventory_master()"
    )
    op.execute(
        "CREATE TRIGGER protect_inventory_location BEFORE UPDATE ON inventory_locations "
        "FOR EACH ROW EXECUTE FUNCTION protect_inventory_master()"
    )
    op.execute("""
        CREATE FUNCTION validate_stock_movement() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        DECLARE kind text; current_quantity numeric;
        BEGIN
            SELECT operation_type INTO kind FROM public.inventory_operations
            WHERE organization_id = NEW.organization_id AND id = NEW.operation_id;
            IF kind IS NULL THEN RAISE EXCEPTION 'Inventory operation is required'; END IF;
            IF kind IN ('OPENING_BALANCE', 'STOCK_RECEIPT', 'ADJUSTMENT_IN')
               AND NEW.quantity_delta <= 0 THEN
                RAISE EXCEPTION 'Inbound inventory movement must be positive';
            END IF;
            IF kind IN ('STOCK_ISSUE', 'ADJUSTMENT_OUT') AND NEW.quantity_delta >= 0 THEN
                RAISE EXCEPTION 'Outbound inventory movement must be negative';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.items WHERE organization_id = NEW.organization_id
                AND id = NEW.item_id AND status = 'ACTIVE' AND base_uom IS NOT NULL
            ) THEN RAISE EXCEPTION 'An active item with a base unit is required'; END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.inventory_locations
                WHERE organization_id = NEW.organization_id
                AND id = NEW.location_id AND status = 'ACTIVE'
            ) THEN RAISE EXCEPTION 'An active inventory location is required'; END IF;
            PERFORM 1 FROM public.inventory_locations
            WHERE organization_id = NEW.organization_id AND id = NEW.location_id FOR UPDATE;
            IF kind = 'OPENING_BALANCE' AND EXISTS (
                SELECT 1 FROM public.stock_movements
                WHERE organization_id = NEW.organization_id
                  AND item_id = NEW.item_id AND location_id = NEW.location_id
            ) THEN RAISE EXCEPTION 'Opening balance already exists'; END IF;
            SELECT COALESCE(sum(quantity_delta), 0) INTO current_quantity
            FROM public.stock_movements
            WHERE organization_id = NEW.organization_id
              AND item_id = NEW.item_id AND location_id = NEW.location_id;
            IF current_quantity + NEW.quantity_delta < 0 THEN
                RAISE EXCEPTION 'Insufficient on-hand quantity' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $body$;
    """)
    op.execute(
        "CREATE TRIGGER validate_stock_movement BEFORE INSERT ON stock_movements "
        "FOR EACH ROW EXECUTE FUNCTION validate_stock_movement()"
    )
    op.execute("""
        CREATE FUNCTION validate_inventory_operation() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        DECLARE movement_count integer; item_count integer; location_count integer;
                net_quantity numeric; minimum_quantity numeric; maximum_quantity numeric;
        BEGIN
            SELECT count(*), count(DISTINCT item_id), count(DISTINCT location_id),
                   COALESCE(sum(quantity_delta), 0), min(abs(quantity_delta)),
                   max(abs(quantity_delta))
            INTO movement_count, item_count, location_count,
                 net_quantity, minimum_quantity, maximum_quantity
            FROM public.stock_movements
            WHERE organization_id = NEW.organization_id AND operation_id = NEW.id;
            IF NEW.operation_type = 'TRANSFER' AND NOT (
                movement_count = 2 AND item_count = 1 AND location_count = 2
                AND net_quantity = 0 AND minimum_quantity = maximum_quantity
            ) THEN RAISE EXCEPTION 'Transfer must contain one exact source/destination pair';
            ELSIF NEW.operation_type = 'REVERSAL' AND (
                movement_count = 0 OR EXISTS (
                    SELECT 1 FROM public.stock_movements original
                    WHERE original.organization_id = NEW.organization_id
                      AND original.operation_id = NEW.reverses_operation_id
                      AND NOT EXISTS (
                          SELECT 1 FROM public.stock_movements inverse
                          WHERE inverse.organization_id = NEW.organization_id
                            AND inverse.operation_id = NEW.id
                            AND inverse.item_id = original.item_id
                            AND inverse.location_id = original.location_id
                            AND inverse.quantity_delta = -original.quantity_delta
                      )
                ) OR movement_count <> (
                    SELECT count(*) FROM public.stock_movements
                    WHERE organization_id = NEW.organization_id
                      AND operation_id = NEW.reverses_operation_id
                )
            ) THEN RAISE EXCEPTION 'Reversal must exactly negate the original operation';
            ELSIF NEW.operation_type NOT IN ('TRANSFER', 'REVERSAL') AND movement_count <> 1 THEN
                RAISE EXCEPTION 'Inventory operation must contain exactly one movement';
            END IF;
            RETURN NULL;
        END $body$;
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER validate_inventory_operation "
        "AFTER INSERT ON inventory_operations DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION validate_inventory_operation()"
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in (*_INVENTORY_TABLES, "items"):
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
    retained = connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM inventory_locations) "
            "OR EXISTS (SELECT 1 FROM inventory_operations) "
            "OR EXISTS (SELECT 1 FROM stock_movements) "
            "OR EXISTS (SELECT 1 FROM items WHERE base_uom IS NOT NULL OR version <> 1)"
        )
    )
    if retained:
        raise RuntimeError("Phase 7 inventory state cannot be downgraded safely")
    op.execute("DROP TRIGGER protect_inventory_item ON items")
    op.execute("DROP FUNCTION protect_inventory_master() CASCADE")
    op.execute("DROP FUNCTION validate_stock_movement() CASCADE")
    op.execute("DROP FUNCTION validate_inventory_operation() CASCADE")
    op.execute("DROP FUNCTION protect_inventory_ledger() CASCADE")
    op.drop_table("stock_movements")
    op.drop_table("inventory_operations")
    op.drop_table("inventory_locations")
    op.execute(
        "REVOKE UPDATE (description, base_uom, status, version) ON items FROM reconcile_runtime"
    )
    op.execute("GRANT UPDATE ON items TO reconcile_runtime")
    op.drop_constraint(op.f("ck_items_version_positive"), "items", type_="check")
    op.drop_constraint(op.f("ck_items_base_uom_format"), "items", type_="check")
    op.drop_column("items", "version")
    op.drop_column("items", "base_uom")
