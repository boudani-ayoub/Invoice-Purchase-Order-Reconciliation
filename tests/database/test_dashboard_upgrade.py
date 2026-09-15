import os
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in
from test_runs import create
from test_workflow import change

from reconcile.auth.runtime import AuthRuntime, verify_database_role
from reconcile.persistence.base import Base
from reconcile.web.app import create_app
from reconcile.web.paths import FINDINGS_PATH
from scripts.postgres_testing import provision_database

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


def test_phase_four_index_upgrade_preserves_rows_schema_and_security(auth, monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0004") as previous:
        settings = replace(
            auth[0].settings,
            identity_database_url=previous.identity.url.render_as_string(hide_password=False),
            tenant_database_url=previous.runtime.url.render_as_string(hide_password=False),
        )
        runtime = AuthRuntime(
            settings,
            previous.identity,
            previous.runtime,
            mailer=auth[2],
            clock=auth[3],
            passwords=auth[0].accounts.passwords,
        )
        with TestClient(
            create_app(auth=runtime), headers={"Origin": settings.frontend_origin}
        ) as client:
            local = (runtime, client, auth[2], auth[3])
            sign_in(local)
            assert create(local).status_code == 201
            finding = client.get(FINDINGS_PATH).json()["items"][0]
            assert (
                change(local, finding, action="comments", text="Preserve this event").status_code
                == 201
            )
            assert (
                change(
                    local,
                    finding,
                    action="transition",
                    target_status="RESOLVED",
                    resolution_note="Preserve this resolution",
                ).status_code
                == 200
            )

        existing_tables = set(inspect(previous.admin).get_table_names()) - {"alembic_version"}
        columns = {table: inspect(previous.admin).get_columns(table) for table in existing_tables}

        def state():
            with previous.admin.connect() as connection:
                rows = {
                    table: sorted(
                        repr(tuple(row))
                        for row in connection.execute(
                            text(
                                "SELECT "
                                + ", ".join(f'"{column["name"]}"' for column in columns[table])
                                + f' FROM "{table}"'
                            )
                        )
                    )
                    for table in sorted(existing_tables)
                }
                policies = [
                    row
                    for row in connection.execute(
                        text("SELECT * FROM pg_policies ORDER BY tablename, policyname")
                    )
                    if row.tablename in existing_tables
                ]
                grants = [
                    row
                    for row in connection.execute(
                        text(
                            "SELECT * FROM information_schema.table_privileges "
                            "WHERE table_schema = 'public' "
                            "ORDER BY table_name, grantee, privilege_type"
                        )
                    )
                    if row.table_name in existing_tables
                ]
                return rows, policies, grants

        before = state()
        monkeypatch.setenv("DATABASE_URL", previous.migration_url)
        config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
        assert state() == before
        assert set(inspect(previous.admin).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        for table, original in columns.items():
            upgraded = inspect(previous.admin).get_columns(table)
            if table in {"organizations", "organization_memberships"}:
                upgraded = [column for column in upgraded if column["name"] != "version"]
            assert repr(upgraded) == repr(original)
        assert "ix_finding_events_activity" in {
            row["name"] for row in inspect(previous.admin).get_indexes("finding_events")
        }
        verify_database_role(previous.runtime, identity=False)
        verify_database_role(previous.identity, identity=True)
        command.downgrade(config, "0004")
        assert state() == before
        command.upgrade(config, "head")
        command.check(config)
        assert state() == before
