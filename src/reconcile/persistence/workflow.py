"""Tenant-scoped operational workflow over immutable finding evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from reconcile.auth.policy import ROLE_PERMISSIONS, Permission, Principal
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import Sessions
from reconcile.persistence import models as db
from reconcile.persistence import workflow_events
from reconcile.persistence.runs import decode_cursor, encode_cursor
from reconcile.persistence.workflow_events import FindingEvent, FindingEventType
from reconcile.persistence.workflow_policy import (
    TRANSITIONS,
    WORKFLOW_FIELDS,
    WORKFLOW_PAGE_MAX,
    WORKFLOW_PAGE_SIZE,
)


def scalar(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def finding_state(finding: db.Finding, now: datetime) -> dict:
    fields = (
        "id",
        "analysis_run_id",
        "code",
        "category",
        "status",
        "assignee_user_id",
        "due_at",
        "reminder_at",
        "resolved_at",
        "resolved_by_user_id",
        "version",
        "created_at",
        "updated_at",
    )
    return {
        **{name: scalar(getattr(finding, name)) for name in fields},
        "overdue": finding.status != db.FindingStatus.RESOLVED
        and finding.due_at is not None
        and finding.due_at < now,
        "reminder_due": finding.status != db.FindingStatus.RESOLVED
        and finding.reminder_at is not None
        and finding.reminder_at <= now,
    }


def event_payload(event: FindingEvent) -> dict:
    return {
        **{
            name: scalar(getattr(event, name))
            for name in (
                "id",
                "finding_id",
                "actor_user_id",
                "event_type",
                "request_id",
                "created_at",
                "message",
            )
        },
        "metadata": event.details,
    }


def page_after(cursor: str | None, limit: int):
    if not 1 <= limit <= WORKFLOW_PAGE_MAX:
        raise AuthError(422, "invalid_limit", "Workflow page size is out of range.")
    try:
        return decode_cursor(cursor) if cursor else None
    except AuthError:
        raise AuthError(400, "invalid_cursor", "The workflow cursor is invalid.") from None


def _same_tenant(left, right, column):
    return (left.organization_id == right.organization_id) & (getattr(left, column) == right.id)


def _context_query(organization: UUID):
    return (
        select(
            db.Finding,
            db.AnalysisRun,
            db.InvoiceLine,
            db.Invoice,
            db.PurchaseOrderLine,
            db.PurchaseOrder,
            db.GoodsReceiptLine,
            db.GoodsReceipt,
        )
        .join(db.AnalysisRun, _same_tenant(db.Finding, db.AnalysisRun, "analysis_run_id"))
        .outerjoin(db.InvoiceLine, _same_tenant(db.Finding, db.InvoiceLine, "invoice_line_id"))
        .outerjoin(db.Invoice, _same_tenant(db.InvoiceLine, db.Invoice, "invoice_id"))
        .outerjoin(
            db.PurchaseOrderLine,
            _same_tenant(db.Finding, db.PurchaseOrderLine, "purchase_order_line_id"),
        )
        .outerjoin(
            db.PurchaseOrder,
            _same_tenant(db.PurchaseOrderLine, db.PurchaseOrder, "purchase_order_id"),
        )
        .outerjoin(
            db.GoodsReceiptLine,
            _same_tenant(db.Finding, db.GoodsReceiptLine, "goods_receipt_line_id"),
        )
        .outerjoin(
            db.GoodsReceipt, _same_tenant(db.GoodsReceiptLine, db.GoodsReceipt, "goods_receipt_id")
        )
        .where(db.Finding.organization_id == organization)
    )


def _context_payload(row, now: datetime, labels: dict, *, detail: bool = False) -> dict:
    finding, run, invoice_line, invoice, po_line, po, receipt_line, receipt = row
    source = invoice_line or receipt_line
    reference = {
        "invoice_number": invoice.invoice_number if invoice else None,
        "invoice_line_number": invoice_line.line_number if invoice_line else None,
        "source_row_number": (source or po_line).source_row_number,
        "supplier_code": invoice.source_supplier_code
        if invoice
        else po.source_supplier_code
        if po
        else None,
        "receipt_number": receipt.receipt_number if receipt else None,
        "receipt_line_number": receipt_line.line_number if receipt_line else None,
        "po_number": source.source_po_number if source else po.po_number,
        "po_line_number": source.source_po_line_number if source else po_line.line_number,
        "item_code": (source or po_line).source_item_code,
        "po_reference_resolved": source.resolved_purchase_order_line_id is not None
        if source
        else True,
        "item_master_resolved": (source or po_line).resolved_item_id is not None,
    }
    result = {
        **finding_state(finding, now),
        "assignee": labels.get(finding.assignee_user_id),
        "reference": reference,
        "run": {
            "id": str(run.id),
            "title": run.title,
            "mode": run.analysis_mode,
            "archived": run.archived_at is not None,
        },
    }
    if detail:
        result["resolution_note"] = finding.resolution_note
    return result


class Workflow:
    def __init__(self, sessions: Sessions) -> None:
        self.sessions = sessions

    @staticmethod
    def _finding(session: Session, organization: UUID, finding_id: UUID, *, lock=False):
        query = select(db.Finding).where(
            db.Finding.organization_id == organization, db.Finding.id == finding_id
        )
        finding = session.scalar(query.with_for_update() if lock else query)
        if finding is None:
            raise AuthError(404, "not_found", "Finding not found.")
        return finding

    def _permissions_after_lock(self, raw: str, principal: Principal, session: Session, permission):
        # A request can wait on another editor's lock; recheck session and role after that wait.
        current = self.sessions.authenticate(raw)
        current.require(permission)
        if (current.user_id, current.active_organization_id) != (
            principal.user_id,
            principal.active_organization_id,
        ):
            raise AuthError(403, "forbidden", "The active organization changed. Refresh the page.")
        role = session.scalar(
            select(db.OrganizationMembership.role)
            .join(db.Organization, db.Organization.id == db.OrganizationMembership.organization_id)
            .where(
                db.OrganizationMembership.organization_id == current.active_organization_id,
                db.OrganizationMembership.user_id == current.user_id,
                db.OrganizationMembership.status == db.RecordStatus.ACTIVE,
                db.Organization.status == db.RecordStatus.ACTIVE,
            )
        )
        permissions = ROLE_PERMISSIONS.get(role, frozenset())
        if permission not in permissions:
            raise AuthError(403, "forbidden", "An active organization membership is required.")
        return permissions

    @staticmethod
    def _version(finding: db.Finding, expected: int):
        if finding.version != expected:
            raise AuthError(
                409, "version_conflict", "This finding changed. Refresh before editing again."
            )

    def list(
        self,
        raw: str,
        *,
        run_id=None,
        status=None,
        assignee=None,
        overdue=None,
        reminder_due=None,
        limit=WORKFLOW_PAGE_SIZE,
        cursor=None,
    ) -> dict:
        after = page_after(cursor, limit)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_FINDING_WORKFLOW) as (
            principal,
            session,
        ):
            organization, now = principal.active_organization_id, self.sessions.clock()
            query = _context_query(organization)
            if run_id:
                if (
                    session.scalar(
                        select(db.AnalysisRun.id).where(
                            db.AnalysisRun.organization_id == organization,
                            db.AnalysisRun.id == run_id,
                        )
                    )
                    is None
                ):
                    raise AuthError(404, "not_found", "Run not found.")
                query = query.where(db.Finding.analysis_run_id == run_id)
            if status:
                query = query.where(db.Finding.status == status)
            if assignee == "me":
                query = query.where(db.Finding.assignee_user_id == principal.user_id)
            elif assignee == "unassigned":
                query = query.where(db.Finding.assignee_user_id.is_(None))
            elif assignee is not None:
                if (
                    session.scalar(
                        select(db.OrganizationMembership.id).where(
                            db.OrganizationMembership.organization_id == organization,
                            db.OrganizationMembership.user_id == assignee,
                        )
                    )
                    is None
                ):
                    raise AuthError(404, "not_found", "Member not found.")
                query = query.where(db.Finding.assignee_user_id == assignee)
            for requested, column, inclusive in (
                (overdue, db.Finding.due_at, False),
                (reminder_due, db.Finding.reminder_at, True),
            ):
                if requested is not None:
                    predicate = (
                        (db.Finding.status != db.FindingStatus.RESOLVED)
                        & column.is_not(None)
                        & (column <= now if inclusive else column < now)
                    )
                    query = query.where(predicate if requested else ~predicate)
            if after:
                query = query.where(tuple_(db.Finding.created_at, db.Finding.id) < after)
            rows = session.execute(
                query.order_by(db.Finding.created_at.desc(), db.Finding.id.desc()).limit(limit + 1)
            ).all()
            labels = self._assignee_labels(organization, [row[0] for row in rows[:limit]])
            return {
                "items": [_context_payload(row, now, labels) for row in rows[:limit]],
                "next_cursor": encode_cursor(rows[limit - 1][0]) if len(rows) > limit else None,
                "server_now": scalar(now),
            }

    def detail(self, raw: str, finding_id: UUID) -> dict:
        with self.sessions.authorized_transaction(raw, Permission.VIEW_FINDING_WORKFLOW) as (
            principal,
            session,
        ):
            row = session.execute(
                _context_query(principal.active_organization_id).where(db.Finding.id == finding_id)
            ).first()
            if row is None:
                raise AuthError(404, "not_found", "Finding not found.")
            now = self.sessions.clock()
            return {
                "finding": _context_payload(
                    row,
                    now,
                    self._assignee_labels(principal.active_organization_id, [row[0]]),
                    detail=True,
                ),
                "server_now": scalar(now),
            }

    def events(self, raw: str, finding_id: UUID, *, limit=WORKFLOW_PAGE_SIZE, cursor=None) -> dict:
        after = page_after(cursor, limit)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_FINDING_WORKFLOW) as (
            principal,
            session,
        ):
            self._finding(session, principal.active_organization_id, finding_id)
            query = select(FindingEvent).where(
                FindingEvent.organization_id == principal.active_organization_id,
                FindingEvent.finding_id == finding_id,
            )
            if after:
                query = query.where(tuple_(FindingEvent.created_at, FindingEvent.id) < after)
            rows = session.scalars(
                query.order_by(FindingEvent.created_at.desc(), FindingEvent.id.desc()).limit(
                    limit + 1
                )
            ).all()
            return {
                "items": [event_payload(event) for event in rows[:limit]],
                "next_cursor": encode_cursor(rows[limit - 1]) if len(rows) > limit else None,
            }

    def assignees(self, raw: str, *, limit=WORKFLOW_PAGE_SIZE, cursor: UUID | None = None) -> dict:
        page_after(None, limit)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_FINDING_WORKFLOW) as (
            principal,
            _,
        ):
            # Identity can read accounts, but this projection is bound to the verified organization.
            with Session(self.sessions.identity) as session:
                query = self._active_members(principal.active_organization_id)
                if cursor:
                    query = query.where(db.User.id > cursor)
                rows = session.execute(query.order_by(db.User.id).limit(limit + 1)).all()
                return {
                    "items": [
                        {"user_id": str(user_id), "display_name": name, "role": role}
                        for user_id, name, role in rows[:limit]
                    ],
                    "next_cursor": str(rows[limit - 1][0]) if len(rows) > limit else None,
                }

    @staticmethod
    def _active_members(organization: UUID):
        return (
            select(db.User.id, db.User.display_name, db.OrganizationMembership.role)
            .join(db.OrganizationMembership, db.OrganizationMembership.user_id == db.User.id)
            .where(
                db.OrganizationMembership.organization_id == organization,
                db.OrganizationMembership.status == db.RecordStatus.ACTIVE,
                db.User.status == db.RecordStatus.ACTIVE,
            )
        )

    def _assignee_labels(self, organization: UUID, findings: list[db.Finding]) -> dict:
        ids = {finding.assignee_user_id for finding in findings if finding.assignee_user_id}
        if not ids:
            return {}
        with Session(self.sessions.identity) as session:
            rows = session.execute(
                select(
                    db.User.id,
                    db.User.display_name,
                    db.User.status,
                    db.OrganizationMembership.status,
                )
                .join(db.OrganizationMembership, db.OrganizationMembership.user_id == db.User.id)
                .where(
                    db.OrganizationMembership.organization_id == organization, db.User.id.in_(ids)
                )
            )
            return {
                user_id: {
                    "display_name": name,
                    "active": user_status == member_status == db.RecordStatus.ACTIVE,
                }
                for user_id, name, user_status, member_status in rows
            }

    def _validate_assignee(self, organization: UUID, user_id: UUID) -> None:
        with Session(self.sessions.identity) as session:
            if (
                session.execute(
                    self._active_members(organization).where(db.User.id == user_id)
                ).first()
                is None
            ):
                raise AuthError(404, "not_found", "Active organization member not found.")

    def manage(
        self, raw: str, finding_id: UUID, expected_version: int, changes: dict, request_id: UUID
    ) -> dict:
        if not changes or set(changes) - WORKFLOW_FIELDS:
            raise ValueError("Unsupported workflow fields")
        permission = Permission.MANAGE_FINDING
        with self.sessions.authorized_transaction(raw, permission) as (principal, session):
            finding = self._finding(
                session, principal.active_organization_id, finding_id, lock=True
            )
            self._permissions_after_lock(raw, principal, session, permission)
            self._version(finding, expected_version)
            if changes.get("assignee_user_id") is not None:
                self._validate_assignee(
                    principal.active_organization_id, changes["assignee_user_id"]
                )
            changes = {
                key: value for key, value in changes.items() if getattr(finding, key) != value
            }
            if not changes:
                raise AuthError(422, "no_change", "Change at least one workflow field.")
            now = self.sessions.clock()
            before = {name: scalar(getattr(finding, name)) for name in changes}
            for name, value in changes.items():
                setattr(finding, name, value)
            finding.version += 1
            session.flush()
            session.refresh(finding)
            types = {
                "assignee_user_id": FindingEventType.ASSIGNEE_CHANGED,
                "due_at": FindingEventType.DUE_DATE_CHANGED,
                "reminder_at": FindingEventType.REMINDER_CHANGED,
            }
            for name in sorted(changes):
                self._event(
                    session,
                    principal,
                    finding,
                    request_id,
                    now,
                    types[name],
                    {
                        "previous_version": expected_version,
                        "new_version": finding.version,
                        "previous": before[name],
                        "new": scalar(changes[name]),
                    },
                )
            return finding_state(finding, now)

    def _event(
        self, session, principal, finding, request_id, now, event_type, details, message=None
    ):
        return workflow_events.record_event(
            session,
            organization_id=principal.active_organization_id,
            finding_id=finding.id,
            actor=principal.user_id,
            event_type=event_type,
            request_id=request_id,
            now=now,
            details=details,
            message=message,
        )

    def transition(
        self,
        raw: str,
        finding_id: UUID,
        expected_version: int,
        target: db.FindingStatus,
        note: str | None,
        request_id: UUID,
    ) -> dict:
        permission = Permission.TRANSITION_ASSIGNED_FINDING
        with self.sessions.authorized_transaction(raw, permission) as (principal, session):
            finding = self._finding(
                session, principal.active_organization_id, finding_id, lock=True
            )
            permissions = self._permissions_after_lock(raw, principal, session, permission)
            if (
                Permission.TRANSITION_ANY_FINDING not in permissions
                and finding.assignee_user_id != principal.user_id
            ):
                raise AuthError(
                    403, "forbidden", "Only the assignee or a manager can transition this finding."
                )
            self._version(finding, expected_version)
            if target not in TRANSITIONS[finding.status]:
                raise AuthError(
                    422, "invalid_transition", "This workflow transition is not allowed."
                )
            if (target == db.FindingStatus.RESOLVED) != (note is not None):
                raise AuthError(
                    422, "invalid_resolution", "A resolution note is required only when resolving."
                )
            now, previous = self.sessions.clock(), finding.status
            if target == db.FindingStatus.RESOLVED:
                finding.resolved_at, finding.resolved_by_user_id, finding.resolution_note = (
                    now,
                    principal.user_id,
                    note,
                )
                event = FindingEventType.RESOLVED
            elif previous == db.FindingStatus.RESOLVED:
                finding.resolved_at = finding.resolved_by_user_id = finding.resolution_note = None
                event = FindingEventType.REOPENED
            else:
                event = FindingEventType.STATUS_CHANGED
            finding.status, finding.version = target, finding.version + 1
            session.flush()
            session.refresh(finding)
            self._event(
                session,
                principal,
                finding,
                request_id,
                now,
                event,
                {
                    "previous": previous,
                    "new": target,
                    "previous_version": expected_version,
                    "new_version": finding.version,
                },
                note,
            )
            return finding_state(finding, now)

    def comment(self, raw: str, finding_id: UUID, message: str, request_id: UUID) -> dict:
        permission = Permission.COMMENT_FINDING
        with self.sessions.authorized_transaction(raw, permission) as (principal, session):
            finding = self._finding(session, principal.active_organization_id, finding_id)
            event = self._event(
                session,
                principal,
                finding,
                request_id,
                self.sessions.clock(),
                FindingEventType.COMMENT_ADDED,
                {},
                message,
            )
            return event_payload(event)
