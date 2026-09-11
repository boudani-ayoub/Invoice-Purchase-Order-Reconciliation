"""Explicit workflow operations; callers never select actors or organization ownership."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from reconcile.persistence.models import FindingStatus
from reconcile.persistence.workflow import Workflow
from reconcile.persistence.workflow_policy import (
    WORKFLOW_FIELDS,
    WORKFLOW_PAGE_MAX,
    WORKFLOW_PAGE_SIZE,
    WORKFLOW_TEXT_LIMIT,
)
from reconcile.web.auth import require_csrf, runtime, session_cookie
from reconcile.web.paths import FINDINGS_PATH, WORKFLOW_PATH
from reconcile.web.runs import VersionInput

router = APIRouter(tags=["Finding workflow"])
PageSize = Annotated[int, Query(ge=1, le=WORKFLOW_PAGE_MAX)]
Cursor = Annotated[str | None, Query(max_length=256)]


def service(request: Request) -> Workflow:
    return Workflow(runtime(request).sessions)


def token(request: Request) -> str:
    return session_cookie(request, runtime(request))


def plain_text(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Use valid Unicode text.") from None
    if "\x00" in value or not value.strip():
        raise ValueError("Enter nonempty plain text without null characters.")
    return value.strip()


class WorkflowInput(VersionInput):
    assignee_user_id: UUID | None = None
    due_at: AwareDatetime | None = None
    reminder_at: AwareDatetime | None = None

    @field_validator("due_at", "reminder_at", mode="before")
    @classmethod
    def timestamp_string(cls, value):
        if value is not None and not isinstance(value, str):
            raise ValueError("Use a timezone-aware ISO timestamp.")
        return value

    @field_validator("due_at", "reminder_at")
    @classmethod
    def utc_timestamp(cls, value):
        try:
            return value.astimezone(UTC) if value is not None else None
        except (ValueError, OverflowError):
            raise ValueError("Use a timestamp within the supported UTC calendar range.") from None

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_fields_set.intersection(WORKFLOW_FIELDS):
            raise ValueError("Supply an assignment or schedule field.")
        return self


class TransitionInput(VersionInput):
    target_status: FindingStatus
    resolution_note: str | None = Field(default=None, max_length=WORKFLOW_TEXT_LIMIT, repr=False)

    _note = field_validator("resolution_note")(plain_text)

    @model_validator(mode="after")
    def resolution_required(self):
        if (self.target_status == FindingStatus.RESOLVED) != (self.resolution_note is not None):
            raise ValueError("Supply a resolution note only when resolving a finding.")
        return self


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    text: str = Field(min_length=1, max_length=WORKFLOW_TEXT_LIMIT, repr=False)
    _text = field_validator("text")(plain_text)


@router.get(FINDINGS_PATH)
def queue(
    request: Request,
    run_id: UUID | None = None,
    status: FindingStatus | None = None,
    assignee: Literal["me", "unassigned"] | UUID | None = None,
    overdue: bool | None = None,
    reminder_due: bool | None = None,
    limit: PageSize = WORKFLOW_PAGE_SIZE,
    cursor: Cursor = None,
):
    return service(request).list(
        token(request),
        run_id=run_id,
        status=status,
        assignee=assignee,
        overdue=overdue,
        reminder_due=reminder_due,
        limit=limit,
        cursor=cursor,
    )


@router.get(f"{FINDINGS_PATH}/{{finding_id}}")
def detail(request: Request, finding_id: UUID):
    return service(request).detail(token(request), finding_id)


@router.get(f"{FINDINGS_PATH}/{{finding_id}}/events")
def events(
    request: Request, finding_id: UUID, limit: PageSize = WORKFLOW_PAGE_SIZE, cursor: Cursor = None
):
    return service(request).events(token(request), finding_id, limit=limit, cursor=cursor)


@router.patch(f"{FINDINGS_PATH}/{{finding_id}}", dependencies=[Depends(require_csrf)])
def manage(request: Request, finding_id: UUID, body: WorkflowInput):
    return service(request).manage(
        token(request),
        finding_id,
        body.expected_version,
        body.model_dump(exclude_unset=True, exclude={"expected_version"}),
        request.state.request_id,
    )


@router.post(f"{FINDINGS_PATH}/{{finding_id}}/transition", dependencies=[Depends(require_csrf)])
def transition(request: Request, finding_id: UUID, body: TransitionInput):
    return service(request).transition(
        token(request),
        finding_id,
        body.expected_version,
        body.target_status,
        body.resolution_note,
        request.state.request_id,
    )


@router.post(
    f"{FINDINGS_PATH}/{{finding_id}}/comments",
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def comment(request: Request, finding_id: UUID, body: CommentInput):
    return service(request).comment(token(request), finding_id, body.text, request.state.request_id)


@router.get(f"{WORKFLOW_PATH}/assignees")
def assignees(request: Request, limit: PageSize = WORKFLOW_PAGE_SIZE, cursor: UUID | None = None):
    return service(request).assignees(token(request), limit=limit, cursor=cursor)
