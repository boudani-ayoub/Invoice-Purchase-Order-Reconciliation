"""Append-only evidence of successful run mutations, in the business transaction."""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from reconcile.persistence.base import Base, TenantRecord, tenant_constraints, tenant_fk
from reconcile.persistence.models import enum_type
from reconcile.persistence.run_policy import AUDIT_METADATA_LIMIT


class AuditEventType(StrEnum):
    ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
    RUN_METADATA_UPDATED = "RUN_METADATA_UPDATED"
    RUN_ARCHIVED = "RUN_ARCHIVED"
    RUN_RESTORED = "RUN_RESTORED"


class AuditEvent(TenantRecord, Base):
    __tablename__ = "audit_events"
    __table_args__ = tenant_constraints(
        tenant_fk("resource_id", "analysis_runs"),
        ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("resource_type = 'ANALYSIS_RUN'", name="resource_type"),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object' "
            f"AND octet_length(metadata::text) <= {AUDIT_METADATA_LIMIT}",
            name="metadata_bound",
        ),
        Index("ix_audit_events_resource", "organization_id", "resource_id", "created_at"),
    )
    actor_user_id: Mapped[UUID]
    event_type: Mapped[AuditEventType] = mapped_column(enum_type(AuditEventType))
    resource_type: Mapped[str] = mapped_column(Text, server_default="ANALYSIS_RUN")
    resource_id: Mapped[UUID]
    request_id: Mapped[UUID]
    details: Mapped[dict[str, object]] = mapped_column("metadata", JSONB)


def record_event(
    session: Session,
    *,
    organization_id: UUID,
    actor: UUID,
    run_id: UUID,
    request_id: UUID,
    event_type: AuditEventType,
    details: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=actor,
            resource_id=run_id,
            request_id=request_id,
            event_type=event_type,
            details=details,
        )
    )
    session.flush()
