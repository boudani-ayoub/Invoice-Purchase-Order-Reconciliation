import hashlib
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in

from reconcile.auth.runtime import AuthRuntime, verify_database_role
from reconcile.persistence import models as db
from reconcile.persistence.audit import AuditEvent
from reconcile.persistence.workflow import Workflow
from reconcile.web.app import create_app
from scripts.postgres_testing import provision_database

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


def test_phase_three_upgrade_preserves_every_existing_row(auth, monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0003") as previous:
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
            _, raw = sign_in((runtime, client, auth[2], auth[3]))
            principal = runtime.sessions.authenticate(raw)
            org, actor = principal.active_organization_id, principal.user_id
            now = auth[3].now
            with Session(previous.admin) as session, session.begin():
                source = db.SourceFile(
                    organization_id=org,
                    source_type="purchase_orders",
                    original_filename="orders.csv",
                    sha256="a" * 64,
                    size_bytes=123,
                )
                session.add(source)
                session.flush()
                po = db.PurchaseOrder(
                    organization_id=org,
                    source_file_id=source.id,
                    po_number="Historical PO",
                    source_supplier_code="Original supplier",
                    order_date=date(2026, 1, 1),
                    currency="EUR",
                )
                session.add(po)
                session.flush()
                line = db.PurchaseOrderLine(
                    organization_id=org,
                    purchase_order_id=po.id,
                    line_number=1,
                    source_row_number=2,
                    source_item_code="Original item",
                    description="Stored evidence",
                    ordered_quantity=1,
                    unit_price=2,
                )
                run = db.AnalysisRun(
                    organization_id=org,
                    analysis_mode="po-receipt",
                    status="COMPLETED",
                    created_by_user_id=actor,
                    started_at=now,
                    completed_at=now,
                    title="Historical title",
                    note="Historical note",
                    version=3,
                )
                session.add_all([line, run])
                session.flush()
                run_id = run.id
                finding_id = session.scalar(
                    text(
                        "INSERT INTO findings "
                        "(organization_id, analysis_run_id, purchase_order_line_id, "
                        "code, category) "
                        "VALUES (:org, :run, :line, 'OVER_RECEIVED', 'QUANTITY') RETURNING id"
                    ),
                    {"org": org, "run": run.id, "line": line.id},
                )
                session.add(
                    db.AnalysisSource(
                        organization_id=org, analysis_run_id=run.id, source_file_id=source.id
                    )
                )
                session.add(
                    db.ResultSnapshot(
                        organization_id=org,
                        analysis_run_id=run.id,
                        schema_version=1,
                        engine_version="0.1.0",
                        report={"mode": "po-receipt", "summary": {}, "results": []},
                    )
                )
                session.add(
                    AuditEvent(
                        organization_id=org,
                        actor_user_id=actor,
                        resource_id=run.id,
                        request_id=uuid4(),
                        event_type="ANALYSIS_COMPLETED",
                        details={"mode": "po-receipt", "version": 3},
                    )
                )
            columns = {
                table: [column["name"] for column in inspect(previous.admin).get_columns(table)]
                for table in inspect(previous.admin).get_table_names()
                if table != "alembic_version"
            }

            def fingerprints():
                with previous.admin.connect() as connection:
                    return {
                        table: hashlib.sha256(
                            repr(
                                connection.execute(
                                    text(f"SELECT {', '.join(names)} FROM {table} ORDER BY id")
                                ).all()
                            ).encode()
                        ).hexdigest()
                        for table, names in columns.items()
                    }

            before = fingerprints()
            monkeypatch.setenv("DATABASE_URL", previous.migration_url)
            config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
            command.upgrade(config, "head")
            command.check(config)
            assert fingerprints() == before
            verify_database_role(previous.runtime, identity=False)
            verify_database_role(previous.identity, identity=True)
            assert runtime.sessions.authenticate(raw).session_id == principal.session_id
            finding = Workflow(runtime.sessions).detail(raw, finding_id)["finding"]
            assert finding["status"] == "OPEN" and finding["version"] == 1
            assert all(
                finding[field] is None
                for field in (
                    "assignee_user_id",
                    "due_at",
                    "reminder_at",
                    "resolved_at",
                    "resolved_by_user_id",
                    "resolution_note",
                )
            )
            assert Workflow(runtime.sessions).events(raw, finding_id)["items"] == []
            with Session(previous.admin) as session:
                assert (
                    session.scalar(select(db.AnalysisRun.title).where(db.AnalysisRun.id == run_id))
                    == "Historical title"
                )
