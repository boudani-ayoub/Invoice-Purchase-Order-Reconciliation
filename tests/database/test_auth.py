from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("argon2")
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from reconcile.analysis.models import AnalysisMode
from reconcile.auth.config import AUTH_PATH, CSRF_HEADER, AuthSettings
from reconcile.auth.crypto import Passwords, new_token, token_hash
from reconcile.auth.mail import Mail
from reconcile.auth.runtime import AuthRuntime, verify_database_role
from reconcile.auth.service_errors import AuthError
from reconcile.persistence.auth_models import AuthSession, EmailToken, TokenPurpose, UserCredential
from reconcile.persistence.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    RecordStatus,
    User,
)
from reconcile.web.app import ANALYSES_PATH, create_app

pytestmark = pytest.mark.database
ORIGIN = "http://testserver:3000"
PASSWORD = "a long private passphrase é"
NEW_PASSWORD = "a different private passphrase"


def upload_files():
    sample = Path(__file__).parents[2] / "examples" / "sample_data"
    names = {
        "purchase_orders": "purchase_orders.csv",
        "receipts": "goods_receipts.csv",
        "invoices": "invoices.csv",
    }
    return {
        field: (name, (sample / name).read_bytes(), "text/csv") for field, name in names.items()
    }


@dataclass
class Clock:
    now: datetime

    def __call__(self):
        return self.now


class Mailbox:
    def __init__(self):
        self.messages: list[Mail] = []

    def send(self, mail):
        self.messages.append(mail)

    def token(self):
        return self.messages[-1].body.split("#token=")[1].split()[0]


@pytest.fixture(scope="module")
def passwords():
    return Passwords()


@pytest.fixture
def auth(database, passwords):
    clock = Clock(datetime.now(UTC))
    settings = AuthSettings(
        environment="development",
        frontend_origin=ORIGIN,
        trusted_origins=(ORIGIN,),
        identity_database_url=database.identity.url.render_as_string(hide_password=False),
        tenant_database_url=database.runtime.url.render_as_string(hide_password=False),
        csrf_secret=bytes.fromhex(uuid4().hex + uuid4().hex),
        smtp_host="mail.example.com",
        smtp_sender="accounts@example.com",
        docs_enabled=True,
    )
    mailbox = Mailbox()
    service = AuthRuntime(
        settings,
        database.identity,
        database.runtime,
        mailer=mailbox,
        clock=clock,
        passwords=passwords,
    )
    with TestClient(
        create_app(auth=service, allowed_origins=[ORIGIN]),
        headers={"Origin": ORIGIN},
        raise_server_exceptions=False,
    ) as client:
        yield service, client, mailbox, clock


def post(client, path, body=None):
    csrf = client.get(f"{AUTH_PATH}/csrf").json()["csrf_token"]
    return client.post(f"{AUTH_PATH}/{path}", json=body or {}, headers={CSRF_HEADER: csrf})


def register(auth, *, verify=True, email=None):
    _, client, mailbox, _ = auth
    email = email or f"person-{uuid4().hex}@example.com"
    response = post(
        client,
        "register",
        {
            "email": email,
            "password": PASSWORD,
            "display_name": "Test person",
            "organization_name": "Test company",
        },
    )
    assert response.status_code == 202, response.text
    if verify:
        assert post(client, "verify-email", {"token": mailbox.token()}).status_code == 200
    return email


def sign_in(auth, *, email=None):
    email = email or register(auth)
    response = post(auth[1], "login", {"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return email, auth[1].cookies.get(auth[0].settings.session_cookie)


def test_registration_is_atomic_and_password_is_argon2id(auth, database):
    email = register(auth)
    with Session(database.identity) as session:
        user = session.scalar(select(User).where(User.email == email))
        credential = session.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
        assert credential.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
        assert auth[0].accounts.passwords.hasher.verify(credential.password_hash, PASSWORD)
        assert PASSWORD not in credential.password_hash
        member = session.scalar(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
        )
        assert member.role == MembershipRole.ORG_ADMIN
        assert session.get(Organization, member.organization_id).name == "Test company"
        assert user.email_verified_at is not None


def test_registration_failure_rolls_back_user_and_organization(auth, database, monkeypatch):
    email = f"rollback-{uuid4().hex}@example.com"

    def fail(*args):
        raise RuntimeError("private delivery preparation failure")

    monkeypatch.setattr(auth[0].accounts, "_issue_token", fail)
    response = post(
        auth[1],
        "register",
        {
            "email": email,
            "password": PASSWORD,
            "display_name": "Person",
            "organization_name": email,
        },
    )
    assert response.status_code == 500 and "private" not in response.text
    with Session(database.identity) as session:
        assert session.scalar(select(User.id).where(User.email == email)) is None
        assert session.scalar(select(Organization.id).where(Organization.name == email)) is None


def test_duplicate_registration_is_generic_and_normalized(auth, database):
    email = register(auth)
    response = post(
        auth[1],
        "register",
        {
            "email": email.upper(),
            "password": NEW_PASSWORD,
            "display_name": "Other",
            "organization_name": "Other",
        },
    )
    assert response.status_code == 202
    assert len(auth[2].messages) == 1
    with Session(database.identity) as session:
        assert len(list(session.scalars(select(User).where(User.email == email)))) == 1


def test_registration_concurrency_preserves_one_account(auth, database):
    email = f"race-{uuid4().hex}@example.com"
    with ThreadPoolExecutor(max_workers=2) as workers:
        list(
            workers.map(
                lambda _: auth[0].accounts.register(email, PASSWORD, "Person", "Company"), range(2)
            )
        )
    with Session(database.identity) as session:
        assert len(list(session.scalars(select(User).where(User.email == email)))) == 1


def test_login_rotates_incoming_token_and_session_hash_only(auth, database):
    email = register(auth)
    arbitrary = new_token()
    auth[1].cookies.set(
        auth[0].settings.session_cookie, arbitrary, domain="testserver.local", path="/"
    )
    _, token = sign_in(auth, email=email)
    assert token != arbitrary and len(token) == 43
    with Session(database.identity) as session:
        record = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash(token))
        )
        assert record is not None
        assert record.token_hash != token and arbitrary not in record.token_hash
    with pytest.raises(AuthError):
        auth[0].sessions.authenticate(arbitrary)
    assert auth[1].get(f"{AUTH_PATH}/me").status_code == 200


def test_login_dummy_work_and_generic_failures(auth, monkeypatch):
    email = register(auth)
    calls = []
    original = auth[0].accounts.passwords.verify

    def track(encoded, password):
        calls.append(encoded)
        return original(encoded, password)

    monkeypatch.setattr(auth[0].accounts.passwords, "verify", track)
    wrong = post(auth[1], "login", {"email": email, "password": "wrong"})
    missing = post(
        auth[1], "login", {"email": f"missing-{uuid4().hex}@example.com", "password": "wrong"}
    )
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    assert calls[-1] is None


def test_rehash_on_success(auth, database):
    from argon2 import PasswordHasher

    email = register(auth)
    with Session(database.admin) as session, session.begin():
        user = session.scalar(select(User).where(User.email == email))
        user_id = user.id
        credential = session.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
        credential.password_hash = PasswordHasher(
            memory_cost=19456, time_cost=2, parallelism=1
        ).hash(PASSWORD)
    sign_in(auth, email=email)
    with Session(database.identity) as session:
        encoded = session.scalar(
            select(UserCredential.password_hash).where(UserCredential.user_id == user_id)
        )
        assert not auth[0].accounts.passwords.needs_rehash(encoded)


@pytest.mark.parametrize("kind", ["unknown", "malformed", "idle", "absolute", "revoked"])
def test_session_failures_are_closed(auth, database, kind):
    _, raw = sign_in(auth)
    if kind in {"unknown", "malformed"}:
        raw = new_token() if kind == "unknown" else "not-a-session"
    else:
        with Session(database.admin) as session, session.begin():
            record = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_hash(raw))
            )
            if kind == "revoked":
                record.revoked_at = auth[3]()
            elif kind == "idle":
                record.idle_expires_at = auth[3]() - timedelta(seconds=1)
            else:
                record.created_at = auth[3]() - timedelta(days=1)
                record.absolute_expires_at = auth[3]() - timedelta(seconds=1)
                record.idle_expires_at = record.absolute_expires_at
    with pytest.raises(AuthError) as error:
        auth[0].sessions.authenticate(raw)
    assert error.value.status == 401


def test_idle_refresh_does_not_extend_absolute_lifetime(auth, database):
    _, raw = sign_in(auth)
    auth[3].now += timedelta(minutes=20)
    auth[0].sessions.authenticate(raw)
    with Session(database.identity) as session:
        record = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash(raw))
        )
        assert record.idle_expires_at == auth[3]() + timedelta(minutes=30)
        assert record.absolute_expires_at == record.created_at + timedelta(hours=12)


def test_logout_revokes_copied_session_and_is_idempotent(auth):
    _, raw = sign_in(auth)
    assert post(auth[1], "logout").status_code == 200
    assert post(auth[1], "logout").status_code == 200
    with pytest.raises(AuthError):
        auth[0].sessions.authenticate(raw)
    assert auth[1].get(f"{AUTH_PATH}/me").status_code == 401


@pytest.mark.parametrize("mode", AnalysisMode)
def test_authorized_analysis_retains_report_contract(auth, mode):
    sign_in(auth)
    proof = auth[1].get(f"{AUTH_PATH}/csrf").json()["csrf_token"]
    result = auth[1].post(
        f"{ANALYSES_PATH}/{mode}", files=upload_files(), headers={CSRF_HEADER: proof}
    )
    assert result.status_code == 200, result.text
    assert result.json()["mode"] == mode
    assert result.headers["cache-control"] == "no-store"
    if mode == AnalysisMode.THREE_WAY:
        legacy = auth[1].post(
            "/api/v1/reconcile", files=upload_files(), headers={CSRF_HEADER: proof}
        )
        payload = result.json()
        payload.pop("mode")
        assert payload == legacy.json()
        assert payload["summary"]["disputed_amounts"] == {
            "EUR": "2450.00",
            "MAD": "10199.00",
            "USD": "75.00",
        }


@pytest.mark.parametrize(
    "path", ["/api/v1/reconcile", *(f"{ANALYSES_PATH}/{m}" for m in AnalysisMode)]
)
@pytest.mark.parametrize("failure", ["none", "invalid", "expired", "membership", "csrf"])
def test_analysis_failures_never_invoke_loaders(auth, database, monkeypatch, path, failure):
    import reconcile.web.app as web

    if failure not in {"none", "invalid"}:
        email, _ = sign_in(auth)
        if failure == "expired":
            auth[3].now += timedelta(hours=13)
        if failure == "membership":
            with Session(database.admin) as session, session.begin():
                user = session.scalar(select(User).where(User.email == email))
                session.execute(
                    update(OrganizationMembership)
                    .where(OrganizationMembership.user_id == user.id)
                    .values(status=RecordStatus.ARCHIVED)
                )
    if failure == "invalid":
        auth[1].cookies.set(
            auth[0].settings.session_cookie, new_token(), domain="testserver.local", path="/"
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized request reached a loader")

    monkeypatch.setattr(web, "_request_directory", forbidden)
    proof = auth[1].get(f"{AUTH_PATH}/csrf").json()["csrf_token"]
    response = auth[1].post(
        path, files=upload_files(), headers={CSRF_HEADER: "wrong" if failure == "csrf" else proof}
    )
    assert response.status_code == (403 if failure in {"membership", "csrf"} else 401)


@pytest.mark.parametrize("change", ["user", "organization", "membership"])
def test_live_revocation_stops_tenant_access(auth, database, change):
    email, raw = sign_in(auth)
    principal = auth[0].sessions.authenticate(raw)
    with Session(database.admin) as session, session.begin():
        if change == "user":
            session.get(User, principal.user_id).status = RecordStatus.ARCHIVED
        elif change == "organization":
            session.get(
                Organization, principal.active_organization_id
            ).status = RecordStatus.ARCHIVED
        else:
            session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == principal.user_id
                )
            ).status = RecordStatus.ARCHIVED
    with pytest.raises(AuthError) as error:
        auth[0].sessions.authorize_analysis(raw)
    assert error.value.status == (401 if change == "user" else 403)


def test_cross_tenant_selection_rejected_and_valid_switch_rotates(auth, database):
    email, raw = sign_in(auth)
    principal = auth[0].sessions.authenticate(raw)
    other = register(auth)
    with Session(database.identity) as session:
        other_user = session.scalar(select(User).where(User.email == other))
        other_org = session.scalar(
            select(OrganizationMembership.organization_id).where(
                OrganizationMembership.user_id == other_user.id
            )
        )
    response = post(auth[1], "select-organization", {"organization_id": str(other_org)})
    assert response.status_code == 403
    with Session(database.admin) as session, session.begin():
        session.add(
            OrganizationMembership(
                user_id=principal.user_id, organization_id=other_org, role=MembershipRole.MEMBER
            )
        )
    stale_proof = auth[1].get(f"{AUTH_PATH}/csrf").json()["csrf_token"]
    assert (
        post(auth[1], "select-organization", {"organization_id": str(other_org)}).status_code == 200
    )
    assert auth[1].cookies.get(auth[0].settings.session_cookie) != raw
    with pytest.raises(AuthError):
        auth[0].sessions.authenticate(raw)
    assert (
        auth[1].post(f"{AUTH_PATH}/logout", headers={CSRF_HEADER: stale_proof}).status_code == 403
    )
    current = auth[1].cookies.get(auth[0].settings.session_cookie)
    assert auth[0].sessions.authorize_analysis(current).active_organization_id == other_org


def test_multiple_memberships_require_selection(auth, database):
    email = register(auth)
    with Session(database.admin) as session, session.begin():
        user = session.scalar(select(User).where(User.email == email))
        organization = Organization(name="Second", slug=f"second-{uuid4().hex}")
        session.add(organization)
        session.flush()
        session.add(
            OrganizationMembership(
                user_id=user.id, organization_id=organization.id, role=MembershipRole.AP_MANAGER
            )
        )
    _, raw = sign_in(auth, email=email)
    assert auth[0].sessions.authenticate(raw).active_organization_id is None
    with pytest.raises(AuthError) as error:
        auth[0].sessions.authorize_analysis(raw)
    assert error.value.status == 403


@pytest.mark.parametrize("purpose", [TokenPurpose.VERIFICATION, TokenPurpose.RESET])
def test_email_tokens_expire_replace_and_cannot_replay(auth, database, purpose):
    email = register(auth, verify=False)
    route = "resend-verification" if purpose == TokenPurpose.VERIFICATION else "forgot-password"
    post(auth[1], route, {"email": email})
    old = auth[2].token()
    post(auth[1], route, {"email": email})
    fresh = auth[2].token()
    assert fresh != old
    service = auth[0].accounts
    with pytest.raises(AuthError):
        service.consume_token(old, purpose, NEW_PASSWORD)
    with pytest.raises(AuthError):
        service.consume_token(new_token(), purpose, NEW_PASSWORD)
    service.consume_token(fresh, purpose, NEW_PASSWORD)
    with pytest.raises(AuthError):
        service.consume_token(fresh, purpose, NEW_PASSWORD)
    with Session(database.identity) as session:
        token = session.scalar(select(EmailToken).where(EmailToken.token_hash == token_hash(fresh)))
        assert token.consumed_at is not None and token.token_hash != fresh
    post(auth[1], "forgot-password", {"email": email})
    expiring = auth[2].token()
    auth[3].now += timedelta(days=2)
    with pytest.raises(AuthError):
        service.consume_token(expiring, TokenPurpose.RESET, NEW_PASSWORD)


def test_reset_changes_password_and_revokes_all_sessions(auth):
    email, first = sign_in(auth)
    second = auth[0].accounts.login(email, PASSWORD, None).token
    assert post(auth[1], "forgot-password", {"email": email}).status_code == 202
    raw = auth[2].token()
    assert (
        post(auth[1], "reset-password", {"token": raw, "password": NEW_PASSWORD}).status_code == 200
    )
    for token in (first, second):
        with pytest.raises(AuthError):
            auth[0].sessions.authenticate(token)
    assert post(auth[1], "login", {"email": email, "password": PASSWORD}).status_code == 401
    assert post(auth[1], "login", {"email": email, "password": NEW_PASSWORD}).status_code == 200
    assert post(auth[1], "reset-password", {"token": raw, "password": PASSWORD}).status_code == 400


def test_unverified_login_is_generic_and_recovery_does_not_enumerate(auth):
    email = register(auth, verify=False)
    assert post(auth[1], "login", {"email": email, "password": PASSWORD}).status_code == 401
    found = post(auth[1], "forgot-password", {"email": email})
    missing = post(auth[1], "forgot-password", {"email": f"nobody-{uuid4().hex}@example.com"})
    assert found.status_code == missing.status_code == 202
    assert found.json() == missing.json()


def test_throttle_is_persistent_concurrent_and_applies_to_unknown_identifiers(auth):
    email = f"unknown-{uuid4().hex}@example.com"
    throttle = auth[0].accounts.throttle
    with ThreadPoolExecutor(max_workers=3) as workers:
        results = list(workers.map(lambda _: throttle.allow("login", email, auth[3]()), range(9)))
    assert sum(results) == auth[0].settings.login_attempts
    assert not throttle.allow("login", email, auth[3]())
    auth[3].now += timedelta(seconds=auth[0].settings.login_window_seconds)
    assert throttle.allow("login", email, auth[3]())


@pytest.mark.parametrize(
    "route",
    [
        "register",
        "login",
        "forgot-password",
        "reset-password",
        "verify-email",
        "resend-verification",
        "logout",
        "select-organization",
    ],
)
def test_every_state_change_requires_pre_auth_csrf(auth, route):
    response = auth[1].post(f"{AUTH_PATH}/{route}", json={})
    assert response.status_code == 403


def test_csrf_origin_and_rotation(auth):
    email = register(auth)
    stale = auth[1].get(f"{AUTH_PATH}/csrf").json()["csrf_token"]
    sign_in(auth, email=email)
    assert auth[1].post(f"{AUTH_PATH}/logout", headers={CSRF_HEADER: stale}).status_code == 403
    proof = auth[1].get(f"{AUTH_PATH}/csrf").json()["csrf_token"]
    assert (
        auth[1]
        .post(
            f"{AUTH_PATH}/logout",
            headers={CSRF_HEADER: proof, "Origin": "https://attacker.example"},
        )
        .status_code
        == 403
    )
    assert (
        auth[1].get(f"{AUTH_PATH}/csrf", headers={"Origin": "https://attacker.example"}).status_code
        == 403
    )
    assert auth[1].post(f"{AUTH_PATH}/logout", headers={CSRF_HEADER: proof}).status_code == 200


def test_identity_and_tenant_roles_are_separate(database):
    verify_database_role(database.identity, identity=True)
    verify_database_role(database.runtime, identity=False)
    with pytest.raises(ValueError):
        verify_database_role(database.admin, identity=True)
    with pytest.raises(DBAPIError):
        with database.identity.begin() as connection:
            connection.execute(text("UPDATE users SET status = 'ACTIVE'"))
    with pytest.raises(DBAPIError):
        with database.identity.begin() as connection:
            connection.execute(text("UPDATE organization_memberships SET role = 'ORG_ADMIN'"))
    for table in (
        "invoices",
        "purchase_orders",
        "goods_receipts",
        "findings",
        "result_snapshots",
        "suppliers",
    ):
        with pytest.raises(DBAPIError):
            with database.identity.begin() as connection:
                connection.execute(text(f'SELECT * FROM "{table}"'))
        with pytest.raises(DBAPIError):
            with database.identity.begin() as connection:
                connection.execute(text(f'UPDATE "{table}" SET updated_at = now()'))


def test_session_membership_fk_rejects_cross_user_organization(auth, database):
    _, raw = sign_in(auth)
    first = auth[0].sessions.authenticate(raw)
    second_email = register(auth)
    with Session(database.identity) as session:
        other = session.scalar(select(User).where(User.email == second_email))
        organization = session.scalar(
            select(OrganizationMembership.organization_id).where(
                OrganizationMembership.user_id == other.id
            )
        )
    with pytest.raises(IntegrityError):
        with Session(database.admin) as session, session.begin():
            session.execute(
                update(AuthSession)
                .where(AuthSession.id == first.session_id)
                .values(active_organization_id=organization)
            )


def test_sensitive_responses_and_validation_do_not_expose_secrets(auth, caplog):
    bad_password = "short-secret"
    response = post(
        auth[1],
        "register",
        {
            "email": "person@example.com",
            "password": bad_password,
            "display_name": "Person",
            "organization_name": "Company",
        },
    )
    assert response.status_code == 422
    assert bad_password not in response.text and bad_password not in caplog.text
    sign_in(auth)
    result = auth[1].get(f"{AUTH_PATH}/me")
    assert result.headers["cache-control"] == "no-store"
    assert set(result.json()) == {"user", "memberships", "active_organization_id"}
    assert "hash" not in result.text
    oversized = auth[1].post(f"{AUTH_PATH}/login", content=b"x" * 17000)
    assert oversized.status_code == 413


def test_production_cookie_attributes(auth):
    service, _, mailbox, clock = auth
    production = replace(
        service.settings,
        environment="production",
        frontend_origin="https://testserver",
        trusted_origins=("https://testserver",),
        docs_enabled=False,
    )
    secure = AuthRuntime(
        production,
        service.identity,
        service.tenant,
        mailer=mailbox,
        clock=clock,
        passwords=service.accounts.passwords,
    )
    with TestClient(
        create_app(auth=secure),
        base_url="https://testserver",
        headers={"Origin": "https://testserver"},
    ) as client:
        secure_auth = secure, client, mailbox, clock
        sign_in(secure_auth)
        response = post(
            client,
            "login",
            {"email": client.get(f"{AUTH_PATH}/me").json()["user"]["email"], "password": PASSWORD},
        )
        cookies = response.headers.get_list("set-cookie")
        assert len(cookies) == 2
        for cookie in cookies:
            assert cookie.startswith("__Host-")
            assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
            assert "Path=/" in cookie and "Domain=" not in cookie
        assert client.get("/docs").status_code == 404


def test_password_reset_concurrent_replay_succeeds_once(auth):
    email = register(auth)
    post(auth[1], "forgot-password", {"email": email})
    raw = auth[2].token()

    def consume(_):
        try:
            auth[0].accounts.consume_token(raw, TokenPurpose.RESET, NEW_PASSWORD)
            return True
        except AuthError:
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(workers.map(consume, range(2))) == 1


def test_no_memberships_and_live_role_changes(auth, database):
    email = register(auth)
    _, raw = sign_in(auth, email=email)
    with Session(database.admin) as session, session.begin():
        user = session.scalar(select(User).where(User.email == email))
        member = session.scalar(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
        )
        member.role = MembershipRole.MEMBER
    principal = auth[0].sessions.authorize_analysis(raw)
    assert principal.memberships[0].role == MembershipRole.MEMBER
    with Session(database.admin) as session, session.begin():
        session.execute(
            update(OrganizationMembership)
            .where(OrganizationMembership.user_id == principal.user_id)
            .values(status=RecordStatus.ARCHIVED)
        )
    _, raw = sign_in(auth, email=email)
    assert not auth[0].sessions.authenticate(raw).memberships
    with pytest.raises(AuthError) as error:
        auth[0].sessions.authorize_analysis(raw)
    assert error.value.status == 403


def test_smtp_failure_is_generic_without_secret_traceback(auth, monkeypatch, caplog):
    def fail(mail):
        raise RuntimeError(f"private-smtp-password {mail.body}")

    monkeypatch.setattr(auth[2], "send", fail)
    register(auth, verify=False)
    assert "Authentication email delivery failed" in caplog.text
    assert "private-smtp-password" not in caplog.text and "#token=" not in caplog.text


def test_login_and_recovery_throttles_enforced_at_routes(auth, monkeypatch):
    email = register(auth)
    for _ in range(auth[0].settings.login_attempts):
        assert post(auth[1], "login", {"email": email, "password": "wrong"}).status_code == 401
    assert post(auth[1], "login", {"email": email, "password": PASSWORD}).status_code == 401
    auth[3].now += timedelta(seconds=auth[0].settings.login_window_seconds)
    sign_in(auth, email=email)
    initial = len(auth[2].messages)
    for _ in range(auth[0].settings.mail_attempts + 2):
        assert post(auth[1], "forgot-password", {"email": email}).status_code == 202
    assert len(auth[2].messages) - initial == auth[0].settings.mail_attempts


def test_driver_errors_do_not_escape_to_asgi_server_logging(auth, monkeypatch, caplog):
    def fail(*args):
        raise RuntimeError("driver detail includes private-password and private-hash")

    monkeypatch.setattr(auth[0].sessions, "authenticate", fail)
    with TestClient(
        auth[1].app, headers={"Origin": ORIGIN}, raise_server_exceptions=True
    ) as client:
        response = client.get(f"{AUTH_PATH}/me")
    assert response.status_code == 500
    assert "private-password" not in response.text + caplog.text
    assert "private-hash" not in response.text + caplog.text


@pytest.mark.parametrize("purpose", [TokenPurpose.VERIFICATION, TokenPurpose.RESET])
def test_email_token_expiry_rejects_at_exact_deadline(auth, purpose):
    email = register(auth, verify=False)
    if purpose == TokenPurpose.RESET:
        post(auth[1], "forgot-password", {"email": email})
    raw = auth[2].token()
    lifetime = (
        auth[0].settings.reset_seconds
        if purpose == TokenPurpose.RESET
        else auth[0].settings.verification_seconds
    )
    auth[3].now += timedelta(seconds=lifetime)
    with pytest.raises(AuthError) as error:
        auth[0].accounts.consume_token(raw, purpose, NEW_PASSWORD)
    assert error.value.code == "invalid_token"
