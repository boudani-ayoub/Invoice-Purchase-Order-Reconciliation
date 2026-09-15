"""Synthetic memberships for browser tests, only in the launcher-owned disposable database."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from reconcile.auth.crypto import token_hash
from reconcile.auth.runtime import AuthRuntime
from reconcile.persistence.auth_models import OrganizationInvitation
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
        runtime.accounts.register(
            seed["governance_admin_email"],
            seed["password"],
            "Governance administrator",
            seed["governance_organization_name"],
        )
        runtime.accounts.register(
            seed["governance_member_email"],
            seed["password"],
            seed["governance_member_name"],
            "Governance member personal organization",
        )
        runtime.accounts.register(
            seed["governance_peer_email"],
            seed["password"],
            "Governance peer administrator",
            "Governance peer personal organization",
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
            governance_admin = session.scalar(
                select(User.id).where(User.email == seed["governance_admin_email"])
            )
            governance_member = session.scalar(
                select(User.id).where(User.email == seed["governance_member_email"])
            )
            governance_peer = session.scalar(
                select(User.id).where(User.email == seed["governance_peer_email"])
            )
            governance_membership = session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == governance_admin
                )
            )
            session.add_all(
                (
                    OrganizationMembership(
                        organization_id=governance_membership.organization_id,
                        user_id=governance_member,
                        role=MembershipRole.MEMBER,
                    ),
                    OrganizationMembership(
                        organization_id=governance_membership.organization_id,
                        user_id=governance_peer,
                        role=MembershipRole.ORG_ADMIN,
                    ),
                )
            )
            session.flush()
            now = datetime.now(UTC)
            session.add(
                OrganizationInvitation(
                    organization_id=governance_membership.organization_id,
                    normalized_email=seed["governance_invited_email"],
                    role=MembershipRole.MEMBER,
                    token_hash=token_hash(seed["governance_invitation_token"]),
                    created_by_user_id=governance_admin,
                    created_at=now,
                    updated_at=now,
                    expires_at=now + timedelta(days=7),
                )
            )
    finally:
        runtime.close()
