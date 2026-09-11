from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in
from test_runs import context, create, csrf, mutate

from reconcile.auth.policy import Permission
from reconcile.auth.service_errors import AuthError
from reconcile.persistence import models as db
from reconcile.persistence import workflow_events
from reconcile.persistence.session import tenant_session
from reconcile.persistence.workflow import Workflow
from reconcile.persistence.workflow_events import FindingEvent
from reconcile.web.paths import FINDINGS_PATH, WORKFLOW_PATH

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


@pytest.fixture
def workflow(auth):
    sign_in(auth)
    saved = create(auth).json()
    response = auth[1].get(FINDINGS_PATH, params={"run_id": saved["run"]["id"], "limit": 100})
    assert response.status_code == 200, response.text
    assert response.json()["items"]
    return saved, response.json()["items"][0]


def change(auth, finding, *, action=None, **body):
    return auth[1].request(
        "POST" if action else "PATCH",
        f"{FINDINGS_PATH}/{finding['id']}" + (f"/{action}" if action else ""),
        json=({"expected_version": finding["version"]} if action != "comments" else {}) | body,
        headers=csrf(auth[1]),
    )


def detail(auth, finding):
    return auth[1].get(f"{FINDINGS_PATH}/{finding['id']}").json()["finding"]


def events(auth, finding):
    return auth[1].get(f"{FINDINGS_PATH}/{finding['id']}/events").json()["items"]


def add_member(database, organization, *, active=True, user_active=True):
    with Session(database.admin) as session, session.begin():
        user = db.User(
            email=f"worker-{uuid4().hex}@example.com",
            display_name="<script>member</script>",
            status=db.RecordStatus.ACTIVE if user_active else db.RecordStatus.ARCHIVED,
        )
        session.add(user)
        session.flush()
        session.add(
            db.OrganizationMembership(
                organization_id=organization,
                user_id=user.id,
                role=db.MembershipRole.MEMBER,
                status=db.RecordStatus.ACTIVE if active else db.RecordStatus.ARCHIVED,
            )
        )
        return user.id


def actor_role(auth, database, role):
    org, actor = context(auth)
    with Session(database.admin) as session, session.begin():
        session.execute(
            update(db.OrganizationMembership)
            .where(
                db.OrganizationMembership.organization_id == org,
                db.OrganizationMembership.user_id == actor,
            )
            .values(role=role)
        )


def test_assignment_schedule_resolution_reopen_history_and_snapshot(auth, database, workflow):
    saved, finding = workflow
    organization, actor = context(auth)
    member = add_member(database, organization)
    when = (auth[3].now - timedelta(hours=1)).isoformat()
    response = change(auth, finding, assignee_user_id=str(member), due_at=when, reminder_at=when)
    assert response.status_code == 200, response.text
    finding = response.json()
    assert finding["version"] == 2 and finding["overdue"] and finding["reminder_due"]
    assert len(events(auth, finding)) == 3
    response = change(auth, finding, action="transition", target_status="IN_REVIEW")
    assert response.status_code == 200
    finding = response.json()
    response = change(
        auth,
        finding,
        action="transition",
        target_status="RESOLVED",
        resolution_note="Supplier clarified the evidence.",
    )
    assert response.status_code == 200, response.text
    finding = response.json()
    assert not finding["overdue"] and not finding["reminder_due"]
    assert finding["resolved_by_user_id"] == str(actor)
    assert finding["resolved_at"] == auth[3].now.isoformat()
    response = change(auth, finding, action="transition", target_status="OPEN")
    assert response.status_code == 200
    current = detail(auth, finding)
    assert current["version"] == 5 and current["status"] == "OPEN"
    assert current["resolution_note"] is None and current["resolved_at"] is None
    assert current["assignee_user_id"] == str(member)
    timeline = events(auth, finding)
    resolved = next(event for event in timeline if event["event_type"] == "RESOLVED")
    assert resolved["message"] == "Supplier clarified the evidence."
    assert resolved["actor_user_id"] == str(actor)
    assert resolved["created_at"] == auth[3].now.isoformat()
    assert all(event["actor_user_id"] == str(actor) for event in timeline)
    assert auth[1].get(f"/api/v1/runs/{saved['run']['id']}").json()["report"] == saved["report"]
    assert mutate(auth, saved["run"], action="archive").status_code == 200
    assert detail(auth, finding)["run"]["archived"] is True
    assert len(events(auth, finding)) == 6
    with tenant_session(database.runtime, organization) as session:
        assert (
            session.scalar(
                select(db.ResultSnapshot.report).where(
                    db.ResultSnapshot.analysis_run_id == UUID(saved["run"]["id"])
                )
            )
            == saved["report"]
        )


@pytest.mark.parametrize("role", list(db.MembershipRole))
@pytest.mark.parametrize("assigned", [False, True])
def test_roles_self_scope_and_direct_open_resolution(auth, database, workflow, role, assigned):
    _, finding = workflow
    _, actor = context(auth)
    if assigned:
        finding = change(auth, finding, assignee_user_id=str(actor)).json()
    actor_role(auth, database, role)
    assert auth[1].get(FINDINGS_PATH).status_code == 200
    assert change(auth, finding, action="comments", text="Investigating").status_code == 201
    managed = change(auth, finding, due_at=auth[3].now.isoformat())
    if role == db.MembershipRole.MEMBER:
        assert managed.status_code == 403
    else:
        assert managed.status_code == 200
        finding = managed.json()
    response = change(
        auth,
        finding,
        action="transition",
        target_status="RESOLVED",
        resolution_note="Checked source with supplier.",
    )
    assert response.status_code == (
        403 if role == db.MembershipRole.MEMBER and not assigned else 200
    )
    if response.status_code == 200:
        assert (
            change(auth, response.json(), action="transition", target_status="OPEN").status_code
            == 200
        )


@pytest.mark.parametrize("kind", ["foreign", "missing", "inactive_membership", "inactive_user"])
def test_invalid_assignee_is_indistinguishable(auth, database, workflow, kind):
    _, finding = workflow
    org, _ = context(auth)
    if kind == "foreign":
        with Session(database.admin) as session, session.begin():
            other = db.Organization(name="Private org", slug=f"other-{uuid4().hex}")
            session.add(other)
            session.flush()
            org = other.id
    user = (
        uuid4()
        if kind == "missing"
        else add_member(
            database, org, active=kind != "inactive_membership", user_active=kind != "inactive_user"
        )
    )
    response = change(auth, finding, assignee_user_id=str(user))
    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Active organization member not found.",
    }
    assert detail(auth, finding)["version"] == 1
    assert not events(auth, finding)


def test_inactivated_assignee_is_preserved_and_can_be_unassigned(auth, database, workflow):
    _, finding = workflow
    org, _ = context(auth)
    user = add_member(database, org)
    finding = change(auth, finding, assignee_user_id=str(user)).json()
    with Session(database.admin) as session, session.begin():
        session.execute(
            update(db.OrganizationMembership)
            .where(db.OrganizationMembership.user_id == user)
            .values(status=db.RecordStatus.ARCHIVED)
        )
    assert detail(auth, finding)["assignee_user_id"] == str(user)
    assert detail(auth, finding)["assignee"] == {
        "display_name": "<script>member</script>",
        "active": False,
    }
    assert change(auth, finding, assignee_user_id=None).status_code == 200
    assert any(event["metadata"].get("new") == str(user) for event in events(auth, finding))


def test_picker_is_narrow_scoped_active_and_paginated(auth, database, workflow):
    org, actor = context(auth)
    active = add_member(database, org)
    add_member(database, org, active=False)
    add_member(database, org, user_active=False)
    items, cursor = [], None
    while True:
        response = auth[1].get(
            f"{WORKFLOW_PATH}/assignees",
            params={"limit": 1, **({"cursor": cursor} if cursor else {})},
        )
        assert response.status_code == 200
        items += response.json()["items"]
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break
    assert {item["user_id"] for item in items} == {str(actor), str(active)}
    assert all(set(item) == {"user_id", "display_name", "role"} for item in items)
    assert (
        next(item for item in items if item["user_id"] == str(active))["display_name"]
        == "<script>member</script>"
    )


@pytest.mark.parametrize(
    "operation", ["detail", "events", "manage", "transition", "comments", "run_filter"]
)
def test_cross_tenant_resources_are_404(auth, database, workflow, operation):
    saved, finding = workflow
    sign_in(auth)
    if operation == "detail":
        response = auth[1].get(f"{FINDINGS_PATH}/{finding['id']}")
    elif operation == "events":
        response = auth[1].get(f"{FINDINGS_PATH}/{finding['id']}/events")
    elif operation == "run_filter":
        response = auth[1].get(FINDINGS_PATH, params={"run_id": saved["run"]["id"]})
    elif operation == "manage":
        response = change(auth, finding, due_at=auth[3].now.isoformat())
    elif operation == "transition":
        response = change(auth, finding, action="transition", target_status="IN_REVIEW")
    else:
        response = change(auth, finding, action="comments", text="Forbidden")
    assert response.status_code == 404, response.text
    assert auth[1].get(FINDINGS_PATH).json()["items"] == []


@pytest.mark.parametrize("action", [None, "transition"])
def test_stale_version_rejects_without_event(auth, workflow, action):
    _, finding = workflow
    assert change(auth, finding, due_at=auth[3].now.isoformat()).status_code == 200
    before = events(auth, finding)
    response = change(
        auth,
        finding,
        action=action,
        **({"target_status": "IN_REVIEW"} if action else {"reminder_at": auth[3].now.isoformat()}),
    )
    assert response.status_code == 409
    assert events(auth, finding) == before


def test_concurrent_writers_one_wins_one_conflicts(auth, database, workflow):
    _, finding = workflow
    raw = auth[1].cookies.get(auth[0].settings.session_cookie)
    service = Workflow(auth[0].sessions)
    # Independent runtime connections exercise row locking, not a one-connection pool queue.
    from threading import Barrier

    from sqlalchemy import create_engine

    ready = Barrier(2)

    engine = create_engine(database.runtime.url, pool_size=2, hide_parameters=True)
    original = auth[0].sessions.tenant
    auth[0].sessions.tenant = engine

    def edit():
        ready.wait(timeout=10)
        try:
            service.transition(
                raw, UUID(finding["id"]), 1, db.FindingStatus.IN_REVIEW, None, uuid4()
            )
            return 200
        except AuthError as error:
            return error.status

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: edit(), range(2))) == [200, 409]
    finally:
        auth[0].sessions.tenant = original
        engine.dispose()
    assert len(events(auth, finding)) == 1


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_due_and_reminder_boundaries_are_server_clock_derived(auth, workflow, offset):
    _, finding = workflow
    value = (auth[3].now + timedelta(seconds=offset)).isoformat()
    current = change(auth, finding, due_at=value, reminder_at=value).json()
    assert current["overdue"] is (offset < 0)
    assert current["reminder_due"] is (offset <= 0)
    for flag, expected in (("overdue", offset < 0), ("reminder_due", offset <= 0)):
        response = auth[1].get(FINDINGS_PATH, params={flag: "true"})
        assert (finding["id"] in {item["id"] for item in response.json()["items"]}) is expected
        response = auth[1].get(FINDINGS_PATH, params={flag: "false", "limit": 100})
        assert (finding["id"] in {item["id"] for item in response.json()["items"]}) is not expected


def test_detail_reports_the_same_clock_sample_used_for_due_flags(auth, workflow, monkeypatch):
    _, finding = workflow
    checked_at = auth[3].now
    when = (checked_at + timedelta(seconds=1)).isoformat()
    assert change(auth, finding, due_at=when, reminder_at=when).status_code == 200
    original = Workflow._assignee_labels

    def delayed_labels(self, organization, findings):
        auth[3].now += timedelta(seconds=2)
        return original(self, organization, findings)

    monkeypatch.setattr(Workflow, "_assignee_labels", delayed_labels)
    response = auth[1].get(f"{FINDINGS_PATH}/{finding['id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["server_now"] == checked_at.isoformat()
    assert not payload["finding"]["overdue"] and not payload["finding"]["reminder_due"]


def test_comments_append_escape_plain_text_and_do_not_change_version(auth, workflow):
    _, finding = workflow
    markup = '<img src=x onerror="window.workflowXss=true"> é 🧾'
    for _ in range(2):
        response = change(auth, finding, action="comments", text=f" {markup}\n")
        assert response.status_code == 201
        assert response.json()["message"] == markup
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert response.json()["metadata"] == {}
    assert len(events(auth, finding)) == 2
    assert detail(auth, finding)["version"] == 1


@pytest.mark.parametrize("action", [None, "transition", "comments"])
def test_workflow_event_failure_rolls_back_and_never_logs_content(
    auth, workflow, monkeypatch, caplog, action
):
    _, finding = workflow
    sensitive = "private investigation text"

    def fail(*args, **kwargs):
        raise RuntimeError(sensitive)

    monkeypatch.setattr(workflow_events, "record_event", fail)
    body = (
        {"due_at": auth[3].now.isoformat()}
        if action is None
        else (
            {"target_status": "RESOLVED", "resolution_note": sensitive}
            if action == "transition"
            else {"text": sensitive}
        )
    )
    response = change(auth, finding, action=action, **body)
    assert response.status_code == 500
    assert sensitive not in response.text and sensitive not in caplog.text
    current = detail(auth, finding)
    assert current["version"] == 1 and current["due_at"] is None and current["status"] == "OPEN"
    assert not events(auth, finding)


@pytest.mark.parametrize("role", ["runtime", "admin"])
@pytest.mark.parametrize(
    "operation", ["UPDATE finding_events SET message='tampered'", "DELETE FROM finding_events"]
)
def test_event_rows_reject_mutation_even_privileged(auth, database, workflow, role, operation):
    _, finding = workflow
    assert (
        change(auth, finding, action="comments", text="Permanent business comment").status_code
        == 201
    )
    org, _ = context(auth)
    with pytest.raises(DBAPIError):
        if role == "runtime":
            with tenant_session(database.runtime, org) as session:
                session.execute(text(operation))
        else:
            with database.admin.begin() as connection:
                connection.execute(text(operation))


def test_event_and_assignment_composite_foreign_keys(auth, database, workflow):
    _, first = workflow
    org, actor = context(auth)
    sign_in(auth)
    _, foreign_actor = context(auth)
    second_saved = create(auth).json()
    foreign_finding = auth[1].get(FINDINGS_PATH).json()["items"][0]
    for actor_id, finding_id in ((foreign_actor, first["id"]), (actor, foreign_finding["id"])):
        with pytest.raises(IntegrityError), Session(database.admin) as session, session.begin():
            session.add(
                FindingEvent(
                    organization_id=org,
                    finding_id=UUID(finding_id),
                    actor_user_id=actor_id,
                    event_type="COMMENT_ADDED",
                    request_id=uuid4(),
                    message="No",
                    details={},
                )
            )
    with pytest.raises(IntegrityError), Session(database.admin) as session, session.begin():
        session.execute(
            update(db.Finding)
            .where(db.Finding.id == UUID(first["id"]))
            .values(assignee_user_id=foreign_actor)
        )
    with tenant_session(database.runtime, org) as session:
        assert session.get(db.Finding, UUID(foreign_finding["id"])) is None
        assert not session.scalars(
            select(FindingEvent).where(FindingEvent.finding_id == UUID(foreign_finding["id"]))
        ).all()
    assert second_saved["run"]["id"] != first["analysis_run_id"]


@pytest.mark.parametrize(
    "column,value",
    [
        ("code", "UNKNOWN_PO"),
        ("category", "REFERENCE"),
        ("analysis_run_id", str(uuid4())),
        ("invoice_line_id", None),
    ],
)
def test_runtime_cannot_mutate_finding_evidence(auth, database, workflow, column, value):
    _, finding = workflow
    org, _ = context(auth)
    with pytest.raises(DBAPIError), tenant_session(database.runtime, org) as session:
        session.execute(
            update(db.Finding)
            .where(db.Finding.id == UUID(finding["id"]))
            .values(**{column: UUID(value) if column == "analysis_run_id" else value})
        )


def test_permission_map_does_not_give_members_manager_powers():
    from reconcile.auth.policy import ROLE_PERMISSIONS

    member = ROLE_PERMISSIONS[db.MembershipRole.MEMBER]
    assert (
        Permission.MANAGE_FINDING not in member and Permission.TRANSITION_ANY_FINDING not in member
    )


@pytest.mark.parametrize(
    "start,target",
    [
        ("OPEN", "OPEN"),
        ("IN_REVIEW", "OPEN"),
        ("IN_REVIEW", "IN_REVIEW"),
        ("RESOLVED", "IN_REVIEW"),
    ],
)
def test_unsupported_transitions_are_explicitly_rejected(auth, workflow, start, target):
    _, finding = workflow
    if start != "OPEN":
        fields = {"resolution_note": "Evidence reviewed."} if start == "RESOLVED" else {}
        finding = change(auth, finding, action="transition", target_status=start, **fields).json()
    before = events(auth, finding)
    assert change(auth, finding, action="transition", target_status=target).status_code == 422
    assert events(auth, finding) == before


def test_noop_management_does_not_increment_version_or_create_history(auth, workflow):
    _, finding = workflow
    assert change(auth, finding, assignee_user_id=None).status_code == 422
    assert detail(auth, finding)["version"] == 1 and not events(auth, finding)
