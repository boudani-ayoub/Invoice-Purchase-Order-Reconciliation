"""Current membership, not browser state, grants analysis permission."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from reconcile.persistence.models import MembershipRole


class Permission(StrEnum):
    RUN_ANALYSIS = "RUN_ANALYSIS"
    VIEW_RUN_HISTORY = "VIEW_RUN_HISTORY"
    UPDATE_RUN_METADATA = "UPDATE_RUN_METADATA"
    ARCHIVE_RUN = "ARCHIVE_RUN"
    VIEW_FINDING_WORKFLOW = "VIEW_FINDING_WORKFLOW"
    COMMENT_FINDING = "COMMENT_FINDING"
    TRANSITION_ASSIGNED_FINDING = "TRANSITION_ASSIGNED_FINDING"
    TRANSITION_ANY_FINDING = "TRANSITION_ANY_FINDING"
    MANAGE_FINDING = "MANAGE_FINDING"


ROLE_PERMISSIONS = {
    MembershipRole.MEMBER: frozenset(
        {
            Permission.RUN_ANALYSIS,
            Permission.VIEW_RUN_HISTORY,
            Permission.VIEW_FINDING_WORKFLOW,
            Permission.COMMENT_FINDING,
            Permission.TRANSITION_ASSIGNED_FINDING,
        }
    ),
    MembershipRole.AP_MANAGER: frozenset(Permission),
    MembershipRole.ORG_ADMIN: frozenset(Permission),
}


@dataclass(frozen=True)
class Membership:
    organization_id: UUID
    organization_name: str
    role: MembershipRole


@dataclass(frozen=True)
class Principal:
    session_id: UUID
    user_id: UUID
    email: str
    display_name: str
    memberships: tuple[Membership, ...]
    active_organization_id: UUID | None

    def require(self, permission: Permission) -> Membership:
        from reconcile.auth.service_errors import AuthError

        for membership in self.memberships:
            if membership.organization_id == self.active_organization_id:
                if permission in ROLE_PERMISSIONS.get(membership.role, frozenset()):
                    return membership
        raise AuthError(403, "forbidden", "An active organization membership is required.")
