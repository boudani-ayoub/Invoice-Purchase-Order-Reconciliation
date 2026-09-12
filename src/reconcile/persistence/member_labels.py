"""Narrow identity labels for IDs obtained from an authorized, bounded tenant query."""

from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from reconcile.persistence.models import OrganizationMembership, RecordStatus, User


def member_labels(identity: Engine, organization: UUID, user_ids: set[UUID]) -> dict:
    if not user_ids:
        return {}
    with Session(identity) as session:
        rows = session.execute(
            select(
                User.id,
                User.display_name,
                User.status,
                OrganizationMembership.status,
                OrganizationMembership.role,
            )
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .where(OrganizationMembership.organization_id == organization, User.id.in_(user_ids))
        )
        return {
            user_id: {
                "display_name": name,
                "active": user_status == member_status == RecordStatus.ACTIVE,
                "role": role,
            }
            for user_id, name, user_status, member_status, role in rows
        }
