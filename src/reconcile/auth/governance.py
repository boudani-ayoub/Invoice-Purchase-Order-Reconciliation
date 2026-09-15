"""Organization-scoped administration through the narrow identity database role."""

import base64
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.orm import Session

from reconcile.auth.config import AuthSettings
from reconcile.auth.crypto import Passwords, new_token, token_hash, valid_token
from reconcile.auth.mail import Mail, Mailer
from reconcile.auth.policy import ROLE_PERMISSIONS, Permission, Principal
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import Sessions
from reconcile.persistence.audit import AuditEvent
from reconcile.persistence.auth_models import (
    GovernanceEvent,
    GovernanceEventType,
    GovernanceResourceType,
    InvitationStatus,
    OrganizationInvitation,
    UserCredential,
)
from reconcile.persistence.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    RecordStatus,
    User,
)
from reconcile.persistence.workflow_events import FindingEvent

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
_AUDIT_SOURCE_RANK = {"RUN": 1, "WORKFLOW": 2, "GOVERNANCE": 3}
_LOGGER = logging.getLogger(__name__)


def _not_found() -> AuthError:
    return AuthError(404, "not_found", "The requested organization resource was not found.")


def _conflict(code: str, message: str) -> AuthError:
    return AuthError(409, code, message)


def _invalid_invitation() -> AuthError:
    return AuthError(400, "invalid_invitation", "This invitation is invalid or unavailable.")


def _encode_cursor(created_at: datetime, discriminator: int, resource_id: UUID) -> str:
    value = json.dumps(
        [created_at.isoformat(), discriminator, str(resource_id)], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, int, UUID] | None:
    if value is None:
        return None
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        timestamp, discriminator, resource_id = json.loads(decoded)
        created_at = datetime.fromisoformat(timestamp)
        if created_at.tzinfo is None or not isinstance(discriminator, int):
            raise ValueError
        return created_at, discriminator, UUID(resource_id)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise AuthError(400, "invalid_cursor", "The pagination cursor is invalid.") from None


def _before_cursor(created_at, resource_id, rank: int, cursor):
    if cursor is None:
        return None
    cursor_time, cursor_rank, cursor_id = cursor
    equal_time = created_at == cursor_time
    if rank < cursor_rank:
        same_time = equal_time
    elif rank == cursor_rank:
        same_time = and_(equal_time, resource_id < cursor_id)
    else:
        same_time = False
    return or_(created_at < cursor_time, same_time)


def _record_event(
    session: Session,
    *,
    organization_id: UUID,
    actor: UUID,
    request_id: UUID,
    event_type: GovernanceEventType,
    resource_type: GovernanceResourceType,
    resource_id: UUID,
    details: dict[str, object],
    now: datetime,
) -> GovernanceEvent:
    event = GovernanceEvent(
        organization_id=organization_id,
        actor_user_id=actor,
        request_id=request_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        created_at=now,
        updated_at=now,
    )
    session.add(event)
    session.flush()
    return event


class Governance:
    def __init__(
        self,
        identity: Engine,
        sessions: Sessions,
        settings: AuthSettings,
        passwords: Passwords,
        mailer: Mailer,
        clock: Callable[[], datetime],
    ) -> None:
        self.identity, self.sessions, self.settings = identity, sessions, settings
        self.passwords, self.mailer, self.clock = passwords, mailer, clock

    @contextmanager
    def _authorized(
        self, raw: str | None, permission: Permission, *, lock_organization: bool = False
    ) -> Iterator[tuple[Principal, OrganizationMembership, Organization, Session]]:
        principal = self.sessions.authenticate(raw)
        claimed = principal.require(permission)
        with Session(self.identity) as session, session.begin():
            organization_query = select(Organization).where(
                Organization.id == claimed.organization_id,
                Organization.status == RecordStatus.ACTIVE,
            )
            if lock_organization:
                organization_query = organization_query.with_for_update()
            organization = session.scalar(organization_query)
            membership = session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == claimed.organization_id,
                    OrganizationMembership.user_id == principal.user_id,
                    OrganizationMembership.status == RecordStatus.ACTIVE,
                )
            )
            if (
                organization is None
                or membership is None
                or permission not in ROLE_PERMISSIONS.get(membership.role, frozenset())
            ):
                raise AuthError(403, "forbidden", "An active organization membership is required.")
            yield principal, membership, organization, session

    def organization(self, raw: str | None) -> dict[str, object]:
        with self._authorized(raw, Permission.VIEW_ORG_ADMIN) as (_, _, organization, _):
            return {
                "id": str(organization.id),
                "name": organization.name,
                "version": organization.version,
            }

    def rename_organization(
        self, raw: str | None, *, expected_version: int, name: str, request_id: UUID
    ) -> dict[str, object]:
        now = self.clock()
        with self._authorized(raw, Permission.MANAGE_ORG_SETTINGS, lock_organization=True) as (
            principal,
            _,
            organization,
            session,
        ):
            if organization.version != expected_version:
                raise _conflict(
                    "version_conflict", "Organization settings changed. Refresh and try again."
                )
            previous = organization.name
            if name != previous:
                organization.name = name
                organization.version += 1
                _record_event(
                    session,
                    organization_id=organization.id,
                    actor=principal.user_id,
                    request_id=request_id,
                    event_type=GovernanceEventType.ORGANIZATION_RENAMED,
                    resource_type=GovernanceResourceType.ORGANIZATION,
                    resource_id=organization.id,
                    details={"previous_name": previous, "name": name},
                    now=now,
                )
            return {
                "id": str(organization.id),
                "name": organization.name,
                "version": organization.version,
            }

    def list_members(
        self, raw: str | None, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> dict[str, object]:
        marker = _decode_cursor(cursor)
        with self._authorized(raw, Permission.VIEW_ORG_ADMIN) as (_, membership, _, session):
            query = (
                select(OrganizationMembership, User)
                .join(User, User.id == OrganizationMembership.user_id)
                .where(OrganizationMembership.organization_id == membership.organization_id)
                .order_by(
                    OrganizationMembership.created_at.desc(),
                    OrganizationMembership.id.desc(),
                )
                .limit(limit + 1)
            )
            clause = _before_cursor(
                OrganizationMembership.created_at, OrganizationMembership.id, 0, marker
            )
            if clause is not None:
                query = query.where(clause)
            rows = list(session.execute(query))
            page = rows[:limit]
            items = [
                {
                    "user_id": str(member.user_id),
                    "display_name": user.display_name,
                    "email": user.email,
                    "role": member.role.value,
                    "status": member.status.value,
                    "version": member.version,
                    "created_at": member.created_at,
                }
                for member, user in page
            ]
            next_cursor = None
            if len(rows) > limit and page:
                member = page[-1][0]
                next_cursor = _encode_cursor(member.created_at, 0, member.id)
            return {"items": items, "next_cursor": next_cursor}

    def update_member(
        self,
        raw: str | None,
        *,
        user_id: UUID,
        expected_version: int,
        role: MembershipRole | None,
        status: RecordStatus | None,
        request_id: UUID,
    ) -> dict[str, object]:
        now = self.clock()
        with self._authorized(raw, Permission.MANAGE_ORG_MEMBERS, lock_organization=True) as (
            principal,
            actor_membership,
            _,
            session,
        ):
            target = session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == actor_membership.organization_id,
                    OrganizationMembership.user_id == user_id,
                )
            )
            if target is None:
                raise _not_found()
            if target.version != expected_version:
                raise _conflict("version_conflict", "Membership changed. Refresh and try again.")
            next_role = role or target.role
            next_status = status or target.status
            leaving_admin = (
                target.role == MembershipRole.ORG_ADMIN
                and target.status == RecordStatus.ACTIVE
                and (next_role != MembershipRole.ORG_ADMIN or next_status != RecordStatus.ACTIVE)
            )
            if leaving_admin:
                other_admin = session.scalar(
                    select(OrganizationMembership.id).where(
                        OrganizationMembership.organization_id == actor_membership.organization_id,
                        OrganizationMembership.user_id != target.user_id,
                        OrganizationMembership.role == MembershipRole.ORG_ADMIN,
                        OrganizationMembership.status == RecordStatus.ACTIVE,
                    )
                )
                if other_admin is None:
                    raise _conflict(
                        "last_active_admin",
                        "Assign another active organization administrator first.",
                    )
            previous_role, previous_status = target.role, target.status
            changed = next_role != previous_role or next_status != previous_status
            if changed:
                target.role = next_role
                target.status = next_status
                target.version += 1
                if next_role != previous_role:
                    _record_event(
                        session,
                        organization_id=actor_membership.organization_id,
                        actor=principal.user_id,
                        request_id=request_id,
                        event_type=GovernanceEventType.MEMBER_ROLE_CHANGED,
                        resource_type=GovernanceResourceType.MEMBERSHIP,
                        resource_id=target.id,
                        details={
                            "user_id": str(target.user_id),
                            "previous_role": previous_role.value,
                            "role": next_role.value,
                        },
                        now=now,
                    )
                if next_status != previous_status:
                    event_type = (
                        GovernanceEventType.MEMBER_REACTIVATED
                        if next_status == RecordStatus.ACTIVE
                        else GovernanceEventType.MEMBER_DEACTIVATED
                    )
                    _record_event(
                        session,
                        organization_id=actor_membership.organization_id,
                        actor=principal.user_id,
                        request_id=request_id,
                        event_type=event_type,
                        resource_type=GovernanceResourceType.MEMBERSHIP,
                        resource_id=target.id,
                        details={"user_id": str(target.user_id)},
                        now=now,
                    )
            return {
                "user_id": str(target.user_id),
                "role": target.role.value,
                "status": target.status.value,
                "version": target.version,
            }

    def list_invitations(
        self, raw: str | None, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> dict[str, object]:
        marker = _decode_cursor(cursor)
        now = self.clock()
        with self._authorized(raw, Permission.VIEW_ORG_ADMIN) as (_, membership, _, session):
            query = (
                select(OrganizationInvitation)
                .where(OrganizationInvitation.organization_id == membership.organization_id)
                .order_by(
                    OrganizationInvitation.created_at.desc(), OrganizationInvitation.id.desc()
                )
                .limit(limit + 1)
            )
            clause = _before_cursor(
                OrganizationInvitation.created_at, OrganizationInvitation.id, 0, marker
            )
            if clause is not None:
                query = query.where(clause)
            rows = list(session.scalars(query))
            page = rows[:limit]
            items = [self._invitation_view(invitation, now) for invitation in page]
            next_cursor = (
                _encode_cursor(page[-1].created_at, 0, page[-1].id)
                if len(rows) > limit and page
                else None
            )
            return {"items": items, "next_cursor": next_cursor}

    def create_invitation(
        self,
        raw_session: str | None,
        *,
        email: str,
        role: MembershipRole,
        request_id: UUID,
    ) -> dict[str, object]:
        now = self.clock()
        raw_invitation = new_token()
        mail = None
        with self._authorized(
            raw_session, Permission.MANAGE_ORG_INVITATIONS, lock_organization=True
        ) as (principal, membership, organization, session):
            if session.scalar(
                select(OrganizationMembership.id)
                .join(User, User.id == OrganizationMembership.user_id)
                .where(
                    OrganizationMembership.organization_id == membership.organization_id,
                    User.email == email,
                )
            ):
                raise _conflict(
                    "membership_exists", "That address already has an organization membership."
                )
            if session.scalar(
                select(OrganizationInvitation.id).where(
                    OrganizationInvitation.organization_id == membership.organization_id,
                    OrganizationInvitation.normalized_email == email,
                    OrganizationInvitation.status == InvitationStatus.PENDING,
                )
            ):
                raise _conflict(
                    "invitation_pending",
                    "A pending invitation already exists. Revoke it before inviting again.",
                )
            invitation = OrganizationInvitation(
                organization_id=membership.organization_id,
                normalized_email=email,
                role=role,
                token_hash=token_hash(raw_invitation),
                created_by_user_id=principal.user_id,
                expires_at=now + timedelta(seconds=self.settings.invitation_seconds),
                created_at=now,
                updated_at=now,
            )
            session.add(invitation)
            session.flush()
            _record_event(
                session,
                organization_id=membership.organization_id,
                actor=principal.user_id,
                request_id=request_id,
                event_type=GovernanceEventType.INVITATION_CREATED,
                resource_type=GovernanceResourceType.INVITATION,
                resource_id=invitation.id,
                details={"email": email, "role": role.value},
                now=now,
            )
            link = f"{self.settings.frontend_origin}/invite#token={raw_invitation}"
            mail = Mail(
                email,
                f"Join {organization.name}",
                f"You were invited to join {organization.name} as {role.value}.\n\n"
                f"Accept the invitation:\n\n{link}\n\n"
                "If you did not expect this invitation, ignore this email.",
            )
            result = self._invitation_view(invitation, now)
        self._deliver(mail)
        return result

    def revoke_invitation(
        self,
        raw: str | None,
        *,
        invitation_id: UUID,
        expected_version: int,
        request_id: UUID,
    ) -> dict[str, object]:
        now = self.clock()
        with self._authorized(raw, Permission.MANAGE_ORG_INVITATIONS, lock_organization=True) as (
            principal,
            membership,
            _,
            session,
        ):
            invitation = session.scalar(
                select(OrganizationInvitation)
                .where(
                    OrganizationInvitation.organization_id == membership.organization_id,
                    OrganizationInvitation.id == invitation_id,
                )
                .with_for_update()
            )
            if invitation is None:
                raise _not_found()
            if invitation.version != expected_version:
                raise _conflict("version_conflict", "Invitation changed. Refresh and try again.")
            if invitation.status != InvitationStatus.PENDING:
                raise _conflict(
                    "invitation_not_pending", "Only a pending invitation can be revoked."
                )
            invitation.status = InvitationStatus.REVOKED
            invitation.revoked_at = now
            invitation.version += 1
            _record_event(
                session,
                organization_id=membership.organization_id,
                actor=principal.user_id,
                request_id=request_id,
                event_type=GovernanceEventType.INVITATION_REVOKED,
                resource_type=GovernanceResourceType.INVITATION,
                resource_id=invitation.id,
                details={"email": invitation.normalized_email, "role": invitation.role.value},
                now=now,
            )
            return self._invitation_view(invitation, now)

    def preview_invitation(self, raw: str) -> dict[str, object]:
        invitation, organization = self._available_invitation(raw)
        return {
            "organization_name": organization.name,
            "email": invitation.normalized_email,
            "role": invitation.role.value,
            "expires_at": invitation.expires_at,
        }

    def accept_invitation(
        self, raw_invitation: str, raw_session: str | None, *, request_id: UUID
    ) -> dict[str, object]:
        principal = self.sessions.authenticate(raw_session)
        now = self.clock()
        with Session(self.identity) as session, session.begin():
            invitation = self._lock_available_invitation(session, raw_invitation, now)
            if principal.email != invitation.normalized_email:
                raise AuthError(
                    403,
                    "invitation_email_mismatch",
                    "Sign in with the email address that received this invitation.",
                )
            if session.scalar(
                select(OrganizationMembership.id).where(
                    OrganizationMembership.organization_id == invitation.organization_id,
                    OrganizationMembership.user_id == principal.user_id,
                )
            ):
                raise _conflict(
                    "membership_exists", "This account already has an organization membership."
                )
            member = OrganizationMembership(
                organization_id=invitation.organization_id,
                user_id=principal.user_id,
                role=invitation.role,
                created_at=now,
                updated_at=now,
            )
            session.add(member)
            session.flush()
            self._accept(session, invitation, principal.user_id, request_id, now)
            organization = session.get(Organization, invitation.organization_id)
            return {
                "organization_id": str(invitation.organization_id),
                "organization_name": organization.name,
                "role": invitation.role.value,
            }

    def register_invited(
        self,
        raw_invitation: str,
        *,
        display_name: str,
        password: str,
        request_id: UUID,
    ) -> dict[str, str]:
        encoded = self.passwords.hash(password)
        now = self.clock()
        with Session(self.identity) as session, session.begin():
            invitation = self._lock_available_invitation(session, raw_invitation, now)
            if session.scalar(select(User.id).where(User.email == invitation.normalized_email)):
                raise _conflict(
                    "account_exists", "Sign in with this email address to accept the invitation."
                )
            user = User(
                email=invitation.normalized_email,
                display_name=display_name,
                email_verified_at=now,
            )
            session.add(user)
            session.flush()
            session.add(
                UserCredential(user_id=user.id, password_hash=encoded, password_updated_at=now)
            )
            member = OrganizationMembership(
                organization_id=invitation.organization_id,
                user_id=user.id,
                role=invitation.role,
                created_at=now,
                updated_at=now,
            )
            session.add(member)
            session.flush()
            self._accept(session, invitation, user.id, request_id, now)
            return {
                "message": "Account created. Sign in to choose your organization.",
                "email": user.email,
            }

    def audit(
        self, raw: str | None, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> dict[str, object]:
        marker = _decode_cursor(cursor)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_ORG_AUDIT) as (
            principal,
            tenant,
        ):
            organization_id = principal.active_organization_id
            run_events = self._tenant_audit_source(
                tenant, AuditEvent, "RUN", organization_id, limit, marker
            )
            workflow_events = self._tenant_audit_source(
                tenant, FindingEvent, "WORKFLOW", organization_id, limit, marker
            )
        with self._authorized(raw, Permission.VIEW_ORG_AUDIT) as (
            _,
            membership,
            _,
            identity,
        ):
            rank = _AUDIT_SOURCE_RANK["GOVERNANCE"]
            query = (
                select(GovernanceEvent)
                .where(GovernanceEvent.organization_id == membership.organization_id)
                .order_by(GovernanceEvent.created_at.desc(), GovernanceEvent.id.desc())
                .limit(limit + 1)
            )
            clause = _before_cursor(GovernanceEvent.created_at, GovernanceEvent.id, rank, marker)
            if clause is not None:
                query = query.where(clause)
            governance_events = [
                {
                    "id": event.id,
                    "source": "GOVERNANCE",
                    "event_type": event.event_type.value,
                    "resource_type": event.resource_type.value,
                    "resource_id": event.resource_id,
                    "actor_user_id": event.actor_user_id,
                    "request_id": event.request_id,
                    "created_at": event.created_at,
                    "metadata": event.details,
                }
                for event in identity.scalars(query)
            ]
            merged = sorted(
                [*run_events, *workflow_events, *governance_events],
                key=lambda event: (
                    event["created_at"],
                    _AUDIT_SOURCE_RANK[event["source"]],
                    event["id"].int,
                ),
                reverse=True,
            )
            page = merged[:limit]
            actors = {event["actor_user_id"] for event in page}
            labels = {
                user_id: display_name
                for user_id, display_name in identity.execute(
                    select(User.id, User.display_name)
                    .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
                    .where(
                        OrganizationMembership.organization_id == membership.organization_id,
                        User.id.in_(actors),
                    )
                )
            }
            items = [
                {
                    **event,
                    "id": str(event["id"]),
                    "resource_id": str(event["resource_id"]),
                    "actor_user_id": str(event["actor_user_id"]),
                    "actor_display_name": labels.get(event["actor_user_id"], "Former member"),
                    "request_id": str(event["request_id"]),
                }
                for event in page
            ]
            next_cursor = None
            if len(merged) > limit and page:
                last = page[-1]
                next_cursor = _encode_cursor(
                    last["created_at"], _AUDIT_SOURCE_RANK[last["source"]], last["id"]
                )
            return {"items": items, "next_cursor": next_cursor}

    def _tenant_audit_source(
        self, session, model, source: str, organization_id: UUID, limit: int, marker
    ) -> list[dict[str, object]]:
        rank = _AUDIT_SOURCE_RANK[source]
        query = (
            select(model)
            .where(model.organization_id == organization_id)
            .order_by(model.created_at.desc(), model.id.desc())
            .limit(limit + 1)
        )
        clause = _before_cursor(model.created_at, model.id, rank, marker)
        if clause is not None:
            query = query.where(clause)
        result = []
        for event in session.scalars(query):
            workflow = source == "WORKFLOW"
            result.append(
                {
                    "id": event.id,
                    "source": source,
                    "event_type": event.event_type.value,
                    "resource_type": "FINDING" if workflow else event.resource_type,
                    "resource_id": event.finding_id if workflow else event.resource_id,
                    "actor_user_id": event.actor_user_id,
                    "request_id": event.request_id,
                    "created_at": event.created_at,
                    "metadata": event.details,
                }
            )
        return result

    def _available_invitation(self, raw: str) -> tuple[OrganizationInvitation, Organization]:
        if not valid_token(raw):
            raise _invalid_invitation()
        now = self.clock()
        with Session(self.identity) as session:
            row = session.execute(
                select(OrganizationInvitation, Organization)
                .join(Organization, Organization.id == OrganizationInvitation.organization_id)
                .where(
                    OrganizationInvitation.token_hash == token_hash(raw),
                    OrganizationInvitation.status == InvitationStatus.PENDING,
                    OrganizationInvitation.expires_at > now,
                    Organization.status == RecordStatus.ACTIVE,
                )
            ).first()
            if row is None:
                raise _invalid_invitation()
            invitation, organization = row
            session.expunge(invitation)
            session.expunge(organization)
            return invitation, organization

    def _lock_available_invitation(
        self, session: Session, raw: str, now: datetime
    ) -> OrganizationInvitation:
        if not valid_token(raw):
            raise _invalid_invitation()
        organization_id = session.scalar(
            select(OrganizationInvitation.organization_id).where(
                OrganizationInvitation.token_hash == token_hash(raw)
            )
        )
        if organization_id is None:
            raise _invalid_invitation()
        organization = session.scalar(
            select(Organization)
            .where(Organization.id == organization_id, Organization.status == RecordStatus.ACTIVE)
            .with_for_update()
        )
        if organization is None:
            raise _invalid_invitation()
        invitation = session.scalar(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.token_hash == token_hash(raw),
                OrganizationInvitation.status == InvitationStatus.PENDING,
                OrganizationInvitation.expires_at > now,
            )
            .with_for_update()
        )
        if invitation is None:
            raise _invalid_invitation()
        return invitation

    def _accept(
        self,
        session: Session,
        invitation: OrganizationInvitation,
        user_id: UUID,
        request_id: UUID,
        now: datetime,
    ) -> None:
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = now
        invitation.accepted_by_user_id = user_id
        invitation.version += 1
        _record_event(
            session,
            organization_id=invitation.organization_id,
            actor=user_id,
            request_id=request_id,
            event_type=GovernanceEventType.INVITATION_ACCEPTED,
            resource_type=GovernanceResourceType.INVITATION,
            resource_id=invitation.id,
            details={"email": invitation.normalized_email, "role": invitation.role.value},
            now=now,
        )

    def _invitation_view(
        self, invitation: OrganizationInvitation, now: datetime
    ) -> dict[str, object]:
        return {
            "id": str(invitation.id),
            "email": invitation.normalized_email,
            "role": invitation.role.value,
            "status": invitation.status.value,
            "expired": invitation.status == InvitationStatus.PENDING
            and invitation.expires_at <= now,
            "version": invitation.version,
            "created_at": invitation.created_at,
            "expires_at": invitation.expires_at,
            "accepted_at": invitation.accepted_at,
            "revoked_at": invitation.revoked_at,
        }

    def _deliver(self, mail: Mail) -> None:
        try:
            self.mailer.send(mail)
        except Exception:
            _LOGGER.error("Invitation email delivery failed; revoke and reissue if needed")
