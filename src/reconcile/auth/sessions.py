"""Opaque sessions and fresh organization authorization."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from reconcile.auth.config import AuthSettings
from reconcile.auth.crypto import new_token, token_hash, valid_token
from reconcile.auth.policy import ROLE_PERMISSIONS, Membership, Permission, Principal
from reconcile.auth.service_errors import AuthError
from reconcile.persistence.auth_models import AuthSession
from reconcile.persistence.models import Organization, OrganizationMembership, RecordStatus, User
from reconcile.persistence.session import tenant_session


def unauthenticated() -> AuthError:
    return AuthError(401, "unauthenticated", "Sign in to continue.")


@dataclass(frozen=True)
class IssuedSession:
    token: str = field(repr=False)
    absolute_expires_at: datetime


def active_memberships(session: Session, user_id: UUID) -> tuple[Membership, ...]:
    rows = session.execute(
        select(Organization.id, Organization.name, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
        .where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == RecordStatus.ACTIVE,
            Organization.status == RecordStatus.ACTIVE,
        )
        .order_by(Organization.name, Organization.id)
    )
    return tuple(Membership(*row) for row in rows)


def create_session(
    session: Session,
    settings: AuthSettings,
    user_id: UUID,
    organization_id: UUID | None,
    now: datetime,
    *,
    absolute_expires_at: datetime | None = None,
) -> IssuedSession:
    raw = new_token()
    absolute = absolute_expires_at or now + timedelta(seconds=settings.session_absolute_seconds)
    session.add(
        AuthSession(
            token_hash=token_hash(raw),
            user_id=user_id,
            active_organization_id=organization_id,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
            idle_expires_at=min(now + timedelta(seconds=settings.session_idle_seconds), absolute),
            absolute_expires_at=absolute,
        )
    )
    return IssuedSession(raw, absolute)


class Sessions:
    def __init__(
        self,
        identity: Engine,
        tenant: Engine,
        settings: AuthSettings,
        clock: Callable[[], datetime],
    ) -> None:
        self.identity, self.tenant, self.settings, self.clock = identity, tenant, settings, clock

    def authenticate(self, raw: str | None) -> Principal:
        if not valid_token(raw):
            raise unauthenticated()
        now = self.clock()
        with Session(self.identity) as session, session.begin():
            found = session.execute(
                select(AuthSession, User)
                .join(User, AuthSession.user_id == User.id)
                .where(
                    AuthSession.token_hash == token_hash(raw), User.status == RecordStatus.ACTIVE
                )
            ).first()
            if found is None:
                raise unauthenticated()
            record, user = found
            if self.settings.require_verification and user.email_verified_at is None:
                raise unauthenticated()
            memberships = active_memberships(session, user.id)
            touched = session.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == record.id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.idle_expires_at > now,
                    AuthSession.absolute_expires_at > now,
                )
                .values(
                    last_seen_at=now,
                    idle_expires_at=min(
                        now + timedelta(seconds=self.settings.session_idle_seconds),
                        record.absolute_expires_at,
                    ),
                )
            )
            if touched.rowcount != 1:
                raise unauthenticated()
            return Principal(
                record.id,
                user.id,
                user.email,
                user.display_name,
                memberships,
                record.active_organization_id,
            )

    def authorize_analysis(self, raw: str | None) -> Principal:
        return self.authorize(raw, Permission.RUN_ANALYSIS)

    def authorize(self, raw: str | None, permission: Permission) -> Principal:
        with self.authorized_transaction(raw, permission) as (principal, _):
            return principal

    @contextmanager
    def authorized_transaction(
        self,
        raw: str | None,
        permission: Permission,
    ) -> Iterator[tuple[Principal, Session]]:
        principal = self.authenticate(raw)
        membership = principal.require(permission)
        with tenant_session(self.tenant, membership.organization_id) as session:
            current = session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == membership.organization_id,
                    OrganizationMembership.user_id == principal.user_id,
                    OrganizationMembership.status == RecordStatus.ACTIVE,
                )
            )
            organization = session.get(Organization, membership.organization_id)
            if (
                current is None
                or organization is None
                or organization.status != RecordStatus.ACTIVE
                or permission not in ROLE_PERMISSIONS.get(current.role, frozenset())
            ):
                raise AuthError(403, "forbidden", "An active organization membership is required.")
            yield principal, session

    def select_organization(self, raw: str | None, organization_id: UUID) -> IssuedSession:
        principal = self.authenticate(raw)
        now = self.clock()
        with Session(self.identity) as session, session.begin():
            user = session.scalar(
                select(User).where(User.id == principal.user_id).with_for_update()
            )
            if user.status != RecordStatus.ACTIVE:
                raise unauthenticated()
            record = session.scalar(
                select(AuthSession)
                .where(
                    AuthSession.id == principal.session_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.idle_expires_at > now,
                    AuthSession.absolute_expires_at > now,
                )
                .with_for_update()
            )
            if record is None:
                raise unauthenticated()
            if organization_id not in {
                m.organization_id for m in active_memberships(session, user.id)
            }:
                raise AuthError(403, "forbidden", "Organization selection is not permitted.")
            record.revoked_at = now
            return create_session(
                session,
                self.settings,
                user.id,
                organization_id,
                now,
                absolute_expires_at=record.absolute_expires_at,
            )

    def logout(self, raw: str | None) -> None:
        if valid_token(raw):
            with Session(self.identity) as session, session.begin():
                session.execute(
                    update(AuthSession)
                    .where(
                        AuthSession.token_hash == token_hash(raw), AuthSession.revoked_at.is_(None)
                    )
                    .values(revoked_at=self.clock())
                )
