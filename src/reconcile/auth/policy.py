"""Current membership, not browser state, grants analysis permission."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from reconcile.persistence.models import MembershipRole


class Permission(StrEnum):
    RUN_ANALYSIS = "RUN_ANALYSIS"


ROLE_PERMISSIONS = {role: frozenset({Permission.RUN_ANALYSIS}) for role in MembershipRole}


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
