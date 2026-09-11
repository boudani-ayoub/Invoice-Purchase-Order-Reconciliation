from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import post
from test_runs import context, csrf
from test_workflow import add_member, change, detail, events
from test_workflow import workflow as workflow_fixture

from reconcile.auth.config import CSRF_HEADER
from reconcile.auth.crypto import token_hash
from reconcile.auth.runtime import verify_database_role
from reconcile.persistence import models as db
from reconcile.persistence.auth_models import AuthSession
from reconcile.persistence.session import tenant_session
from reconcile.persistence.workflow_events import FindingEvent
from reconcile.web.paths import FINDINGS_PATH, WORKFLOW_PATH

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture
workflow = workflow_fixture


@pytest.mark.parametrize("failure", ["membership", "user", "organization", "session", "expired"])
@pytest.mark.parametrize("operation", ["list", "assignees", "manage", "transition", "comments"])
def test_stale_authority_denies_all_workflow_access(auth, database, workflow, failure, operation):
    _, finding = workflow
    org, actor = context(auth)
    with Session(database.admin) as session, session.begin():
        if failure == "membership":
            session.execute(
                update(db.OrganizationMembership)
                .where(db.OrganizationMembership.organization_id == org)
                .values(status=db.RecordStatus.ARCHIVED)
            )
        elif failure == "user":
            session.execute(
                update(db.User).where(db.User.id == actor).values(status=db.RecordStatus.ARCHIVED)
            )
        elif failure == "organization":
            session.execute(
                update(db.Organization)
                .where(db.Organization.id == org)
                .values(status=db.RecordStatus.ARCHIVED)
            )
        elif failure == "session":
            raw = auth[1].cookies.get(auth[0].settings.session_cookie)
            session.execute(
                update(AuthSession)
                .where(AuthSession.token_hash == token_hash(raw))
                .values(revoked_at=auth[3].now)
            )
        else:
            auth[3].now += timedelta(days=1)
    if operation in {"list", "assignees"}:
        response = auth[1].get(
            FINDINGS_PATH if operation == "list" else f"{WORKFLOW_PATH}/assignees"
        )
    elif operation == "manage":
        response = change(auth, finding, due_at=auth[3].now.isoformat())
    elif operation == "transition":
        response = change(auth, finding, action="transition", target_status="IN_REVIEW")
    else:
        response = change(auth, finding, action="comments", text="Not permitted")
    assert response.status_code == (403 if failure in {"membership", "organization"} else 401)


@pytest.mark.parametrize("action", [None, "transition", "comments"])
@pytest.mark.parametrize("failure", ["csrf", "origin", "body_size", "extra", "nul", "surrogate"])
def test_workflow_request_boundaries(auth, workflow, action, failure):
    _, finding = workflow
    body = (
        {"expected_version": 1, "due_at": auth[3].now.isoformat()}
        if action is None
        else (
            {"expected_version": 1, "target_status": "RESOLVED", "resolution_note": "Investigated"}
            if action == "transition"
            else {"text": "Investigated"}
        )
    )
    headers = csrf(auth[1])
    if failure == "csrf":
        headers[CSRF_HEADER] = "forged"
    elif failure == "origin":
        headers["Origin"] = "https://untrusted.example.com"
    elif failure == "extra":
        body["actor_user_id"] = str(uuid4())
    else:
        value = (
            "x" * (17 * 1024)
            if failure == "body_size"
            else "bad\x00text"
            if failure == "nul"
            else "\ud800"
        )
        body[
            "due_at" if action is None else "resolution_note" if action == "transition" else "text"
        ] = value
    # Escape malformed Unicode so it reaches the API rather than failing in the client encoder.
    import json

    response = auth[1].request(
        "POST" if action else "PATCH",
        f"{FINDINGS_PATH}/{finding['id']}" + (f"/{action}" if action else ""),
        content=json.dumps(body),
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code == (
        403 if failure in {"csrf", "origin"} else 413 if failure == "body_size" else 422
    )
    assert detail(auth, finding)["version"] == 1
    assert not events(auth, finding)


@pytest.mark.parametrize(
    "query,status",
    [
        ({"limit": 0}, 422),
        ({"limit": 101}, 422),
        ({"cursor": "' OR 1=1;--"}, 400),
        ({"cursor": "a" * 257}, 422),
        ({"assignee": "not-a-uuid"}, 422),
        ({"status": "APPROVED"}, 422),
        ({"run_id": str(uuid4())}, 404),
        ({"assignee": str(uuid4())}, 404),
    ],
)
def test_queue_rejects_invalid_queries(auth, workflow, query, status):
    assert auth[1].get(FINDINGS_PATH, params=query).status_code == status


def test_queue_and_events_keyset_pagination(auth, workflow):
    _, finding = workflow
    full = auth[1].get(FINDINGS_PATH, params={"limit": 100}).json()["items"]
    gathered, cursor = [], None
    while True:
        page = (
            auth[1]
            .get(FINDINGS_PATH, params={"limit": 3, **({"cursor": cursor} if cursor else {})})
            .json()
        )
        gathered.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert [item["id"] for item in gathered] == [item["id"] for item in full]
    for index in range(5):
        assert change(auth, finding, action="comments", text=f"Comment {index}").status_code == 201
    gathered, cursor = [], None
    while True:
        page = (
            auth[1]
            .get(
                f"{FINDINGS_PATH}/{finding['id']}/events",
                params={"limit": 2, **({"cursor": cursor} if cursor else {})},
            )
            .json()
        )
        gathered += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(gathered) == 5 and len({event["id"] for event in gathered}) == 5


def test_organization_switch_never_reuses_old_workflow_or_directory(auth, database, workflow):
    _, finding = workflow
    _, actor = context(auth)
    with Session(database.admin) as session, session.begin():
        organization = db.Organization(name="Second organization", slug=f"second-{uuid4().hex}")
        session.add(organization)
        session.flush()
        second = organization.id
        session.add(
            db.OrganizationMembership(
                organization_id=second, user_id=actor, role=db.MembershipRole.MEMBER
            )
        )
    other = add_member(database, second)
    assert post(auth[1], "select-organization", {"organization_id": str(second)}).status_code == 200
    assert auth[1].get(FINDINGS_PATH).json()["items"] == []
    assert auth[1].get(f"{FINDINGS_PATH}/{finding['id']}").status_code == 404
    assert {
        item["user_id"] for item in auth[1].get(f"{WORKFLOW_PATH}/assignees").json()["items"]
    } == {str(actor), str(other)}


def test_post_lock_recheck_rejects_role_change(auth, database, workflow, monkeypatch):
    _, finding = workflow
    from reconcile.persistence.workflow import Workflow

    original = Workflow._finding

    def locked(session, organization, finding_id, *, lock=False):
        row = original(session, organization, finding_id, lock=lock)
        if lock:
            with database.admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE organization_memberships SET role='MEMBER' "
                        "WHERE organization_id=:org"
                    ),
                    {"org": organization},
                )
        return row

    monkeypatch.setattr(Workflow, "_finding", staticmethod(locked))
    assert change(auth, finding, due_at=auth[3].now.isoformat()).status_code == 403
    assert not events(auth, finding)


def test_database_roles_remain_separated_and_event_grants_narrow(auth, database, workflow):
    verify_database_role(database.runtime, identity=False)
    verify_database_role(database.identity, identity=True)
    for table in ("finding_events", "findings"):
        with pytest.raises(DBAPIError), database.identity.begin() as connection:
            connection.execute(text(f"SELECT * FROM {table}"))
    with database.runtime.connect() as connection:
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not connection.scalar(
                text("SELECT has_table_privilege(current_user, 'finding_events', :privilege)"),
                {"privilege": privilege},
            )
        assert not connection.scalar(
            text("SELECT has_table_privilege(current_user, 'users', 'SELECT')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege(current_user, 'findings', 'UPDATE')")
        )


@pytest.mark.parametrize(
    "changes", [{"details": []}, {"details": {"x": "x" * 2048}}, {"message": "x" * 4001}]
)
def test_event_database_content_constraints(auth, database, workflow, changes):
    _, finding = workflow
    org, actor = context(auth)
    fields = {
        "organization_id": org,
        "finding_id": UUID(finding["id"]),
        "actor_user_id": actor,
        "event_type": "COMMENT_ADDED",
        "request_id": uuid4(),
        "message": "Comment",
        "details": {},
    }
    with pytest.raises(IntegrityError), tenant_session(database.runtime, org) as session:
        session.add(FindingEvent(**(fields | changes)))


def test_snapshot_text_and_source_evidence_identical_after_workflow(auth, database, workflow):
    _, finding = workflow
    org, _ = context(auth)
    tables = (
        "source_files",
        "purchase_orders",
        "purchase_order_lines",
        "goods_receipts",
        "goods_receipt_lines",
        "invoices",
        "invoice_lines",
        "analysis_sources",
        "result_snapshots",
    )

    def capture():
        with database.admin.connect() as connection:
            return {
                table: connection.execute(
                    text(
                        f"SELECT row_to_json(t)::text FROM {table} t "
                        "WHERE organization_id=:org ORDER BY id"
                    ),
                    {"org": org},
                )
                .scalars()
                .all()
                for table in tables
            }

    before = capture()
    finding = change(
        auth,
        finding,
        action="transition",
        target_status="RESOLVED",
        resolution_note="Evidence reviewed",
    ).json()
    assert change(auth, finding, action="comments", text="Resolution context").status_code == 201
    assert change(auth, finding, action="transition", target_status="OPEN").status_code == 200
    assert capture() == before


def test_known_event_is_invisible_to_other_tenant_and_missing_context(auth, database, workflow):
    _, finding = workflow
    org, actor = context(auth)
    response = change(auth, finding, action="comments", text="Private workflow history")
    assert response.status_code == 201
    event_id = UUID(response.json()["id"])
    with tenant_session(database.runtime, org) as session:
        assert session.get(FindingEvent, event_id).actor_user_id == actor
    from test_auth import sign_in

    sign_in(auth)
    other, _ = context(auth)
    with tenant_session(database.runtime, other) as session:
        assert session.get(FindingEvent, event_id) is None
    with Session(database.runtime) as session:
        assert session.get(FindingEvent, event_id) is None
    with pytest.raises(DBAPIError), tenant_session(database.runtime, other) as session:
        session.add(
            FindingEvent(
                organization_id=org,
                finding_id=UUID(finding["id"]),
                actor_user_id=actor,
                event_type="COMMENT_ADDED",
                request_id=uuid4(),
                message="Forbidden",
                details={},
            )
        )
