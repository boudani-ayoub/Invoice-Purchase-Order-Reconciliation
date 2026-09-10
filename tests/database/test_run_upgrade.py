import os
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in

from reconcile.auth.runtime import AuthRuntime, verify_database_role
from reconcile.persistence.auth_models import AuthSession, UserCredential
from reconcile.persistence.models import User
from reconcile.web.app import create_app
from scripts.postgres_testing import provision_database

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


def test_phase_two_upgrade_keeps_accounts_credentials_and_sessions(auth, monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0002") as previous:
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
            old_auth = runtime, client, auth[2], auth[3]
            email, raw = sign_in(old_auth)
            with Session(previous.identity) as session:
                user = session.scalar(select(User).where(User.email == email))
                user_id = user.id
                password_hash = session.scalar(
                    select(UserCredential.password_hash).where(UserCredential.user_id == user_id)
                )
                session_id = session.scalar(
                    select(AuthSession.id).where(AuthSession.user_id == user_id)
                )
            monkeypatch.setenv("DATABASE_URL", previous.migration_url)
            config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
            command.upgrade(config, "head")
            command.check(config)
            verify_database_role(previous.runtime, identity=False)
            verify_database_role(previous.identity, identity=True)
            principal = runtime.sessions.authenticate(raw)
            assert principal.user_id == user_id and principal.session_id == session_id
            with Session(previous.identity) as session:
                assert (
                    session.scalar(
                        select(UserCredential.password_hash).where(
                            UserCredential.user_id == user_id
                        )
                    )
                    == password_hash
                )
            assert client.get("/api/v1/runs").json() == {"items": [], "next_cursor": None}
