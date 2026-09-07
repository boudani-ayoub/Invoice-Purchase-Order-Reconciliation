"""Atomic registration, password verification, and single-use recovery."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reconcile.auth.config import AuthSettings
from reconcile.auth.crypto import Passwords, new_token, token_hash, valid_token
from reconcile.auth.mail import Mail, Mailer
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import IssuedSession, active_memberships, create_session
from reconcile.auth.throttle import Throttle
from reconcile.persistence.auth_models import AuthSession, EmailToken, TokenPurpose, UserCredential
from reconcile.persistence.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    RecordStatus,
    User,
)

_LOGGER = logging.getLogger(__name__)


class Accounts:
    def __init__(
        self,
        engine: Engine,
        settings: AuthSettings,
        passwords: Passwords,
        mailer: Mailer,
        clock: Callable[[], datetime],
    ) -> None:
        self.engine, self.settings = engine, settings
        self.passwords, self.mailer, self.clock = passwords, mailer, clock
        self.throttle = Throttle(engine, settings)

    def register(
        self, email: str, password: str, display_name: str, organization_name: str
    ) -> None:
        if not self.settings.registration_enabled:
            raise AuthError(403, "registration_closed", "Registration is currently unavailable.")
        now = self.clock()
        if not self.throttle.allow("register", email, now):
            return
        encoded = self.passwords.hash(password)
        mail = None
        try:
            with Session(self.engine) as session, session.begin():
                if session.scalar(select(User.id).where(User.email == email)):
                    return
                user = User(
                    email=email,
                    display_name=display_name,
                    email_verified_at=None if self.settings.require_verification else now,
                )
                organization = Organization(name=organization_name, slug=f"org-{uuid4().hex}")
                session.add_all((user, organization))
                session.flush()
                session.add(
                    UserCredential(user_id=user.id, password_hash=encoded, password_updated_at=now)
                )
                session.add(
                    OrganizationMembership(
                        organization_id=organization.id,
                        user_id=user.id,
                        role=MembershipRole.ORG_ADMIN,
                    )
                )
                if self.settings.require_verification:
                    mail = self._issue_token(session, user, TokenPurpose.VERIFICATION, now)
        except IntegrityError as error:
            if (
                getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                == "uq_users_email"
            ):
                return
            raise
        self._deliver(mail)

    def login(self, email: str, password: str, incoming_token: str | None) -> IssuedSession:
        now = self.clock()
        failure = AuthError(401, "invalid_credentials", "Unable to sign in with these credentials.")
        if not self.throttle.allow("login", email, now):
            raise failure
        with Session(self.engine) as session, session.begin():
            user = session.scalar(select(User).where(User.email == email).with_for_update())
            credential = (
                session.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
                if user
                else None
            )
            encoded = credential.password_hash if credential else None
            matches = self.passwords.verify(encoded, password)
            if (
                not matches
                or user.status != RecordStatus.ACTIVE
                or (self.settings.require_verification and user.email_verified_at is None)
            ):
                raise failure
            if self.passwords.needs_rehash(encoded):
                credential.password_hash = self.passwords.hash(password)
            memberships = active_memberships(session, user.id)
            active = memberships[0].organization_id if len(memberships) == 1 else None
            if valid_token(incoming_token):
                session.execute(
                    update(AuthSession)
                    .where(
                        AuthSession.token_hash == token_hash(incoming_token),
                        AuthSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
            issued = create_session(session, self.settings, user.id, active, now)
            self.throttle.clear_login(session, email)
            return issued

    def request_email(self, email: str, purpose: TokenPurpose) -> None:
        now = self.clock()
        if not self.throttle.allow(purpose.value, email, now):
            return
        mail = None
        with Session(self.engine) as session, session.begin():
            user = session.scalar(select(User).where(User.email == email).with_for_update())
            if (
                user
                and user.status == RecordStatus.ACTIVE
                and (purpose == TokenPurpose.RESET or user.email_verified_at is None)
            ):
                credential = session.scalar(
                    select(UserCredential.id).where(UserCredential.user_id == user.id)
                )
                if credential:
                    mail = self._issue_token(session, user, purpose, now)
        self._deliver(mail)

    def _issue_token(
        self, session: Session, user: User, purpose: TokenPurpose, now: datetime
    ) -> Mail:
        session.execute(
            update(EmailToken)
            .where(
                EmailToken.user_id == user.id,
                EmailToken.purpose == purpose,
                EmailToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        raw = new_token()
        reset = purpose == TokenPurpose.RESET
        lifetime = self.settings.reset_seconds if reset else self.settings.verification_seconds
        session.add(
            EmailToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=token_hash(raw),
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(seconds=lifetime),
            )
        )
        path = "reset-password" if reset else "verify-email"
        subject = "Reset your password" if reset else "Verify your email"
        link = f"{self.settings.frontend_origin}/{path}#token={raw}"
        return Mail(
            user.email,
            subject,
            f"{subject}:\n\n{link}\n\nIf you did not request this, ignore this email.",
        )

    def consume_token(self, raw: str, purpose: TokenPurpose, password: str | None = None) -> None:
        failure = AuthError(
            400, "invalid_token", "This link is invalid or has expired. Request a new one."
        )
        if not valid_token(raw):
            raise failure
        now = self.clock()
        with Session(self.engine) as session, session.begin():
            user_id = session.scalar(
                select(EmailToken.user_id).where(
                    EmailToken.token_hash == token_hash(raw), EmailToken.purpose == purpose
                )
            )
            if user_id is None:
                raise failure
            user = session.scalar(select(User).where(User.id == user_id).with_for_update())
            token = session.scalar(
                select(EmailToken)
                .where(
                    EmailToken.token_hash == token_hash(raw),
                    EmailToken.purpose == purpose,
                    EmailToken.consumed_at.is_(None),
                    EmailToken.expires_at > now,
                )
                .with_for_update()
            )
            if token is None or user.status != RecordStatus.ACTIVE:
                raise failure
            if purpose == TokenPurpose.RESET:
                credential = session.scalar(
                    select(UserCredential).where(UserCredential.user_id == user_id)
                )
                if credential is None or password is None:
                    raise failure
                credential.password_hash = self.passwords.hash(password)
                credential.password_updated_at = now
                session.execute(
                    update(AuthSession)
                    .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                    .values(revoked_at=now)
                )
            else:
                user.email_verified_at = now
            session.execute(
                update(EmailToken)
                .where(
                    EmailToken.user_id == user_id,
                    EmailToken.purpose == purpose,
                    EmailToken.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            )

    def _deliver(self, mail: Mail | None) -> None:
        if mail is not None:
            try:
                self.mailer.send(mail)
            except Exception:
                _LOGGER.error("Authentication email delivery failed; retry through resend/recovery")
