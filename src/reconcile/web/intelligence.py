"""Read-only procurement, supplier, and inventory intelligence endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconcile.persistence.intelligence import Intelligence
from reconcile.persistence.intelligence_policy import (
    INTELLIGENCE_PAGE_MAX,
    INTELLIGENCE_PAGE_SIZE,
    IntelligenceWindow,
)
from reconcile.web.auth import runtime, session_cookie
from reconcile.web.paths import INTELLIGENCE_PATH

router = APIRouter(prefix=INTELLIGENCE_PATH, tags=["Intelligence"])


class IntelligenceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageQuery(IntelligenceQuery):
    limit: int = Field(default=INTELLIGENCE_PAGE_SIZE, ge=1, le=INTELLIGENCE_PAGE_MAX)
    cursor: str | None = Field(default=None, max_length=512)


class InventoryQuery(PageQuery):
    window: IntelligenceWindow = IntelligenceWindow.MONTH


def service(request: Request):
    auth = runtime(request)
    return Intelligence(auth.sessions), session_cookie(request, auth)


@router.get("/runs/{run_id}/procurement")
def procurement(run_id: UUID, request: Request) -> dict[str, object]:
    intelligence, raw = service(request)
    return intelligence.procurement(raw, run_id)


@router.get("/runs/{run_id}/suppliers")
def suppliers(
    run_id: UUID,
    request: Request,
    query: Annotated[PageQuery, Query()],
) -> dict[str, object]:
    intelligence, raw = service(request)
    return intelligence.suppliers(raw, run_id, limit=query.limit, cursor=query.cursor)


@router.get("/inventory")
def inventory(
    request: Request,
    query: Annotated[InventoryQuery, Query()],
) -> dict[str, object]:
    intelligence, raw = service(request)
    return intelligence.inventory(
        raw,
        window=query.window,
        limit=query.limit,
        cursor=query.cursor,
    )
