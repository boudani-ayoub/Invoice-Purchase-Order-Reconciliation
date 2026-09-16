import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from reconcile.auth.runtime import verify_database_role
from reconcile.persistence.base import Base
from scripts.postgres_testing import provision_database

pytestmark = pytest.mark.database


def alembic_config(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


def test_phase_six_upgrade_preserves_rows_and_creates_no_inventory(database, monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0006") as previous:
        organization, user, item = uuid4(), uuid4(), uuid4()
        with previous.admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organizations(id, name, slug) "
                    "VALUES (:id, 'Existing organization', :slug)"
                ),
                {"id": organization, "slug": f"existing-{uuid4().hex}"},
            )
            connection.execute(
                text(
                    "INSERT INTO users(id, email, display_name) "
                    "VALUES (:id, :email, 'Existing administrator')"
                ),
                {"id": user, "email": f"existing-{uuid4().hex}@example.com"},
            )
            connection.execute(
                text(
                    "INSERT INTO organization_memberships(organization_id, user_id, role) "
                    "VALUES (:organization, :user, 'ORG_ADMIN')"
                ),
                {"organization": organization, "user": user},
            )
            connection.execute(
                text(
                    "INSERT INTO items(id, organization_id, item_code, description) "
                    "VALUES (:id, :organization, 'LEGACY', 'Existing item')"
                ),
                {"id": item, "organization": organization},
            )

        config = alembic_config(monkeypatch, previous.migration_url)
        command.upgrade(config, "head")
        command.check(config)

        with previous.admin.connect() as connection:
            upgraded = connection.execute(
                text(
                    "SELECT organization_id, item_code, description, status, base_uom, version "
                    "FROM items WHERE id = :id"
                ),
                {"id": item},
            ).one()
            counts = connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM inventory_locations), "
                    "(SELECT count(*) FROM inventory_operations), "
                    "(SELECT count(*) FROM stock_movements)"
                )
            ).one()
        assert tuple(upgraded) == (
            organization,
            "LEGACY",
            "Existing item",
            "ACTIVE",
            None,
            1,
        )
        assert tuple(counts) == (0, 0, 0)
        assert set(inspect(previous.admin).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        verify_database_role(previous.identity, identity=True)
        verify_database_role(previous.runtime, identity=False)


def test_inventory_grants_policies_and_triggers_match_runtime_boundary(database):
    with database.admin.connect() as connection:
        privileges = {
            (row.table_name, row.privilege_type)
            for row in connection.execute(
                text(
                    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND grantee = 'reconcile_runtime' "
                    "AND table_name IN "
                    "('inventory_locations', 'inventory_operations', 'stock_movements')"
                )
            )
        }
        assert privileges == {
            ("inventory_locations", "SELECT"),
            ("inventory_locations", "INSERT"),
            ("inventory_operations", "SELECT"),
            ("inventory_operations", "INSERT"),
            ("stock_movements", "SELECT"),
            ("stock_movements", "INSERT"),
        }
        item_updates = {
            row.column_name
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE table_schema = 'public' AND table_name = 'items' "
                    "AND grantee = 'reconcile_runtime' AND privilege_type = 'UPDATE'"
                )
            )
        }
        location_updates = {
            row.column_name
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE table_schema = 'public' AND table_name = 'inventory_locations' "
                    "AND grantee = 'reconcile_runtime' AND privilege_type = 'UPDATE'"
                )
            )
        }
        assert item_updates == {"description", "base_uom", "status", "version"}
        assert location_updates == {"name", "status", "version"}
        assert not connection.scalar(
            text(
                "SELECT has_table_privilege('reconcile_identity', table_name, "
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE') FROM "
                "(VALUES ('inventory_locations'), ('inventory_operations'), "
                "('stock_movements')) AS inventory(table_name) WHERE "
                "has_table_privilege('reconcile_identity', table_name, "
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE') LIMIT 1"
            )
        )
        policies = {
            row.relname: (row.relrowsecurity, row.relforcerowsecurity, row.policyname)
            for row in connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, p.policyname "
                    "FROM pg_class c JOIN pg_policies p ON p.tablename = c.relname "
                    "WHERE c.relname IN "
                    "('inventory_locations', 'inventory_operations', 'stock_movements')"
                )
            )
        }
        assert policies == {
            table: (True, True, "tenant_isolation")
            for table in ("inventory_locations", "inventory_operations", "stock_movements")
        }
        triggers = {
            row.tgname
            for row in connection.execute(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN "
                    "('items'::regclass, 'inventory_locations'::regclass, "
                    "'inventory_operations'::regclass, 'stock_movements'::regclass)"
                )
            )
        }
        assert {
            "protect_inventory_item",
            "protect_inventory_location",
            "protect_inventory_ledger",
            "validate_stock_movement",
            "validate_inventory_operation",
        }.issubset(triggers)


def test_inventory_downgrade_refuses_to_erase_item_metadata(database, monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0007") as current:
        organization = uuid4()
        with current.admin.begin() as connection:
            connection.execute(
                text("INSERT INTO organizations(id, name, slug) VALUES (:id, 'Org', :slug)"),
                {"id": organization, "slug": f"org-{uuid4().hex}"},
            )
            connection.execute(
                text(
                    "INSERT INTO items(organization_id, item_code, description, base_uom) "
                    "VALUES (:id, 'ITEM', 'Item', 'EA')"
                ),
                {"id": organization},
            )
        with current.admin.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT base_uom FROM items WHERE organization_id = :id"),
                    {"id": organization},
                )
                == "EA"
            )
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007"
        with pytest.raises(RuntimeError, match="cannot be downgraded safely"):
            command.downgrade(alembic_config(monkeypatch, current.migration_url), "0006")


def test_phase_seven_to_eight_index_upgrade_preserves_inventory(database, monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0007") as previous:
        organization, user, item, location, operation = (uuid4() for _ in range(5))
        with previous.admin.begin() as connection:
            connection.execute(
                text("INSERT INTO organizations(id, name, slug) VALUES (:id, 'Org', :slug)"),
                {"id": organization, "slug": f"phase-eight-{uuid4().hex}"},
            )
            connection.execute(
                text(
                    "INSERT INTO users(id, email, display_name) "
                    "VALUES (:id, :email, 'Administrator')"
                ),
                {"id": user, "email": f"phase-eight-{uuid4().hex}@example.com"},
            )
            connection.execute(
                text(
                    "INSERT INTO organization_memberships(organization_id, user_id, role) "
                    "VALUES (:organization, :user, 'ORG_ADMIN')"
                ),
                {"organization": organization, "user": user},
            )
            connection.execute(
                text(
                    "INSERT INTO items(id, organization_id, item_code, description, base_uom) "
                    "VALUES (:item, :organization, 'PRESERVED', 'Preserved item', 'EA')"
                ),
                {"item": item, "organization": organization},
            )
            connection.execute(
                text(
                    "INSERT INTO inventory_locations(id, organization_id, location_code, name) "
                    "VALUES (:location, :organization, 'MAIN', 'Main')"
                ),
                {"location": location, "organization": organization},
            )
            connection.execute(
                text(
                    "INSERT INTO inventory_operations("
                    "id, organization_id, operation_type, actor_user_id, occurred_at, "
                    "request_id, idempotency_key, request_fingerprint) VALUES ("
                    ":operation, :organization, 'OPENING_BALANCE', :user, now(), "
                    ":request, :key, :fingerprint)"
                ),
                {
                    "operation": operation,
                    "organization": organization,
                    "user": user,
                    "request": uuid4(),
                    "key": uuid4(),
                    "fingerprint": "a" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO stock_movements(organization_id, operation_id, item_id, "
                    "location_id, quantity_delta) VALUES "
                    "(:organization, :operation, :item, :location, 3.5)"
                ),
                {
                    "organization": organization,
                    "operation": operation,
                    "item": item,
                    "location": location,
                },
            )

        def inventory_state():
            with previous.admin.connect() as connection:
                return tuple(
                    connection.execute(
                        text(
                            "SELECT i.item_code, l.location_code, o.operation_type, "
                            "m.quantity_delta FROM items i JOIN stock_movements m "
                            "ON m.organization_id = i.organization_id AND m.item_id = i.id "
                            "JOIN inventory_locations l ON l.organization_id = m.organization_id "
                            "AND l.id = m.location_id JOIN inventory_operations o "
                            "ON o.organization_id = m.organization_id AND o.id = m.operation_id "
                            "WHERE i.organization_id = :organization"
                        ),
                        {"organization": organization},
                    ).one()
                )

        before = inventory_state()
        config = alembic_config(monkeypatch, previous.migration_url)
        command.upgrade(config, "head")
        command.check(config)
        assert inventory_state() == before
        assert "ix_inventory_operations_intelligence_window" in {
            row["name"] for row in inspect(previous.admin).get_indexes("inventory_operations")
        }
        command.downgrade(config, "0007")
        assert inventory_state() == before
        command.upgrade(config, "head")
        assert inventory_state() == before
