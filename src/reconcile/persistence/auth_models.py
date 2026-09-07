"""Global authentication records, accessible only through the identity role."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from reconcile.persistence.base import Base, Record
from reconcile.persistence.models import enum_type


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
