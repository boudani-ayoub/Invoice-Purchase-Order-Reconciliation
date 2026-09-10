import hashlib
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in, upload_files

from reconcile.analysis.models import REQUIRED_SOURCES, AnalysisMode
from reconcile.auth.config import AUTH_PATH, CSRF_HEADER
from reconcile.persistence import audit
from reconcile.persistence import models as db
from reconcile.persistence.audit import AuditEvent, AuditEventType
from reconcile.persistence.runs import Runs
from reconcile.persistence.session import tenant_session
from reconcile.web.paths import RUNS_PATH

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


def csrf(client):
    return {CSRF_HEADER: client.get(f"{AUTH_PATH}/csrf").json()["csrf_token"]}


def create(auth, mode=AnalysisMode.THREE_WAY, *, files=None):
    files = files or upload_files()
    return auth[1].post(
        f"{RUNS_PATH}/{mode}",
        files={key: files[key] for key in REQUIRED_SOURCES[mode]},
        headers=csrf(auth[1]),
    )


def context(auth):
    me = auth[1].get(f"{AUTH_PATH}/me").json()
    return UUID(me["active_organization_id"]), UUID(me["user"]["id"])


def mutate(auth, run, *, changes=None, action=None, version=None):
    client = auth[1]
    path = f"{RUNS_PATH}/{run['id']}" + (f"/{action}" if action else "")
    data = {"expected_version": version or run["version"], **(changes or {})}
    return client.request("POST" if action else "PATCH", path, json=data, headers=csrf(client))


def count_rows(session, organization):
    tables = (
        db.SourceFile,
        db.PurchaseOrder,
        db.PurchaseOrderLine,
        db.GoodsReceipt,
        db.GoodsReceiptLine,
        db.Invoice,
        db.InvoiceLine,
        db.AnalysisRun,
        db.AnalysisSource,
        db.Finding,
        db.ResultSnapshot,
        AuditEvent,
    )
    return {
        table.__tablename__: session.scalar(
            select(func.count()).select_from(table).where(table.organization_id == organization)
        )
        for table in tables
    }


@pytest.mark.parametrize("mode", list(AnalysisMode))
def test_persistent_modes_keep_exact_report_and_provenance(auth, database, mode, monkeypatch):
    sign_in(auth)
    organization, actor = context(auth)
    files = upload_files()
    expected = (
        auth[1]
        .post(
            f"/api/v1/analyses/{mode}",
            files={key: files[key] for key in REQUIRED_SOURCES[mode]},
            headers=csrf(auth[1]),
        )
        .json()
    )
    response = create(auth, mode)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["report"] == expected
    run_id = UUID(payload["run"]["id"])
    with tenant_session(database.runtime, organization) as session:
        run = session.get(db.AnalysisRun, run_id)
        assert run.created_by_user_id == actor
        assert run.status == db.RunStatus.COMPLETED and run.version == 1
        event = session.scalar(select(AuditEvent).where(AuditEvent.resource_id == run_id))
        assert event.actor_user_id == actor
        assert event.request_id == UUID(response.headers["X-Request-ID"])
        assert event.event_type == AuditEventType.ANALYSIS_COMPLETED
        assert set(event.details) == {"mode", "version"}
        assert session.scalar(
            select(func.count())
            .select_from(db.AnalysisSource)
            .where(db.AnalysisSource.analysis_run_id == run_id)
        ) == len(REQUIRED_SOURCES[mode])
    monkeypatch.setattr(
        "reconcile.web.runs.render_records", lambda *_: pytest.fail("History must not reanalyze")
    )
    detail = auth[1].get(f"{RUNS_PATH}/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["report"] == expected
    assert detail.headers["Cache-Control"] == "no-store"
    for source in detail.json()["sources"]:
        original = files[source["source_type"]]
        assert source["sha256"] == hashlib.sha256(original[1]).hexdigest()
        assert source["size_bytes"] == len(original[1])
        assert set(source) == {"source_type", "filename", "size_bytes", "sha256", "created_at"}
    history = auth[1].get(RUNS_PATH).json()
    assert history["items"][0]["summary"] == expected["summary"]
    assert "report" not in history["items"][0] and "note" not in history["items"][0]


def test_duplicate_occurrences_unresolved_references_and_reimports_survive(auth, database):
    sign_in(auth)
    organization, _ = context(auth)
    first = create(auth).json()
    second = create(auth).json()
    assert first["run"]["id"] != second["run"]["id"]
    assert first["report"] == second["report"]
    summary = first["report"]["summary"]
    assert [
        summary[key]
        for key in (
            "invoices_processed",
            "invoice_lines_processed",
            "matched_lines",
            "review_required_lines",
        )
    ] == [15, 17, 6, 11]
    assert summary["disputed_amounts"] == {"EUR": "2450.00", "MAD": "10199.00", "USD": "75.00"}
    with tenant_session(database.runtime, organization) as session:
        assert session.scalar(select(func.count()).select_from(db.InvoiceLine)) == 34
        duplicates = session.scalar(
            select(func.count())
            .select_from(db.Finding)
            .where(db.Finding.code == db.IssueCode.DUPLICATE_INVOICE)
        )
        assert duplicates > 0
        unresolved = session.scalars(
            select(db.InvoiceLine).where(db.InvoiceLine.resolved_purchase_order_line_id.is_(None))
        ).all()
        assert unresolved and all(
            row.source_po_number and row.source_item_code for row in unresolved
        )
        assert session.scalar(select(func.count()).select_from(db.Supplier)) == 0
        assert session.scalar(select(func.count()).select_from(db.Item)) == 0


@pytest.mark.parametrize("failure", ["validation", "persistence", "audit", "analysis"])
def test_failed_create_rolls_back_every_table(auth, database, monkeypatch, failure):
    sign_in(auth)
    organization, _ = context(auth)

    def fail(*args, **kwargs):
        raise RuntimeError("controlled failure")

    files = upload_files()
    if failure == "validation":
        files["invoices"] = ("invoices.csv", b"wrong,header\ninvalid,row\n", "text/csv")
    elif failure == "persistence":
        monkeypatch.setattr("reconcile.persistence.runs.persist_findings", fail)
    elif failure == "audit":
        monkeypatch.setattr(audit, "record_event", fail)
    else:
        monkeypatch.setattr("reconcile.web.runs.render_records", fail)
    response = create(auth, files=files)
    assert response.status_code == (422 if failure == "validation" else 500)
    with tenant_session(database.runtime, organization) as session:
        assert not any(count_rows(session, organization).values())


@pytest.mark.parametrize("role", list(db.MembershipRole))
def test_role_policy_and_archive_restore_versioning(auth, database, role):
    sign_in(auth)
    organization, actor = context(auth)
    run = create(auth).json()["run"]
    with Session(database.admin) as session, session.begin():
        session.execute(
            update(db.OrganizationMembership)
            .where(
                db.OrganizationMembership.organization_id == organization,
                db.OrganizationMembership.user_id == actor,
            )
            .values(role=role)
        )
    assert auth[1].get(RUNS_PATH).status_code == 200
    response = mutate(auth, run, changes={"title": "  Quarter review  ", "note": "Internal only"})
    if role == db.MembershipRole.MEMBER:
        assert response.status_code == 403
        assert mutate(auth, run, action="archive").status_code == 403
        assert mutate(auth, run, action="restore").status_code == 403
        return
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["title"] == "Quarter review" and changed["version"] == 2
    assert mutate(auth, run, changes={"note": "stale"}).status_code == 409
    assert mutate(auth, run, action="archive").status_code == 409
    archived = mutate(auth, changed, action="archive").json()
    assert archived["version"] == 3 and archived["archived_at"]
    assert auth[1].get(RUNS_PATH).json()["items"] == []
    assert len(auth[1].get(RUNS_PATH, params={"archived": "true"}).json()["items"]) == 1
    restored = mutate(auth, archived, action="restore").json()
    assert restored["version"] == 4 and restored["archived_at"] is None
    with tenant_session(database.runtime, organization) as session:
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.resource_id == UUID(run["id"]))
        ).all()
        assert len(events) == 4
        assert "Internal only" not in str([e.details for e in events])


def test_cross_tenant_reads_and_mutations_are_indistinguishable_from_missing(auth):
    sign_in(auth)
    first = create(auth).json()["run"]
    sign_in(auth)
    assert auth[1].get(RUNS_PATH).json()["items"] == []
    for identifier in (first["id"], str(uuid4())):
        foreign = {**first, "id": identifier}
        assert auth[1].get(f"{RUNS_PATH}/{identifier}").status_code == 404
        assert mutate(auth, foreign, changes={"title": "not mine"}).status_code == 404
        assert mutate(auth, foreign, action="archive").status_code == 404
        assert mutate(auth, foreign, action="restore").status_code == 404


@pytest.mark.parametrize("table", [db.User, db.OrganizationMembership, db.Organization])
def test_current_identity_required_on_every_persistent_request(auth, database, table):
    sign_in(auth)
    organization, actor = context(auth)
    run = create(auth).json()["run"]
    with Session(database.admin) as session, session.begin():
        predicate = table.id == (actor if table is db.User else organization)
        if table is db.OrganizationMembership:
            predicate = (table.organization_id == organization) & (table.user_id == actor)
        session.execute(update(table).where(predicate).values(status=db.RecordStatus.ARCHIVED))
    expected = 401 if table is db.User else 403
    assert auth[1].get(RUNS_PATH).status_code == expected
    assert auth[1].get(f"{RUNS_PATH}/{run['id']}").status_code == expected
    assert create(auth).status_code == expected
    assert mutate(auth, run, changes={"title": "denied"}).status_code == expected
    assert mutate(auth, run, action="archive").status_code == expected


def test_audit_failure_rolls_back_metadata_and_archive(auth, database, monkeypatch):
    sign_in(auth)
    organization, _ = context(auth)
    run = create(auth).json()["run"]

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(audit, "record_event", fail)
    assert mutate(auth, run, changes={"title": "must rollback"}).status_code == 500
    assert mutate(auth, run, action="archive").status_code == 500
    current = auth[1].get(f"{RUNS_PATH}/{run['id']}").json()["run"]
    assert current == run
    with tenant_session(database.runtime, organization) as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_history_keyset_filters_and_malformed_cursor(auth, database):
    sign_in(auth)
    runs = [
        create(auth, mode).json()["run"]
        for mode in (AnalysisMode.THREE_WAY, AnalysisMode.INVOICE_PO, AnalysisMode.THREE_WAY)
    ]
    first = auth[1].get(RUNS_PATH, params={"limit": 2}).json()
    second = auth[1].get(RUNS_PATH, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [row["id"] for row in first["items"] + second["items"]] == [
        r["id"] for r in sorted(runs, key=lambda row: (row["created_at"], row["id"]), reverse=True)
    ]
    assert second["next_cursor"] is None
    filtered = auth[1].get(RUNS_PATH, params={"mode": "invoice-po"}).json()["items"]
    assert len(filtered) == 1
    for cursor in ("!!!", "e30", "W10", "x" * 257):
        assert auth[1].get(RUNS_PATH, params={"cursor": cursor}).status_code in (400, 422)
    for limit in (0, 101):
        assert auth[1].get(RUNS_PATH, params={"limit": limit}).status_code == 422


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE audit_events SET resource_type='ANALYSIS_RUN'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
        "UPDATE result_snapshots SET engine_version='tampered'",
        "DELETE FROM result_snapshots",
    ],
)
def test_runtime_cannot_tamper_with_audit_or_snapshot(auth, database, operation):
    sign_in(auth)
    organization, _ = context(auth)
    create(auth)
    with pytest.raises(DBAPIError), tenant_session(database.runtime, organization) as session:
        session.execute(text(operation))


@pytest.mark.parametrize(
    "field", ["mode", "created_by_user_id", "actor_user_id", "report", "version", "organization_id"]
)
def test_metadata_rejects_mass_assignment(auth, field):
    sign_in(auth)
    run = create(auth).json()["run"]
    assert mutate(auth, run, changes={"title": "valid", field: "forged"}).status_code == 422


def test_mutations_require_csrf_and_notes_remain_plain_text(auth):
    sign_in(auth)
    run = create(auth).json()["run"]
    client = auth[1]
    assert (
        client.patch(
            f"{RUNS_PATH}/{run['id']}", json={"expected_version": 1, "title": "bad"}
        ).status_code
        == 403
    )
    for action in ("archive", "restore"):
        assert (
            client.post(
                f"{RUNS_PATH}/{run['id']}/{action}", json={"expected_version": 1}
            ).status_code
            == 403
        )
    text_value = "<script>alert(1)</script>"
    changed = mutate(auth, run, changes={"title": text_value, "note": text_value}).json()
    assert changed["title"] == text_value
    assert client.get(f"{RUNS_PATH}/{run['id']}").json()["run"]["note"] == text_value


def test_concurrent_metadata_writers_have_one_winner(auth):
    sign_in(auth)
    run = create(auth).json()["run"]
    raw = auth[1].cookies.get(auth[0].settings.session_cookie)
    service = Runs(auth[0].sessions, "test")

    def change(title):
        from reconcile.auth.service_errors import AuthError

        try:
            return service.mutate(raw, UUID(run["id"]), 1, {"title": title}, uuid4())["version"]
        except AuthError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, ("first", "second"))) == [2, 409]
