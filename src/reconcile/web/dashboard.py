"""Manager-only read contracts with bounded query parameters and no mutation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconcile.persistence.dashboard import Dashboard
from reconcile.persistence.dashboard_policy import (
    WORKLOAD_PAGE_MAX,
    WORKLOAD_PAGE_SIZE,
    ReportingWindow,
)
from reconcile.web.auth import runtime, session_cookie
from reconcile.web.paths import DASHBOARD_PATH

router = APIRouter(prefix=DASHBOARD_PATH, tags=["Manager dashboard"])


class DashboardQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WindowQuery(DashboardQuery):
    window: ReportingWindow = ReportingWindow.MONTH


class WorkloadQuery(DashboardQuery):
    limit: int = Field(default=WORKLOAD_PAGE_SIZE, ge=1, le=WORKLOAD_PAGE_MAX)
    cursor: UUID | None = None


def service(request: Request):
    auth = runtime(request)
    return Dashboard(auth.sessions), session_cookie(request, auth)


@router.get("/overview")
def overview(request: Request, query: Annotated[WindowQuery, Query()]):
    dashboard, raw = service(request)
    return dashboard.overview(raw, query.window)


@router.get("/trends")
def trends(request: Request, query: Annotated[WindowQuery, Query()]):
    dashboard, raw = service(request)
    return dashboard.trends(raw, query.window)


@router.get("/issues")
def issues(request: Request, query: Annotated[DashboardQuery, Query()]):
    dashboard, raw = service(request)
    return dashboard.issues(raw)


@router.get("/workload")
def workload(request: Request, query: Annotated[WorkloadQuery, Query()]):
    dashboard, raw = service(request)
    return dashboard.workload(raw, limit=query.limit, cursor=query.cursor)
