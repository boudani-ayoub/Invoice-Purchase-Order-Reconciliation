from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import post, sign_in, upload_files
from test_runs import context, create, mutate
from test_workflow import actor_role, add_member, change

from reconcile.persistence import models as db
from reconcile.persistence.auth_models import AuthSession
from reconcile.persistence.base import Base
from reconcile.persistence.dashboard import overview_query, trends_query, workload_query
from reconcile.persistence.dashboard_policy import Period, ReportingWindow
from reconcile.persistence.session import tenant_session
from reconcile.persistence.workflow_events import FindingEvent
from reconcile.web.paths import DASHBOARD_PATH, FINDINGS_PATH

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture
ENDPOINTS = ("overview", "trends", "issues", "workload")


@pytest.fixture
def dashboard(auth, database):
    auth[3].now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    sign_in(auth)
    saved = create(auth).json()
    org, actor = context(auth)
    rows = auth[1].get(FINDINGS_PATH, params={"limit": 100}).json()["items"]
    with database.admin.begin() as connection:
        connection.execute(
            update(db.Finding)
            .where(db.Finding.organization_id == org)
            .values(
                status="RESOLVED",
                resolved_at=auth[3].now,
                resolved_by_user_id=actor,
                resolution_note="Private resolution note",
                created_at=auth[3].now - timedelta(days=120),
            )
        )
    return saved, rows, org, actor


def metric(auth, endpoint="overview", **params):
    response = auth[1].get(f"{DASHBOARD_PATH}/{endpoint}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def arrange(database, finding, **fields):
    if fields.get("status") in {"OPEN", "IN_REVIEW"}:
        fields.update(resolved_at=None, resolved_by_user_id=None, resolution_note=None)
    with database.admin.begin() as connection:
        connection.execute(
            update(db.Finding).where(db.Finding.id == UUID(finding["id"])).values(**fields)
        )


def event(database, dashboard, finding, event_type, when):
    _, _, org, actor = dashboard
    with Session(database.admin) as session, session.begin():
        session.add(
            FindingEvent(
                organization_id=org,
                finding_id=UUID(finding["id"]),
                actor_user_id=actor,
                request_id=uuid4(),
                created_at=when,
                updated_at=when,
                event_type=event_type,
                message="Private retained text"
                if event_type in {"RESOLVED", "COMMENT_ADDED"}
                else None,
                details={},
            )
        )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("role", list(db.MembershipRole))
def test_dashboard_roles_are_authoritative(auth, database, dashboard, endpoint, role):
    actor_role(auth, database, role)
    response = auth[1].get(f"{DASHBOARD_PATH}/{endpoint}")
    assert response.status_code == (403 if role == db.MembershipRole.MEMBER else 200)
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("window", list(ReportingWindow))
def test_empty_organization_and_bounded_zero_filled_trends(auth, window):
    sign_in(auth)
    payload = metric(auth, window=window)
    assert all(value == 0 for value in payload["backlog"].values())
    assert all(value == 0 for value in payload["activity"].values())
    assert all(value is None for value in payload["age"].values())
    trends = metric(auth, "trends", window=window)
    assert len(trends["items"]) == window.days
    assert all(
        row["new_findings"] == row["resolution_events"] == row["reopen_events"] == 0
        for row in trends["items"]
    )
    assert metric(auth, "issues")["items"] == []
    workload = metric(auth, "workload")
    assert workload["items"] == [] and workload["next_cursor"] is None
    assert workload["unassigned"]["unresolved"] == 0


def test_backlog_exact_clock_boundaries_and_archive(auth, database, dashboard):
    saved, rows, _, _ = dashboard
    now = auth[3].now
    arrange(database, rows[0], status="OPEN", due_at=now, reminder_at=now)
    arrange(
        database,
        rows[1],
        status="IN_REVIEW",
        due_at=now - timedelta(microseconds=1),
        reminder_at=now + timedelta(microseconds=1),
    )
    arrange(database, rows[2], due_at=now - timedelta(days=1), reminder_at=now - timedelta(days=1))
    payload = metric(auth)
    assert payload["server_now"] == now.isoformat()
    assert payload["backlog"] == {
        "open": 1,
        "in_review": 1,
        "unresolved": 2,
        "resolved": len(rows) - 2,
        "unassigned_unresolved": 2,
        "overdue": 1,
        "reminder_due": 1,
    }
    assert mutate(auth, saved["run"], action="archive").status_code == 200
    assert metric(auth)["backlog"] == payload["backlog"]
    assert sum(row["count"] for row in metric(auth, "issues")["items"]) == 2


@pytest.mark.parametrize(
    "ages,median,oldest",
    [([], None, None), ([20], 20, 20), ([10, 20, 90], 20, 90), ([10, 20, 40, 90], 30, 90)],
)
def test_unresolved_age_odd_even_and_empty(auth, database, dashboard, ages, median, oldest):
    _, rows, _, _ = dashboard
    for row, age in zip(rows, ages, strict=False):
        arrange(database, row, status="OPEN", created_at=auth[3].now - timedelta(seconds=age))
    assert metric(auth)["age"] == {
        "median_unresolved_age_seconds": median,
        "oldest_unresolved_age_seconds": oldest,
    }


@pytest.mark.parametrize(
    "boundary,offset,included",
    [("start", -1, False), ("start", 0, True), ("end", -1, True), ("end", 0, False)],
)
def test_activity_half_open_window_and_utc_buckets(
    auth, database, dashboard, boundary, offset, included
):
    _, rows, _, _ = dashboard
    period = Period.at(ReportingWindow.MONTH, auth[3].now)
    when = getattr(period, boundary) + timedelta(microseconds=offset)
    arrange(database, rows[0], created_at=when)
    event(database, dashboard, rows[0], "RESOLVED", when)
    event(database, dashboard, rows[0], "REOPENED", when)
    event(database, dashboard, rows[0], "COMMENT_ADDED", when)
    overview = metric(auth)
    assert overview["activity"] == {
        "new_findings": int(included),
        "resolution_events": int(included),
        "reopen_events": int(included),
    }
    trends = metric(auth, "trends")
    assert trends["period"] == overview["period"]
    for field in overview["activity"]:
        assert sum(row[field] for row in trends["items"]) == overview["activity"][field]
    if included:
        bucket = next(row for row in trends["items"] if row["new_findings"])
        assert (
            bucket["bucket_start"]
            == when.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        )


def test_resolution_actions_are_not_unique_or_currently_resolved_cases(auth, database, dashboard):
    _, rows, _, _ = dashboard
    finding = rows[0]
    arrange(database, finding, status="OPEN")
    for target in ("RESOLVED", "OPEN", "RESOLVED"):
        response = change(
            auth,
            finding,
            action="transition",
            target_status=target,
            **({"resolution_note": "Investigation"} if target == "RESOLVED" else {}),
        )
        assert response.status_code == 200
        finding = response.json()
        auth[3].now += timedelta(seconds=1)
    payload = metric(auth)
    assert payload["activity"]["resolution_events"] == 2
    assert payload["activity"]["reopen_events"] == 1
    assert payload["backlog"]["resolved"] == len(rows)
    assert payload["backlog"]["unresolved"] == 0


def test_workload_includes_inactive_assignment_and_unassigned_without_identity_leak(
    auth, database, dashboard
):
    _, rows, org, _ = dashboard
    members = sorted([add_member(database, org), add_member(database, org)])
    arrange(database, rows[0], status="OPEN")
    arrange(
        database,
        rows[1],
        status="OPEN",
        assignee_user_id=members[0],
        due_at=auth[3].now - timedelta(seconds=1),
    )
    arrange(database, rows[2], status="IN_REVIEW", assignee_user_id=members[0])
    arrange(database, rows[3], status="OPEN", assignee_user_id=members[1])
    with database.admin.begin() as connection:
        connection.execute(
            update(db.OrganizationMembership)
            .where(db.OrganizationMembership.user_id == members[0])
            .values(status="ARCHIVED")
        )
    page = metric(auth, "workload", limit=1)
    assert page["unassigned"]["unresolved"] == 1
    item = page["items"][0]
    assert item == {
        "assignee_user_id": str(members[0]),
        "display_name": "<script>member</script>",
        "active": False,
        "role": "MEMBER",
        "open": 1,
        "in_review": 1,
        "unresolved": 2,
        "overdue": 1,
    }
    assert page["next_cursor"] == str(members[0])
    following = metric(auth, "workload", limit=1, cursor=page["next_cursor"])
    assert following["items"][0]["assignee_user_id"] == str(members[1])
    assert following["next_cursor"] is None
    assert following["unassigned"] == page["unassigned"]


def test_issue_mix_uses_codes_categories_and_current_unresolved_only(auth, database, dashboard):
    _, rows, _, _ = dashboard
    arrange(database, rows[0], status="OPEN")
    arrange(
        database, rows[1], status="IN_REVIEW", code=rows[0]["code"], category=rows[0]["category"]
    )
    assert metric(auth, "issues")["items"] == [
        {"code": rows[0]["code"], "category": rows[0]["category"], "count": 2}
    ]


@pytest.mark.parametrize(
    "endpoint,query",
    [
        ("overview", {"window": "365d"}),
        ("trends", {"window": "' OR 1=1;--"}),
        ("issues", {"organization_id": str(uuid4())}),
        ("workload", {"limit": 101}),
        ("workload", {"limit": 0}),
        ("workload", {"cursor": "bad"}),
        ("overview", {"run_id": str(uuid4())}),
    ],
)
def test_dashboard_queries_are_narrow(auth, dashboard, endpoint, query):
    assert auth[1].get(f"{DASHBOARD_PATH}/{endpoint}", params=query).status_code == 422


@pytest.mark.parametrize(
    "failure", ["revoked", "expired", "user", "organization", "membership", "role"]
)
def test_live_access_changes_apply_to_every_dashboard_read(auth, database, dashboard, failure):
    _, _, org, actor = dashboard
    with database.admin.begin() as connection:
        if failure in {"revoked", "expired"}:
            fields = (
                {"revoked_at": auth[3].now}
                if failure == "revoked"
                else {"idle_expires_at": auth[3].now - timedelta(seconds=1)}
            )
            connection.execute(
                update(AuthSession).where(AuthSession.user_id == actor).values(**fields)
            )
        elif failure == "user":
            connection.execute(update(db.User).where(db.User.id == actor).values(status="ARCHIVED"))
        elif failure == "organization":
            connection.execute(
                update(db.Organization).where(db.Organization.id == org).values(status="ARCHIVED")
            )
        else:
            fields = {"role": "MEMBER"} if failure == "role" else {"status": "ARCHIVED"}
            connection.execute(
                update(db.OrganizationMembership)
                .where(
                    db.OrganizationMembership.organization_id == org,
                    db.OrganizationMembership.user_id == actor,
                )
                .values(**fields)
            )
    expected = 401 if failure in {"revoked", "expired", "user"} else 403
    for endpoint in ENDPOINTS:
        response = auth[1].get(f"{DASHBOARD_PATH}/{endpoint}")
        assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
        assert "backlog" not in response.text and "Private" not in response.text


def test_cross_tenant_counts_labels_events_and_switch(auth, database, dashboard):
    _, rows, org, actor = dashboard
    arrange(database, rows[0], status="OPEN", assignee_user_id=actor)
    event(database, dashboard, rows[0], "RESOLVED", auth[3].now - timedelta(seconds=1))
    own = {endpoint: metric(auth, endpoint) for endpoint in ENDPOINTS}
    own_cookie = auth[1].cookies.get(auth[0].settings.session_cookie)
    auth[1].cookies.clear()
    sign_in(auth)
    foreign_org, foreign_actor = context(auth)
    foreign_run = create(auth).json()
    foreign_rows = auth[1].get(FINDINGS_PATH, params={"limit": 100}).json()["items"]
    event(
        database,
        (foreign_run, foreign_rows, foreign_org, foreign_actor),
        foreign_rows[0],
        "REOPENED",
        auth[3].now - timedelta(seconds=1),
    )
    foreign_member = add_member(database, foreign_org, user_active=False)
    arrange(database, foreign_rows[0], assignee_user_id=foreign_member)
    foreign = metric(auth, "workload")
    assert foreign["items"][0]["active"] is False
    auth[1].cookies.set(
        auth[0].settings.session_cookie, own_cookie, domain="testserver.local", path="/"
    )
    assert {endpoint: metric(auth, endpoint) for endpoint in ENDPOINTS} == own
    assert str(foreign_member) not in str(own) and foreign_run["run"]["id"] not in str(own)
    with Session(database.admin) as session, session.begin():
        session.add(
            db.OrganizationMembership(organization_id=foreign_org, user_id=actor, role="AP_MANAGER")
        )
    assert (
        post(auth[1], "select-organization", {"organization_id": str(foreign_org)}).status_code
        == 200
    )
    assert metric(auth)["backlog"]["unresolved"] == len(foreign_rows)
    assert metric(auth)["activity"]["resolution_events"] == 0
    assert metric(auth)["activity"]["reopen_events"] == 1
    assert metric(auth, "workload") == foreign
    auth[1].cookies.set(
        auth[0].settings.session_cookie, own_cookie, domain="testserver.local", path="/"
    )
    assert auth[1].get(f"{DASHBOARD_PATH}/overview").status_code == 401


def test_dashboard_queries_fail_closed_without_or_with_wrong_rls_context(auth, database, dashboard):
    _, rows, org, _ = dashboard
    arrange(database, rows[0], status="OPEN")
    period = Period.at(ReportingWindow.MONTH, auth[3].now)
    for tenant in (None, uuid4()):
        manager = (
            Session(database.runtime)
            if tenant is None
            else tenant_session(database.runtime, tenant)
        )
        with manager as session:
            assert (
                session.execute(overview_query(org, auth[3].now, period))
                .mappings()
                .one()["unresolved"]
                == 0
            )
            assert session.execute(trends_query(org, period)).all() == []
            workload = session.execute(workload_query(org, auth[3].now, 25, None)).mappings().all()
            assert len(workload) == 1 and workload[0]["unresolved"] == 0


def test_reads_preserve_every_tenant_row_and_do_not_reanalyze(
    auth, database, dashboard, monkeypatch
):
    _, rows, org, _ = dashboard
    event(database, dashboard, rows[0], "COMMENT_ADDED", auth[3].now)

    def state():
        with database.admin.connect() as connection:
            return {
                table.name: sorted(
                    repr(tuple(row))
                    for row in connection.execute(
                        select(table).where(table.c.organization_id == org)
                    )
                )
                for table in Base.metadata.sorted_tables
                if "organization_id" in table.c
            }

    before = state()
    monkeypatch.setattr(
        "reconcile.web.runs.render_records", lambda *_: pytest.fail("Dashboard must not reanalyze")
    )
    for endpoint in ENDPOINTS:
        payload = metric(auth, endpoint)
        assert "Private" not in str(payload)
        assert "email" not in str(payload)
        assert "amount" not in str(payload) and "currency" not in str(payload)
    assert state() == before


def test_future_created_timestamp_preserves_signed_age(auth, database, dashboard):
    arrange(database, dashboard[1][0], status="OPEN", created_at=auth[3].now + timedelta(seconds=1))
    assert metric(auth)["age"]["median_unresolved_age_seconds"] == -1


def test_saved_run_without_findings_is_not_a_zero_dollar_metric(auth):
    sign_in(auth)
    files = {
        field: (name, b"\n".join(content.splitlines()[:2]) + b"\n", mime)
        for field, (name, content, mime) in upload_files().items()
    }
    saved = create(auth, files=files)
    assert saved.status_code == 201
    assert saved.json()["report"]["summary"]["review_required_lines"] == 0
    assert all(count == 0 for count in metric(auth)["backlog"].values())
    assert metric(auth)["age"]["oldest_unresolved_age_seconds"] is None
    assert metric(auth, "issues")["items"] == []
    assert metric(auth, "workload")["unassigned"]["unresolved"] == 0


def test_workload_time_does_not_move_during_label_lookup(auth, database, dashboard, monkeypatch):
    import reconcile.persistence.dashboard as module

    _, rows, _, actor = dashboard
    now = auth[3].now
    arrange(
        database, rows[0], status="OPEN", assignee_user_id=actor, due_at=now + timedelta(seconds=1)
    )
    original = module.member_labels

    def delayed(*args):
        auth[3].now += timedelta(seconds=2)
        return original(*args)

    monkeypatch.setattr(module, "member_labels", delayed)
    payload = metric(auth, "workload")
    assert payload["server_now"] == now.isoformat()
    assert payload["items"][0]["overdue"] == 0
