"""Global authentication records, accessible only through the identity role."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reconcile.persistence.base import Base, Record
from reconcile.persistence.models import MembershipRole, enum_type


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"


class GovernanceEventType(StrEnum):
    ORGANIZATION_RENAMED = "ORGANIZATION_RENAMED"
    INVITATION_CREATED = "INVITATION_CREATED"
    INVITATION_REVOKED = "INVITATION_REVOKED"
    INVITATION_ACCEPTED = "INVITATION_ACCEPTED"
    MEMBER_ROLE_CHANGED = "MEMBER_ROLE_CHANGED"
    MEMBER_DEACTIVATED = "MEMBER_DEACTIVATED"
    MEMBER_REACTIVATED = "MEMBER_REACTIVATED"


class GovernanceResourceType(StrEnum):
    ORGANIZATION = "ORGANIZATION"
    MEMBERSHIP = "MEMBERSHIP"
    INVITATION = "INVITATION"


class TokenPurpose(StrEnum):
    VERIFICATION = "VERIFICATION"
    RESET = "RESET"


class UserCredential(Record, Base):
    __tablename__ = "user_credentials"
    __table_args__ = (CheckConstraint("password_hash LIKE '$argon2id$%'", name="argon2id_hash"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    password_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthSession(Record, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["active_organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_shape"),
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at AND created_at < absolute_expires_at",
            name="session_lifetimes",
        ),
        Index("ix_auth_sessions_user_revoked", "user_id", "revoked_at"),
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    active_organization_id: Mapped[UUID | None]
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailToken(Record, Base):
    __tablename__ = "email_tokens"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_shape"),
        CheckConstraint("expires_at > created_at", name="token_lifetime"),
        Index("ix_email_tokens_user_purpose", "user_id", "purpose"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    purpose: Mapped[TokenPurpose] = mapped_column(enum_type(TokenPurpose))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthThrottle(Record, Base):
    __tablename__ = "auth_throttles"
    __table_args__ = (
        CheckConstraint("bucket_hash ~ '^[0-9a-f]{64}$'", name="bucket_hash_shape"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        Index("ix_auth_throttles_window", "window_started_at"),
    )
    bucket_hash: Mapped[str] = mapped_column(Text, unique=True)
    attempts: Mapped[int]
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrganizationInvitation(Record, Base):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "created_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "accepted_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "normalized_email = lower(btrim(normalized_email)) "
            "AND normalized_email ~ '^[^@[:space:]]+@[^@[:space:]]+$' "
            "AND length(normalized_email) <= 254",
            name="email_normalized",
        ),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_shape"),
        CheckConstraint("expires_at > created_at", name="lifetime"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "(status = 'PENDING' AND accepted_at IS NULL AND accepted_by_user_id IS NULL "
            "AND revoked_at IS NULL) OR "
            "(status = 'ACCEPTED' AND accepted_at IS NOT NULL AND accepted_by_user_id IS NOT NULL "
            "AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND accepted_at IS NULL AND accepted_by_user_id IS NULL "
            "AND revoked_at IS NOT NULL)",
            name="lifecycle",
        ),
        Index("ix_organization_invitations_token", "token_hash", unique=True),
        Index(
            "uq_organization_invitations_pending_email",
            "organization_id",
            "normalized_email",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_organization_invitations_history", "organization_id", "created_at", "id"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    normalized_email: Mapped[str] = mapped_column(Text)
    role: Mapped[MembershipRole] = mapped_column(enum_type(MembershipRole))
    token_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[InvitationStatus] = mapped_column(
        enum_type(InvitationStatus), server_default=InvitationStatus.PENDING
    )
    created_by_user_id: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[UUID | None]
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class GovernanceEvent(Record, Base):
    __tablename__ = "governance_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 2048",
            name="metadata_bound",
        ),
        Index("ix_governance_events_chronology", "organization_id", "created_at", "id"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[UUID]
    event_type: Mapped[GovernanceEventType] = mapped_column(enum_type(GovernanceEventType))
    resource_type: Mapped[GovernanceResourceType] = mapped_column(enum_type(GovernanceResourceType))
    resource_id: Mapped[UUID]
    request_id: Mapped[UUID]
    details: Mapped[dict[str, object]] = mapped_column("metadata", JSONB)
