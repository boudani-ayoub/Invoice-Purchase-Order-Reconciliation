"""Synthetic memberships for browser tests, only in the launcher-owned disposable database."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from reconcile.auth.runtime import AuthRuntime
from reconcile.persistence.models import MembershipRole, OrganizationMembership, User


def seed_workflow_accounts(database, configured: str) -> None:
    seed = json.loads(configured)
    runtime = AuthRuntime.from_environment()
    try:
        runtime.accounts.register(
            seed["manager_email"], seed["password"], "Workflow manager", seed["organization_name"]
        )
        runtime.accounts.register(
            seed["member_email"],
            seed["password"],
            seed["member_name"],
            "Member personal test organization",
        )
        with Session(database.admin) as session, session.begin():
            manager = session.scalar(select(User.id).where(User.email == seed["manager_email"]))
            member = session.scalar(select(User.id).where(User.email == seed["member_email"]))
            membership = session.scalar(
                select(OrganizationMembership).where(OrganizationMembership.user_id == manager)
            )
            membership.role = MembershipRole.AP_MANAGER
            session.add(
                OrganizationMembership(
                    organization_id=membership.organization_id,
                    user_id=member,
                    role=MembershipRole.MEMBER,
                )
            )
    finally:
        runtime.close()
