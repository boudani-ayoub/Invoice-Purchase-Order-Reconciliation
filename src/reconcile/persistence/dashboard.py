"""Read-only SQL aggregates over workflow state and append-only activity, never money."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Date, Uuid, cast, column, func, literal, select, true, union_all

from reconcile.auth.policy import Permission
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import Sessions
from reconcile.persistence.dashboard_policy import (
    WORKLOAD_PAGE_MAX,
    WORKLOAD_PAGE_SIZE,
    Period,
    ReportingWindow,
)
from reconcile.persistence.member_labels import member_labels
from reconcile.persistence.models import Finding, FindingStatus
from reconcile.persistence.workflow_events import FindingEvent, FindingEventType

UNRESOLVED = Finding.status.in_((FindingStatus.OPEN, FindingStatus.IN_REVIEW))
ACTIVITY_TYPES = (FindingEventType.RESOLVED, FindingEventType.REOPENED)


def count_when(condition, name):
    return func.count().filter(condition).label(name)


def workload_counts(now: datetime):
    return (
        count_when(Finding.status == FindingStatus.OPEN, "open"),
        count_when(Finding.status == FindingStatus.IN_REVIEW, "in_review"),
        func.count().label("unresolved"),
        count_when(Finding.due_at < now, "overdue"),
    )


def event_activity(organization: UUID, period: Period):
    return (
        FindingEvent.organization_id == organization,
        FindingEvent.event_type.in_(ACTIVITY_TYPES),
        FindingEvent.created_at >= period.start,
        FindingEvent.created_at < period.end,
    )


def overview_query(organization: UUID, now: datetime, period: Period):
    elapsed = func.extract("epoch", literal(now) - Finding.created_at)
    backlog = (
        select(
            count_when(Finding.status == FindingStatus.OPEN, "open"),
            count_when(Finding.status == FindingStatus.IN_REVIEW, "in_review"),
            count_when(UNRESOLVED, "unresolved"),
            count_when(Finding.status == FindingStatus.RESOLVED, "resolved"),
            count_when(UNRESOLVED & Finding.assignee_user_id.is_(None), "unassigned_unresolved"),
            count_when(UNRESOLVED & (Finding.due_at < now), "overdue"),
            count_when(UNRESOLVED & (Finding.reminder_at <= now), "reminder_due"),
            count_when(
                (Finding.created_at >= period.start) & (Finding.created_at < period.end),
                "new_findings",
            ),
            func.percentile_cont(0.5).within_group(elapsed).filter(UNRESOLVED).label("median_age"),
            func.max(elapsed).filter(UNRESOLVED).label("oldest_age"),
        )
        .where(Finding.organization_id == organization)
        .subquery()
    )
    activity = (
        select(
            count_when(FindingEvent.event_type == FindingEventType.RESOLVED, "resolution_events"),
            count_when(FindingEvent.event_type == FindingEventType.REOPENED, "reopen_events"),
        )
        .where(*event_activity(organization, period))
        .subquery()
    )
    return select(backlog, activity).select_from(backlog.join(activity, true()))


def trends_query(organization: UUID, period: Period):
    finding_day = cast(func.timezone("UTC", Finding.created_at), Date)
    event_day = cast(func.timezone("UTC", FindingEvent.created_at), Date)
    created = (
        select(
            finding_day.label("day"),
            func.count().label("new_findings"),
            literal(0).label("resolution_events"),
            literal(0).label("reopen_events"),
        )
        .where(
            Finding.organization_id == organization,
            Finding.created_at >= period.start,
            Finding.created_at < period.end,
        )
        .group_by(finding_day)
    )
    actions = (
        select(
            event_day.label("day"),
            literal(0).label("new_findings"),
            count_when(FindingEvent.event_type == FindingEventType.RESOLVED, "resolution_events"),
            count_when(FindingEvent.event_type == FindingEventType.REOPENED, "reopen_events"),
        )
        .where(*event_activity(organization, period))
        .group_by(event_day)
    )
    buckets = union_all(created, actions).subquery()
    return (
        select(
            buckets.c.day,
            *(
                func.sum(buckets.c[name]).label(name)
                for name in ("new_findings", "resolution_events", "reopen_events")
            ),
        )
        .group_by(buckets.c.day)
        .order_by(buckets.c.day)
    )


def workload_query(organization: UUID, now: datetime, limit: int, cursor: UUID | None):
    base = (Finding.organization_id == organization, UNRESOLVED)
    unassigned = select(literal(None, Uuid).label("assignee_user_id"), *workload_counts(now)).where(
        *base, Finding.assignee_user_id.is_(None)
    )
    assigned = select(Finding.assignee_user_id, *workload_counts(now)).where(
        *base, Finding.assignee_user_id.is_not(None)
    )
    if cursor:
        assigned = assigned.where(Finding.assignee_user_id > cursor)
    page = (
        assigned.group_by(Finding.assignee_user_id)
        .order_by(Finding.assignee_user_id)
        .limit(limit + 1)
        .subquery()
    )
    return union_all(unassigned, select(page)).order_by(column("assignee_user_id").nulls_first())


class Dashboard:
    def __init__(self, sessions: Sessions):
        self.sessions = sessions

    def overview(self, raw: str, window=ReportingWindow.MONTH):
        with self.sessions.authorized_transaction(raw, Permission.VIEW_MANAGER_DASHBOARD) as (
            principal,
            session,
        ):
            now = self.sessions.clock().astimezone(UTC)
            period = Period.at(window, now)
            row = (
                session.execute(overview_query(principal.active_organization_id, now, period))
                .mappings()
                .one()
            )
            return {
                "server_now": now.isoformat(),
                "period": period.payload(),
                "backlog": {
                    name: row[name]
                    for name in (
                        "open",
                        "in_review",
                        "unresolved",
                        "resolved",
                        "unassigned_unresolved",
                        "overdue",
                        "reminder_due",
                    )
                },
                "activity": {
                    name: row[name]
                    for name in ("new_findings", "resolution_events", "reopen_events")
                },
                "age": {
                    "median_unresolved_age_seconds": float(row["median_age"])
                    if row["median_age"] is not None
                    else None,
                    "oldest_unresolved_age_seconds": float(row["oldest_age"])
                    if row["oldest_age"] is not None
                    else None,
                },
            }

    def trends(self, raw: str, window=ReportingWindow.MONTH):
        with self.sessions.authorized_transaction(raw, Permission.VIEW_MANAGER_DASHBOARD) as (
            principal,
            session,
        ):
            now = self.sessions.clock().astimezone(UTC)
            period = Period.at(window, now)
            rows = session.execute(
                trends_query(principal.active_organization_id, period)
            ).mappings()
            by_day = {row["day"]: row for row in rows}
            items = []
            for offset in range(window.days):
                start = period.start + timedelta(days=offset)
                row = by_day.get(start.date(), {})
                items.append(
                    {
                        "bucket_start": start.isoformat(),
                        **{
                            name: int(row.get(name, 0))
                            for name in ("new_findings", "resolution_events", "reopen_events")
                        },
                    }
                )
            return {"server_now": now.isoformat(), "period": period.payload(), "items": items}

    def issues(self, raw: str):
        with self.sessions.authorized_transaction(raw, Permission.VIEW_MANAGER_DASHBOARD) as (
            principal,
            session,
        ):
            now = self.sessions.clock().astimezone(UTC)
            rows = session.execute(
                select(Finding.code, Finding.category, func.count().label("count"))
                .where(Finding.organization_id == principal.active_organization_id, UNRESOLVED)
                .group_by(Finding.code, Finding.category)
                .order_by(func.count().desc(), Finding.code, Finding.category)
            ).mappings()
            return {"server_now": now.isoformat(), "items": [dict(row) for row in rows]}

    def workload(self, raw: str, *, limit=WORKLOAD_PAGE_SIZE, cursor: UUID | None = None):
        if not 1 <= limit <= WORKLOAD_PAGE_MAX:
            raise AuthError(422, "invalid_limit", "Workload page size is out of range.")
        with self.sessions.authorized_transaction(raw, Permission.VIEW_MANAGER_DASHBOARD) as (
            principal,
            session,
        ):
            now = self.sessions.clock().astimezone(UTC)
            rows = (
                session.execute(
                    workload_query(principal.active_organization_id, now, limit, cursor)
                )
                .mappings()
                .all()
            )
            unassigned, assigned = rows[0], rows[1:]
            labels = member_labels(
                self.sessions.identity,
                principal.active_organization_id,
                {row["assignee_user_id"] for row in assigned[:limit]},
            )

            def payload(row):
                user_id = row["assignee_user_id"]
                return {
                    **dict(row),
                    "assignee_user_id": str(user_id) if user_id else None,
                    **labels.get(user_id, {"display_name": None, "active": None, "role": None}),
                }

            return {
                "server_now": now.isoformat(),
                "unassigned": payload(unassigned),
                "items": [payload(row) for row in assigned[:limit]],
                "next_cursor": str(assigned[limit - 1]["assignee_user_id"])
                if len(assigned) > limit
                else None,
            }
