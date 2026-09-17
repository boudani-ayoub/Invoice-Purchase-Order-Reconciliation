import os
import re
import shutil
import subprocess
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from test_auth import PASSWORD, sign_in
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_inventory import create_item, create_location, movement
from test_runs import context, create, csrf

from reconcile.auth.runtime import verify_database_role
from reconcile.persistence import models as db
from reconcile.persistence.audit import AuditEvent
from reconcile.persistence.intelligence import Intelligence
from reconcile.persistence.models import ResultSnapshot
from reconcile.persistence.session import tenant_session
from reconcile.web.paths import FINDINGS_PATH, INTELLIGENCE_PATH
from scripts.postgres_testing import provision_database

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


def test_disposable_logical_backup_restores_snapshot_audit_and_rls(auth, database, tmp_path):
    client_path = os.environ.get("POSTGRES_BIN", os.environ.get("PATH"))
    dump = shutil.which("pg_dump", path=client_path)
    restore = shutil.which("pg_restore", path=client_path)
    if not dump or not restore:
        pytest.skip("PostgreSQL client binaries are required for the optional restore smoke")
    version = subprocess.run([dump, "--version"], capture_output=True, text=True, check=True)
    with database.admin.connect() as connection:
        server_major = int(connection.scalar(text("SHOW server_version_num"))) // 10000
    if int(re.search(r"(\d+)\.", version.stdout)[1]) < server_major:
        pytest.skip("pg_dump must be at least the server's major version")
    email, raw = sign_in(auth)
    organization, actor = context(auth)
    saved = create(auth).json()
    finding_id = (
        auth[1]
        .get(FINDINGS_PATH, params={"run_id": saved["run"]["id"], "limit": 1})
        .json()["items"][0]["id"]
    )
    comment = auth[1].post(
        f"{FINDINGS_PATH}/{finding_id}/comments",
        json={"text": "Synthetic restore rehearsal comment"},
        headers=csrf(auth[1]),
    )
    assert comment.status_code == 201
    invitation = auth[0].governance.create_invitation(
        raw,
        email="restore-invitation@example.com",
        role=db.MembershipRole.MEMBER,
        request_id=uuid4(),
    )
    item = create_item(auth[1], "RESTORE-SKU")
    location = create_location(auth[1], "RESTORE-LOCATION")
    receipt = movement(auth[1], "STOCK_RECEIPT", item["id"], location["id"], "7.25")
    assert receipt.status_code == 201
    intelligence = auth[1].get(f"{INTELLIGENCE_PATH}/runs/{saved['run']['id']}/procurement")
    assert intelligence.status_code == 200
    assert intelligence.json()["scope"] == "selected_run"
    archive = tmp_path / "synthetic-test-backup.dump"

    def command(executable, url, *args):
        environment = {
            **os.environ,
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database,
            "PGUSER": url.username,
            "PGPASSWORD": url.password or "",
            "PGCONNECT_TIMEOUT": "5",
        }
        completed = subprocess.run(
            [executable, *args], env=environment, capture_output=True, timeout=90
        )
        assert completed.returncode == 0, "Disposable backup/restore command failed"

    command(dump, database.admin.url, "--format=custom", "--no-owner", f"--file={archive}")
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision=None) as restored:
        command(
            restore,
            restored.admin.url,
            "--dbname=" + restored.admin.url.database,
            "--no-owner",
            "--exit-on-error",
            str(archive),
        )
        verify_database_role(restored.runtime, identity=False)
        verify_database_role(restored.identity, identity=True)
        with restored.admin.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
            tables = {
                row[0]: (row[1], row[2])
                for row in connection.execute(
                    text(
                        "SELECT relname, relrowsecurity, relforcerowsecurity "
                        "FROM pg_class JOIN pg_namespace ON pg_namespace.oid = relnamespace "
                        "WHERE nspname = 'public' AND relkind = 'r' "
                        "AND relname <> 'alembic_version'"
                    )
                )
            }
            assert tables and all(enabled and forced for enabled, forced in tables.values())
            indexes = set(
                connection.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
                        "AND indexname IN "
                        "('ix_finding_events_activity', "
                        "'ix_inventory_operations_intelligence_window')"
                    )
                )
            )
            assert indexes == {
                "ix_finding_events_activity",
                "ix_inventory_operations_intelligence_window",
            }
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                        "AND tgname LIKE 'protect_%'"
                    )
                )
            )
            assert {
                "protect_result_snapshot",
                "protect_audit_event",
                "protect_finding_event",
                "protect_governance_event",
                "protect_inventory_ledger",
            } <= triggers
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM organization_invitations WHERE id = :invitation"),
                    {"invitation": invitation["id"]},
                )
                == 1
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM governance_events "
                        "WHERE organization_id = :organization"
                    ),
                    {"organization": organization},
                )
                >= 1
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM finding_events WHERE finding_id = :finding "
                        "AND event_type = 'COMMENT_ADDED'"
                    ),
                    {"finding": finding_id},
                )
                == 1
            )
        with tenant_session(restored.runtime, organization) as session:
            snapshot = session.scalar(
                select(ResultSnapshot).where(
                    ResultSnapshot.analysis_run_id == UUID(saved["run"]["id"])
                )
            )
            assert snapshot.report == saved["report"]
            event = session.scalar(
                select(AuditEvent).where(AuditEvent.resource_id == snapshot.analysis_run_id)
            )
            assert event.actor_user_id == actor
        with restored.runtime.connect() as connection:
            assert connection.execute(select(ResultSnapshot)).all() == []
            assert not connection.scalar(
                text("SELECT has_table_privilege(current_user, 'audit_events', 'DELETE,TRUNCATE')")
            )
            assert not connection.scalar(
                text(
                    "SELECT has_table_privilege(current_user, "
                    "'inventory_operations', 'UPDATE,DELETE,TRUNCATE')"
                )
            )

        restored_auth = type(auth[0])(
            auth[0].settings,
            restored.identity,
            restored.runtime,
            mailer=auth[2],
            clock=auth[3],
            passwords=auth[0].accounts.passwords,
        )
        try:
            assert restored_auth.sessions.authenticate(raw).user_id == actor
            restored_raw = restored_auth.accounts.login(email, PASSWORD, None).token
            procurement = Intelligence(restored_auth.sessions).procurement(
                restored_raw, UUID(saved["run"]["id"])
            )
            assert procurement["scope"] == "selected_run"
            assert procurement["result_state"] == {
                "matched_lines": 6,
                "review_required_lines": 11,
            }
            inventory = Intelligence(restored_auth.sessions).inventory(restored_raw)
            restored_position = next(
                row
                for row in inventory["items"]
                if row["item"]["id"] == item["id"] and row["location"]["id"] == location["id"]
            )
            assert restored_position["current_on_hand"] == "7.25"
        finally:
            restored_auth.close()
