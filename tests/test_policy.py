from reconcile.auth.policy import (
    AP_MANAGER_PERMISSIONS,
    MEMBER_PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
)
from reconcile.persistence.models import MembershipRole


def test_role_permissions_are_explicit_and_preserve_operational_access():
    assert MEMBER_PERMISSIONS == {
        Permission.RUN_ANALYSIS,
        Permission.VIEW_RUN_HISTORY,
        Permission.VIEW_FINDING_WORKFLOW,
        Permission.COMMENT_FINDING,
        Permission.TRANSITION_ASSIGNED_FINDING,
    }
    assert AP_MANAGER_PERMISSIONS == {
        *MEMBER_PERMISSIONS,
        Permission.UPDATE_RUN_METADATA,
        Permission.ARCHIVE_RUN,
        Permission.TRANSITION_ANY_FINDING,
        Permission.MANAGE_FINDING,
        Permission.VIEW_MANAGER_DASHBOARD,
    }
    assert ROLE_PERMISSIONS == {
        MembershipRole.MEMBER: MEMBER_PERMISSIONS,
        MembershipRole.AP_MANAGER: AP_MANAGER_PERMISSIONS,
        MembershipRole.ORG_ADMIN: AP_MANAGER_PERMISSIONS,
    }
