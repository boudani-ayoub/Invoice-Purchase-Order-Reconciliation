import os
import re
import shutil
import subprocess
from uuid import UUID

import pytest
from sqlalchemy import select, text
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in
from test_runs import context, create

from reconcile.auth.runtime import verify_database_role
from reconcile.persistence.audit import AuditEvent
from reconcile.persistence.models import ResultSnapshot
from reconcile.persistence.session import tenant_session
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
    sign_in(auth)
    organization, actor = context(auth)
    saved = create(auth).json()
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
