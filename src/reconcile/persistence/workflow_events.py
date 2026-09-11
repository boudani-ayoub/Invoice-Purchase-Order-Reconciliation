"""Append-only comments and actor-aware workflow changes, never financial results."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from reconcile.persistence.base import Base, TenantRecord, tenant_constraints, tenant_fk
from reconcile.persistence.models import enum_type
from reconcile.persistence.workflow_policy import EVENT_METADATA_LIMIT, WORKFLOW_TEXT_LIMIT


class FindingEventType(StrEnum):
    COMMENT_ADDED = "COMMENT_ADDED"
    ASSIGNEE_CHANGED = "ASSIGNEE_CHANGED"
    DUE_DATE_CHANGED = "DUE_DATE_CHANGED"
    REMINDER_CHANGED = "REMINDER_CHANGED"
    STATUS_CHANGED = "STATUS_CHANGED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class FindingEvent(TenantRecord, Base):
    __tablename__ = "finding_events"
    __table_args__ = tenant_constraints(
        tenant_fk("finding_id", "findings"),
        ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object' "
            f"AND octet_length(metadata::text) <= {EVENT_METADATA_LIMIT}",
            name="metadata_bound",
        ),
        CheckConstraint(
            f"message IS NULL OR length(btrim(message)) BETWEEN 1 AND {WORKFLOW_TEXT_LIMIT}",
            name="message_length",
        ),
        CheckConstraint(
            "(event_type IN ('COMMENT_ADDED', 'RESOLVED') AND message IS NOT NULL) OR "
            "(event_type NOT IN ('COMMENT_ADDED', 'RESOLVED') AND message IS NULL)",
            name="message_type",
        ),
        Index("ix_finding_events_history", "organization_id", "finding_id", "created_at", "id"),
    )
    finding_id: Mapped[UUID]
    actor_user_id: Mapped[UUID]
    event_type: Mapped[FindingEventType] = mapped_column(enum_type(FindingEventType))
    request_id: Mapped[UUID]
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, object]] = mapped_column("metadata", JSONB)


def record_event(
    session: Session,
    *,
    organization_id: UUID,
    finding_id: UUID,
    actor: UUID,
    event_type: FindingEventType,
    request_id: UUID,
    now: datetime,
    details: dict[str, object],
    message: str | None = None,
) -> FindingEvent:
    event = FindingEvent(
        organization_id=organization_id,
        finding_id=finding_id,
        actor_user_id=actor,
        event_type=event_type,
        request_id=request_id,
        created_at=now,
        updated_at=now,
        details=details,
        message=message,
    )
    session.add(event)
    session.flush()
    return event
