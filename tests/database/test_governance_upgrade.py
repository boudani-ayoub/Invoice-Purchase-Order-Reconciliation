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


def test_phase_five_upgrade_preserves_identity_and_membership_state(monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0005") as previous:
        organization, user, membership = uuid4(), uuid4(), uuid4()
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
                    "INSERT INTO organization_memberships(id, organization_id, user_id, role) "
                    "VALUES (:id, :organization, :user, 'ORG_ADMIN')"
                ),
                {"id": membership, "organization": organization, "user": user},
            )
            before = connection.execute(
                text(
                    "SELECT o.id, o.name, o.slug, o.status, m.id, m.user_id, m.role, m.status "
                    "FROM organizations o JOIN organization_memberships m "
                    "ON m.organization_id = o.id WHERE o.id = :organization"
                ),
                {"organization": organization},
            ).one()

        monkeypatch.setenv("DATABASE_URL", previous.migration_url)
        config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)

        with previous.admin.connect() as connection:
            after = connection.execute(
                text(
                    "SELECT o.id, o.name, o.slug, o.status, m.id, m.user_id, m.role, m.status "
                    "FROM organizations o JOIN organization_memberships m "
                    "ON m.organization_id = o.id WHERE o.id = :organization"
                ),
                {"organization": organization},
            ).one()
            versions = connection.execute(
                text(
                    "SELECT o.version, m.version FROM organizations o "
                    "JOIN organization_memberships m ON m.organization_id = o.id "
                    "WHERE o.id = :organization"
                ),
                {"organization": organization},
            ).one()
        assert after == before and tuple(versions) == (1, 1)
        assert set(inspect(previous.admin).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        verify_database_role(previous.identity, identity=True)
        verify_database_role(previous.runtime, identity=False)


def test_phase_six_grants_and_policies_match_identity_boundary(database):
    with database.admin.connect() as connection:

        def column_grants(table, role):
            return {
                (row.column_name, row.privilege_type)
                for row in connection.execute(
                    text(
                        "SELECT column_name, privilege_type "
                        "FROM information_schema.column_privileges "
                        "WHERE table_schema = 'public' AND table_name = :table "
                        "AND grantee = :role"
                    ),
                    {"table": table, "role": role},
                )
            }

        organization_updates = {
            column
            for column, privilege in column_grants("organizations", "reconcile_identity")
            if privilege == "UPDATE"
        }
        membership_updates = {
            column
            for column, privilege in column_grants("organization_memberships", "reconcile_identity")
            if privilege == "UPDATE"
        }
        invitation_updates = {
            column
            for column, privilege in column_grants("organization_invitations", "reconcile_identity")
            if privilege == "UPDATE"
        }
        assert organization_updates == {"name", "version"}
        assert membership_updates == {"role", "status", "version"}
        assert invitation_updates == {
            "status",
            "accepted_at",
            "accepted_by_user_id",
            "revoked_at",
            "version",
        }
        assert not column_grants("organization_memberships", "reconcile_runtime") & {
            ("role", "UPDATE"),
            ("status", "UPDATE"),
            ("version", "UPDATE"),
        }
        policies = {
            row.tablename: (row.rowsecurity, row.forcerowsecurity, row.policyname)
            for row in connection.execute(
                text(
                    "SELECT c.relname AS tablename, c.relrowsecurity AS rowsecurity, "
                    "c.relforcerowsecurity AS forcerowsecurity, p.policyname "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "JOIN pg_policies p ON p.tablename = c.relname "
                    "WHERE n.nspname = 'public' AND c.relname IN "
                    "('organization_invitations', 'governance_events')"
                )
            )
        }
        assert policies == {
            "organization_invitations": (True, True, "identity_access"),
            "governance_events": (True, True, "identity_access"),
        }
