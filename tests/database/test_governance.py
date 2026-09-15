from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_auth import (
    PASSWORD,
    post,
    sign_in,
)
from test_auth import (
    auth as auth_fixture,
)
from test_auth import (
    passwords as passwords_fixture,
)
from test_runs import create
from test_workflow import change

from reconcile.auth.config import AUTH_PATH, CSRF_HEADER
from reconcile.auth.crypto import token_hash
from reconcile.auth.policy import Permission
from reconcile.auth.service_errors import AuthError
from reconcile.persistence import models as db
from reconcile.persistence.auth_models import (
    GovernanceEvent,
    OrganizationInvitation,
    UserCredential,
)
from reconcile.web.paths import FINDINGS_PATH

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture
ADMIN_PATH = "/api/v1/admin"


def csrf(client):
    return {CSRF_HEADER: client.get(f"{AUTH_PATH}/csrf").json()["csrf_token"]}


def admin_context(auth):
    email, raw = sign_in(auth)
    principal = auth[0].sessions.authenticate(raw)
    return email, raw, principal.active_organization_id, principal.user_id


def seed_member(auth, database, organization, *, role=db.MembershipRole.MEMBER, status=None):
    email = f"member-{uuid4().hex}@example.com"
    with Session(database.admin) as session, session.begin():
        user = db.User(
            email=email,
            display_name="<script>member label</script>",
            email_verified_at=auth[3](),
        )
        session.add(user)
        session.flush()
        session.add(
            UserCredential(
                user_id=user.id,
                password_hash=auth[0].accounts.passwords.hash(PASSWORD),
                password_updated_at=auth[3](),
            )
        )
        membership = db.OrganizationMembership(
            organization_id=organization,
            user_id=user.id,
            role=role,
            status=status or db.RecordStatus.ACTIVE,
        )
        session.add(membership)
        session.flush()
        return email, user.id, membership.id


def login(auth, email):
    response = post(auth[1], "login", {"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return auth[1].cookies.get(auth[0].settings.session_cookie)


def invite(auth, email, role="MEMBER"):
    return auth[1].post(
        f"{ADMIN_PATH}/invitations",
        json={"email": email, "role": role},
        headers=csrf(auth[1]),
    )


def patch_member(auth, user_id, version, **changes):
    return auth[1].patch(
        f"{ADMIN_PATH}/members/{user_id}",
        json={"expected_version": version, **changes},
        headers=csrf(auth[1]),
    )


@pytest.mark.parametrize("role", [db.MembershipRole.MEMBER, db.MembershipRole.AP_MANAGER])
def test_admin_endpoints_enforce_explicit_role_permissions(auth, database, role):
    _, _, organization, _ = admin_context(auth)
    email, _, _ = seed_member(auth, database, organization, role=role)
    login(auth, email)
    for path in ("organization", "members", "invitations", "audit"):
        assert auth[1].get(f"{ADMIN_PATH}/{path}").status_code == 403
    assert invite(auth, f"forbidden-{uuid4().hex}@example.com").status_code == 403


def test_member_directory_lifecycle_and_live_permission_changes(auth, database):
    _, admin_raw, organization, _ = admin_context(auth)
    email, user_id, _ = seed_member(auth, database, organization)
    with Session(database.admin) as session, session.begin():
        foreign = db.Organization(name="Foreign", slug=f"foreign-{uuid4().hex}")
        session.add(foreign)
        session.flush()
        foreign_id = foreign.id
    foreign_email, _, _ = seed_member(auth, database, foreign_id)

    response = auth[1].get(f"{ADMIN_PATH}/members", params={"limit": 1})
    assert response.status_code == 200
    first = response.json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = (
        auth[1]
        .get(f"{ADMIN_PATH}/members", params={"limit": 100, "cursor": first["next_cursor"]})
        .json()
    )
    directory = first["items"] + second["items"]
    assert email in {item["email"] for item in directory}
    assert foreign_email not in {item["email"] for item in directory}
    assert "<script>" in next(item for item in directory if item["email"] == email)["display_name"]

    promoted = patch_member(auth, user_id, 1, role="AP_MANAGER")
    assert promoted.status_code == 200 and promoted.json()["version"] == 2
    assert patch_member(auth, user_id, 1, role="MEMBER").status_code == 409
    member_raw = auth[0].accounts.login(email, PASSWORD, None).token
    assert auth[0].sessions.authorize(member_raw, Permission.VIEW_MANAGER_DASHBOARD)

    auth[1].cookies.set(auth[0].settings.session_cookie, admin_raw)
    demoted = patch_member(auth, user_id, 2, role="MEMBER")
    assert demoted.status_code == 200
    with pytest.raises(AuthError):
        auth[0].sessions.authorize(member_raw, Permission.VIEW_MANAGER_DASHBOARD)
    inactive = patch_member(auth, user_id, 3, status="ARCHIVED")
    assert inactive.status_code == 200 and inactive.json()["status"] == "ARCHIVED"
    with pytest.raises(AuthError):
        auth[0].sessions.authorize_analysis(member_raw)
    active = patch_member(auth, user_id, 4, status="ACTIVE")
    assert active.status_code == 200 and active.json()["version"] == 5

    with Session(database.admin) as session:
        assert session.get(db.User, user_id).status == db.RecordStatus.ACTIVE


def test_last_active_admin_is_serialized_for_single_and_concurrent_updates(auth, database):
    _, first_raw, organization, first_id = admin_context(auth)
    assert patch_member(auth, first_id, 1, role="MEMBER").json()["error"] == "last_active_admin"
    assert patch_member(auth, first_id, 1, status="ARCHIVED").json()["error"] == "last_active_admin"
    second_email, second_id, _ = seed_member(
        auth, database, organization, role=db.MembershipRole.ORG_ADMIN
    )
    second_raw = auth[0].accounts.login(second_email, PASSWORD, None).token

    def demote(target):
        raw, user_id = target
        try:
            auth[0].governance.update_member(
                raw,
                user_id=user_id,
                expected_version=1,
                role=db.MembershipRole.MEMBER,
                status=None,
                request_id=uuid4(),
            )
            return True
        except AuthError as error:
            assert error.code in {"last_active_admin", "forbidden"}
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(demote, [(first_raw, first_id), (second_raw, second_id)]))
    assert sum(outcomes) == 1
    with Session(database.admin) as session:
        active_admins = session.scalar(
            select(func.count())
            .select_from(db.OrganizationMembership)
            .where(
                db.OrganizationMembership.organization_id == organization,
                db.OrganizationMembership.role == db.MembershipRole.ORG_ADMIN,
                db.OrganizationMembership.status == db.RecordStatus.ACTIVE,
            )
        )
        assert active_admins == 1


def test_invitation_creation_normalization_hash_only_and_revoke_contract(auth, database, caplog):
    admin_email, _, _, _ = admin_context(auth)
    email = f"invite-{uuid4().hex}@example.com"
    response = invite(auth, email.upper(), "AP_MANAGER")
    assert response.status_code == 201, response.text
    raw = auth[2].token()
    payload = response.json()
    assert payload["email"] == email and payload["role"] == "AP_MANAGER"
    assert raw not in response.text + caplog.text
    with Session(database.admin) as session:
        stored = session.get(OrganizationInvitation, UUID(payload["id"]))
        assert stored.token_hash == token_hash(raw) and stored.token_hash != raw
    assert invite(auth, email).status_code == 409
    assert invite(auth, email, "NOT_A_ROLE").status_code == 422

    auth[3].now += timedelta(seconds=auth[0].settings.invitation_seconds)
    assert post(auth[1], "invitations/preview", {"token": raw}).status_code == 400
    login(auth, admin_email)
    revoked = auth[1].post(
        f"{ADMIN_PATH}/invitations/{payload['id']}/revoke",
        json={"expected_version": 1},
        headers=csrf(auth[1]),
    )
    assert revoked.status_code == 200 and revoked.json()["status"] == "REVOKED"
    repeated = auth[1].post(
        f"{ADMIN_PATH}/invitations/{payload['id']}/revoke",
        json={"expected_version": 2},
        headers=csrf(auth[1]),
    )
    assert repeated.status_code == 409


def test_existing_account_accepts_once_without_changing_active_organization(auth, database):
    _, admin_raw, organization, _ = admin_context(auth)
    with Session(database.admin) as session, session.begin():
        other = db.Organization(name="Existing home", slug=f"existing-{uuid4().hex}")
        session.add(other)
        session.flush()
        other_id = other.id
    email, user_id, _ = seed_member(auth, database, other_id)
    response = invite(auth, email, "AP_MANAGER")
    assert response.status_code == 201
    raw_invitation = auth[2].token()
    user_raw = auth[0].accounts.login(email, PASSWORD, None).token

    accepted = auth[0].governance.accept_invitation(raw_invitation, user_raw, request_id=uuid4())
    assert accepted["organization_id"] == str(organization)
    principal = auth[0].sessions.authenticate(user_raw)
    assert principal.active_organization_id == other_id
    assert {membership.organization_id for membership in principal.memberships} == {
        organization,
        other_id,
    }
    with pytest.raises(AuthError):
        auth[0].governance.accept_invitation(raw_invitation, user_raw, request_id=uuid4())

    auth[1].cookies.set(auth[0].settings.session_cookie, admin_raw)
    with Session(database.admin) as session:
        membership = session.scalar(
            select(db.OrganizationMembership).where(
                db.OrganizationMembership.organization_id == organization,
                db.OrganizationMembership.user_id == user_id,
            )
        )
        assert membership.role == db.MembershipRole.AP_MANAGER


def test_invitation_rejects_email_mismatch_and_new_registration_uses_invited_role(auth, database):
    _, _, organization, _ = admin_context(auth)
    email = f"new-{uuid4().hex}@example.com"
    assert invite(auth, email, "ORG_ADMIN").status_code == 201
    raw = auth[2].token()
    other_email, other_id, _ = seed_member(auth, database, organization)
    other_raw = auth[0].accounts.login(other_email, PASSWORD, None).token
    with pytest.raises(AuthError) as mismatch:
        auth[0].governance.accept_invitation(raw, other_raw, request_id=uuid4())
    assert mismatch.value.code == "invitation_email_mismatch"

    result = auth[0].governance.register_invited(
        raw, display_name="Invited person", password=PASSWORD, request_id=uuid4()
    )
    assert result["email"] == email
    with Session(database.admin) as session:
        user = session.scalar(select(db.User).where(db.User.email == email))
        memberships = list(
            session.scalars(
                select(db.OrganizationMembership).where(
                    db.OrganizationMembership.user_id == user.id
                )
            )
        )
        assert user.email_verified_at == auth[3]()
        assert len(memberships) == 1
        assert memberships[0].organization_id == organization
        assert memberships[0].role == db.MembershipRole.ORG_ADMIN
        assert session.get(db.User, other_id).status == db.RecordStatus.ACTIVE


def test_concurrent_invitation_acceptance_has_one_winner(auth, database):
    _, _, organization, _ = admin_context(auth)
    with Session(database.admin) as session, session.begin():
        home = db.Organization(name="Home", slug=f"home-{uuid4().hex}")
        session.add(home)
        session.flush()
        home_id = home.id
    email, _, _ = seed_member(auth, database, home_id)
    assert invite(auth, email).status_code == 201
    invitation = auth[2].token()
    user_session = auth[0].accounts.login(email, PASSWORD, None).token

    def accept(_):
        try:
            auth[0].governance.accept_invitation(invitation, user_session, request_id=uuid4())
            return True
        except AuthError:
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(workers.map(accept, range(2))) == 1
    with Session(database.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(db.OrganizationMembership)
                .where(db.OrganizationMembership.organization_id == organization)
            )
            == 2
        )


def test_organization_rename_conflict_slug_and_event_atomicity(auth, database, monkeypatch):
    _, _, organization, _ = admin_context(auth)
    current = auth[1].get(f"{ADMIN_PATH}/organization").json()
    with Session(database.admin) as session:
        slug = session.get(db.Organization, organization).slug
    response = auth[1].patch(
        f"{ADMIN_PATH}/organization",
        json={"expected_version": current["version"], "name": "Renamed <Company>"},
        headers=csrf(auth[1]),
    )
    assert response.status_code == 200 and response.json()["version"] == 2
    assert (
        auth[1]
        .patch(
            f"{ADMIN_PATH}/organization",
            json={"expected_version": 1, "name": "Stale"},
            headers=csrf(auth[1]),
        )
        .status_code
        == 409
    )
    with Session(database.admin) as session:
        assert session.get(db.Organization, organization).slug == slug

    import reconcile.auth.governance as governance

    def fail_event(*args, **kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr(governance, "_record_event", fail_event)
    failed = auth[1].patch(
        f"{ADMIN_PATH}/organization",
        json={"expected_version": 2, "name": "Must roll back"},
        headers=csrf(auth[1]),
    )
    assert failed.status_code == 500
    with Session(database.admin) as session:
        saved = session.get(db.Organization, organization)
        assert saved.name == "Renamed <Company>" and saved.version == 2


def test_unified_audit_is_bounded_tenant_scoped_and_omits_workflow_body(auth, database):
    _, _, organization, _ = admin_context(auth)
    saved = create(auth).json()
    finding = (
        auth[1]
        .get(FINDINGS_PATH, params={"run_id": saved["run"]["id"], "limit": 1})
        .json()["items"][0]
    )
    secret_body = "private workflow narrative"
    assert change(auth, finding, action="comments", text=secret_body).status_code == 201
    assert invite(auth, f"audit-{uuid4().hex}@example.com").status_code == 201

    first = auth[1].get(f"{ADMIN_PATH}/audit", params={"limit": 2})
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2 and first.json()["next_cursor"]
    second = auth[1].get(
        f"{ADMIN_PATH}/audit",
        params={"limit": 100, "cursor": first.json()["next_cursor"]},
    )
    combined = first.json()["items"] + second.json()["items"]
    assert {item["source"] for item in combined} >= {"RUN", "WORKFLOW", "GOVERNANCE"}
    assert secret_body not in first.text + second.text
    assert auth[2].token() not in first.text + second.text
    assert all(UUID(item["request_id"]) for item in combined)

    with Session(database.admin) as session, session.begin():
        foreign = db.Organization(name="No leak", slug=f"no-leak-{uuid4().hex}")
        session.add(foreign)
        session.flush()
        assert foreign.id != organization


def test_governance_events_are_immutable_and_runtime_boundary_is_narrow(auth, database):
    admin_context(auth)
    assert invite(auth, f"boundary-{uuid4().hex}@example.com").status_code == 201
    with pytest.raises(DBAPIError):
        with database.identity.begin() as connection:
            connection.execute(text("UPDATE governance_events SET metadata = '{}'::jsonb"))
    with pytest.raises(DBAPIError):
        with database.identity.begin() as connection:
            connection.execute(text("DELETE FROM governance_events"))
    for statement in (
        "UPDATE organization_memberships SET role = 'ORG_ADMIN'",
        "SELECT * FROM organization_invitations",
        "SELECT * FROM governance_events",
        "SELECT * FROM user_credentials",
    ):
        with pytest.raises(DBAPIError):
            with database.runtime.begin() as connection:
                connection.execute(text(statement))


def test_invitation_and_audit_resources_do_not_cross_organization_boundary(auth, database):
    first_email, _, first_organization, _ = admin_context(auth)
    pending = invite(auth, f"isolated-{uuid4().hex}@example.com").json()
    with Session(database.admin) as session, session.begin():
        second = db.Organization(name="Second tenant", slug=f"second-{uuid4().hex}")
        session.add(second)
        session.flush()
        second_id = second.id
    second_email, _, _ = seed_member(auth, database, second_id, role=db.MembershipRole.ORG_ADMIN)
    login(auth, second_email)
    assert auth[1].get(f"{ADMIN_PATH}/invitations").json()["items"] == []
    revoke = auth[1].post(
        f"{ADMIN_PATH}/invitations/{pending['id']}/revoke",
        json={"expected_version": pending["version"]},
        headers=csrf(auth[1]),
    )
    assert revoke.status_code == 404
    assert pending["email"] not in auth[1].get(f"{ADMIN_PATH}/audit").text

    first_raw = auth[0].accounts.login(first_email, PASSWORD, None).token
    auth[1].cookies.set(auth[0].settings.session_cookie, first_raw)
    assert pending["email"] in auth[1].get(f"{ADMIN_PATH}/audit").text
    with Session(database.admin) as session:
        assert session.get(db.Organization, first_organization) is not None


def test_active_member_cannot_be_invited_and_acceptance_event_uses_server_context(auth, database):
    _, _, organization, _ = admin_context(auth)
    member_email, _, _ = seed_member(auth, database, organization)
    assert invite(auth, member_email).status_code == 409
    invited_email = f"context-{uuid4().hex}@example.com"
    created = invite(auth, invited_email)
    token = auth[2].token()
    response = auth[1].post(
        f"{AUTH_PATH}/register-invited",
        json={"token": token, "display_name": "Context user", "password": PASSWORD},
        headers=csrf(auth[1]),
    )
    assert response.status_code == 201
    request_id = UUID(response.headers["X-Request-ID"])
    with Session(database.admin) as session:
        user = session.scalar(select(db.User).where(db.User.email == invited_email))
        event = session.scalar(
            select(GovernanceEvent).where(
                GovernanceEvent.resource_id == UUID(created.json()["id"]),
                GovernanceEvent.event_type == "INVITATION_ACCEPTED",
            )
        )
        assert event.actor_user_id == user.id and event.request_id == request_id


def test_admin_mutations_require_csrf_and_forbid_server_owned_fields(auth):
    _, _, _, user_id = admin_context(auth)
    assert (
        auth[1]
        .patch(f"{ADMIN_PATH}/members/{user_id}", json={"expected_version": 1, "role": "MEMBER"})
        .status_code
        == 403
    )
    response = auth[1].patch(
        f"{ADMIN_PATH}/members/{user_id}",
        json={"expected_version": 1, "role": "MEMBER", "actor_user_id": str(user_id)},
        headers=csrf(auth[1]),
    )
    assert response.status_code == 422
    assert (
        auth[1]
        .post(
            f"{AUTH_PATH}/register-invited",
            json={"token": "x", "display_name": "Person", "password": PASSWORD},
        )
        .status_code
        == 403
    )
