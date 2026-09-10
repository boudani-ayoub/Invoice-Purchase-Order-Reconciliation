import asyncio
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in, upload_files
from test_runs import context, create, csrf

from reconcile.auth.config import CSRF_HEADER
from reconcile.auth.runtime import verify_database_role
from reconcile.persistence import models as db
from reconcile.persistence.audit import AuditEvent
from reconcile.persistence.session import tenant_session
from reconcile.web.app import create_app
from reconcile.web.paths import MULTIPART_PATHS, RUNS_PATH

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


@pytest.mark.parametrize("path", sorted(MULTIPART_PATHS))
@pytest.mark.parametrize(
    "failure", ["anonymous", "invalid_session", "expired", "membership", "csrf"]
)
def test_denied_multipart_never_reads_request_body(auth, database, path, failure):
    sign_in(auth)
    headers = csrf(auth[1])
    raw = auth[1].cookies.get(auth[0].settings.session_cookie)
    organization, actor = context(auth)
    if failure == "anonymous":
        raw = ""
    elif failure == "invalid_session":
        raw = "x" * 43
    elif failure == "expired":
        auth[3].now += timedelta(hours=13)
    elif failure == "membership":
        with Session(database.admin) as session, session.begin():
            session.execute(
                update(db.OrganizationMembership)
                .where(
                    db.OrganizationMembership.organization_id == organization,
                    db.OrganizationMembership.user_id == actor,
                )
                .values(status=db.RecordStatus.ARCHIVED)
            )
    else:
        headers[CSRF_HEADER] = "invalid"
    cookie = "; ".join(
        f"{key}={value}"
        for key, value in auth[1].cookies.items()
        if key != auth[0].settings.session_cookie
    )
    cookie += f"; {auth[0].settings.session_cookie}={raw}"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"origin", auth[0].settings.frontend_origin.encode()),
            (b"cookie", cookie.encode()),
            (CSRF_HEADER.lower().encode(), headers[CSRF_HEADER].encode()),
            (b"content-type", b"multipart/form-data; boundary=test"),
            (b"content-length", b"999999999"),
        ],
        "state": {},
    }
    messages = []
    consumed = 0

    async def receive():
        nonlocal consumed
        consumed += 1
        raise AssertionError("Unauthorized body was read")

    async def send(message):
        messages.append(message)

    asyncio.run(
        create_app(auth=auth[0], allowed_origins=[auth[0].settings.frontend_origin])(
            scope, receive, send
        )
    )
    assert consumed == 0
    assert next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    ) == (403 if failure in {"membership", "csrf"} else 401)


def test_original_hash_filename_and_multiline_row_positions(auth, database, monkeypatch):
    sign_in(auth)
    organization, _ = context(auth)
    files = upload_files()
    lines = files["purchase_orders"][1].decode().splitlines()
    fields = lines[1].split(",")
    fields[6] = '"Quoted\nmultiline description"'
    lines[1] = ",".join(fields)
    body = ("\n".join(lines) + "\n").encode()
    files["purchase_orders"] = ("../../unsafe\\orders.csv", body, "text/csv")
    directories = []

    def directory():
        result = TemporaryDirectory(prefix="reconcile-api-test-")
        directories.append(Path(result.name))
        return result

    monkeypatch.setattr("reconcile.web.app._request_directory", directory)
    response = create(auth, files=files)
    assert response.status_code == 201, response.text
    assert directories and all(not path.exists() for path in directories)
    with tenant_session(database.runtime, organization) as session:
        source = session.scalar(
            select(db.SourceFile).where(db.SourceFile.source_type == db.SourceType.PURCHASE_ORDERS)
        )
        assert source.original_filename == "orders.csv"
        first = session.scalar(
            select(db.PurchaseOrderLine).order_by(db.PurchaseOrderLine.source_row_number)
        )
        assert first.source_row_number == 3
        assert first.description == "Quoted\nmultiline description"


@pytest.mark.parametrize(
    "operation",
    ["UPDATE audit_events SET resource_type='ANALYSIS_RUN'", "DELETE FROM audit_events"],
)
def test_audit_trigger_rejects_privileged_row_mutation(auth, database, operation):
    sign_in(auth)
    create(auth)
    with pytest.raises(DBAPIError), database.admin.begin() as connection:
        connection.execute(text(operation))


def test_audit_actor_and_resource_foreign_keys_cannot_cross_tenants(auth, database):
    sign_in(auth)
    first_org, first_actor = context(auth)
    first = create(auth).json()["run"]
    sign_in(auth)
    second_org, second_actor = context(auth)
    second = create(auth).json()["run"]
    for actor, run_id in ((second_actor, first["id"]), (first_actor, second["id"])):
        with pytest.raises(IntegrityError), Session(database.admin) as session, session.begin():
            session.add(
                AuditEvent(
                    organization_id=first_org,
                    actor_user_id=actor,
                    resource_id=UUID(run_id),
                    request_id=uuid4(),
                    event_type="RUN_METADATA_UPDATED",
                    details={},
                )
            )
    with tenant_session(database.runtime, second_org) as session:
        assert not session.scalar(select(AuditEvent).where(AuditEvent.organization_id == first_org))


def test_identity_role_cannot_access_history_or_audit(auth, database):
    verify_database_role(database.identity, identity=True)
    verify_database_role(database.runtime, identity=False)
    for table in ("analysis_runs", "source_files", "audit_events", "result_snapshots"):
        with pytest.raises(DBAPIError), database.identity.begin() as connection:
            connection.execute(text(f"SELECT * FROM {table}"))


@pytest.mark.parametrize(
    "field,value",
    [("title", "x" * 121), ("note", "x" * 4001), ("version", 0), ("archived_at", "1900-01-01")],
)
def test_run_metadata_has_database_constraints(auth, database, field, value):
    sign_in(auth)
    run = create(auth).json()["run"]
    with pytest.raises(IntegrityError), Session(database.admin) as session, session.begin():
        session.execute(
            update(db.AnalysisRun)
            .where(db.AnalysisRun.id == UUID(run["id"]))
            .values({field: value})
        )


def test_create_rejects_actor_injection_and_oversize_requests(auth):
    sign_in(auth)
    response = auth[1].post(
        f"{RUNS_PATH}/three-way",
        files=upload_files(),
        data={"actor_user_id": str(uuid4())},
        headers=csrf(auth[1]),
    )
    assert response.status_code == 422
    run = create(auth).json()["run"]
    assert (
        auth[1]
        .patch(
            f"{RUNS_PATH}/{run['id']}",
            content=b"x" * (16 * 1024 + 1),
            headers={**csrf(auth[1]), "Content-Type": "application/json"},
        )
        .status_code
        == 413
    )


def test_cors_allows_patch_only_for_trusted_origin(auth):
    client = auth[1]
    response = client.options(
        f"{RUNS_PATH}/{uuid4()}",
        headers={
            "Origin": auth[0].settings.frontend_origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": CSRF_HEADER,
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-origin"] == auth[0].settings.frontend_origin


@pytest.mark.parametrize("value", [str(2**63), "\x00"])
def test_source_storage_limits_fail_explicitly_without_partial_history(auth, database, value):
    from test_runs import count_rows

    sign_in(auth)
    organization, _ = context(auth)
    files = upload_files()
    lines = files["invoices"][1].decode().splitlines()
    fields = lines[1].split(",")
    fields[1 if value.isdigit() else 4] = value
    lines[1] = ",".join(fields)
    files["invoices"] = ("invoices.csv", ("\n".join(lines) + "\n").encode(), "text/csv")
    response = create(auth, files=files)
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "storage_capacity"
    with tenant_session(database.runtime, organization) as session:
        assert all(count == 0 for count in count_rows(session, organization).values())


def test_runtime_cannot_rewrite_saved_evidence_or_decisions(auth, database):
    sign_in(auth)
    organization, _ = context(auth)
    create(auth)
    for table in (
        "source_files",
        "purchase_orders",
        "purchase_order_lines",
        "goods_receipts",
        "goods_receipt_lines",
        "invoices",
        "invoice_lines",
        "analysis_sources",
        "findings",
    ):
        with pytest.raises(DBAPIError), tenant_session(database.runtime, organization) as session:
            session.execute(text(f"UPDATE {table} SET id=id"))


def test_org_switch_rotates_session_and_history(auth, database):
    from test_auth import post

    sign_in(auth)
    first_org, actor = context(auth)
    run = create(auth).json()["run"]
    with Session(database.admin) as session, session.begin():
        other = db.Organization(name="Other", slug=f"other-{uuid4().hex}")
        session.add(other)
        session.flush()
        other_id = other.id
        session.add(
            db.OrganizationMembership(
                organization_id=other.id, user_id=actor, role=db.MembershipRole.ORG_ADMIN
            )
        )
    old = auth[1].cookies.get(auth[0].settings.session_cookie)
    assert (
        post(auth[1], "select-organization", {"organization_id": str(other_id)}).status_code == 200
    )
    assert auth[1].cookies.get(auth[0].settings.session_cookie) != old
    assert auth[1].get(RUNS_PATH).json()["items"] == []
    assert auth[1].get(f"{RUNS_PATH}/{run['id']}").status_code == 404
    assert create(auth).status_code == 201
    assert (
        post(auth[1], "select-organization", {"organization_id": str(first_org)}).status_code == 200
    )
    assert auth[1].get(RUNS_PATH).json()["items"][0]["id"] == run["id"]
