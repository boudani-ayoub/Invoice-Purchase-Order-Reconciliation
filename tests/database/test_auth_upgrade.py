import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from reconcile.persistence.models import Organization, Supplier, User
from scripts.postgres_testing import provision_database

pytestmark = pytest.mark.database


def test_phase_one_upgrade_preserves_existing_identity_and_business_records(database, monkeypatch):
    with provision_database(os.environ["TEST_DATABASE_ADMIN_URL"], revision="0001") as previous:
        organization, user, supplier = uuid4(), uuid4(), uuid4()
        with previous.admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organizations(id, name, slug) "
                    "VALUES (:id, 'Existing company', 'existing-company')"
                ),
                {"id": organization},
            )
            connection.execute(
                text(
                    "INSERT INTO users(id, email, display_name) "
                    "VALUES (:id, 'existing@example.com', 'Existing person')"
                ),
                {"id": user},
            )
            connection.execute(
                text(
                    "INSERT INTO organization_memberships(organization_id, user_id, role) "
                    "VALUES (:org, :user, 'ORG_ADMIN')"
                ),
                {"org": organization, "user": user},
            )
            connection.execute(
                text(
                    "INSERT INTO suppliers(id, organization_id, supplier_code, name) "
                    "VALUES (:id, :org, 'EXISTING', 'Existing supplier')"
                ),
                {"id": supplier, "org": organization},
            )
        monkeypatch.setenv("DATABASE_URL", previous.migration_url)
        config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
        with Session(previous.admin) as session:
            assert session.get(Organization, organization).name == "Existing company"
            assert session.get(User, user).email_verified_at is None
            assert session.get(User, user).email == "existing@example.com"
            assert session.get(Supplier, supplier).supplier_code == "EXISTING"
            assert len(list(session.scalars(select(User)))) == 1
