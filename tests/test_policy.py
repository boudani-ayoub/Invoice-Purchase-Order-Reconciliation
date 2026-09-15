from reconcile.auth.policy import (
    AP_MANAGER_PERMISSIONS,
    MEMBER_PERMISSIONS,
    ORG_ADMIN_PERMISSIONS,
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
        MembershipRole.ORG_ADMIN: ORG_ADMIN_PERMISSIONS,
    }


def test_admin_permissions_never_appear_in_operational_roles_implicitly():
    administration = {
        Permission.VIEW_ORG_ADMIN,
        Permission.MANAGE_ORG_SETTINGS,
        Permission.MANAGE_ORG_MEMBERS,
        Permission.MANAGE_ORG_INVITATIONS,
        Permission.VIEW_ORG_AUDIT,
    }
    assert administration.isdisjoint(MEMBER_PERMISSIONS)
    assert administration.isdisjoint(AP_MANAGER_PERMISSIONS)
    assert ORG_ADMIN_PERMISSIONS == AP_MANAGER_PERMISSIONS | administration
