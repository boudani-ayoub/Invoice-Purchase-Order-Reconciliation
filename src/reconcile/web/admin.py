"""Organization-administration API with server-derived tenant and actor context."""

from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reconcile.auth.governance import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from reconcile.persistence.models import MembershipRole, RecordStatus
from reconcile.web.auth import EmailInput, require_csrf, runtime, session_cookie

router = APIRouter(prefix="/api/v1/admin", tags=["Organization administration"])
PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemberUpdate(AdminInput):
    expected_version: int = Field(gt=0)
    role: MembershipRole | None = None
    status: RecordStatus | None = None

    @model_validator(mode="after")
    def requires_change(self) -> Self:
        if self.role is None and self.status is None:
            raise ValueError("Provide a role or membership status.")
        return self


class InvitationCreate(EmailInput):
    role: MembershipRole


class ExpectedVersion(AdminInput):
    expected_version: int = Field(gt=0)


class OrganizationUpdate(ExpectedVersion):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter an organization name.")
        return value


@router.get("/organization")
def organization(request: Request) -> dict[str, object]:
    service = runtime(request)
    return service.governance.organization(session_cookie(request, service))


@router.patch("/organization", dependencies=[Depends(require_csrf)])
def rename_organization(body: OrganizationUpdate, request: Request) -> dict[str, object]:
    service = runtime(request)
    return service.governance.rename_organization(
        session_cookie(request, service),
        expected_version=body.expected_version,
        name=body.name,
        request_id=request.state.request_id,
    )


@router.get("/members")
def members(
    request: Request,
    limit: PageLimit = DEFAULT_PAGE_SIZE,
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, object]:
    service = runtime(request)
    return service.governance.list_members(
        session_cookie(request, service), limit=limit, cursor=cursor
    )


@router.patch("/members/{user_id}", dependencies=[Depends(require_csrf)])
def update_member(user_id: UUID, body: MemberUpdate, request: Request) -> dict[str, object]:
    service = runtime(request)
    return service.governance.update_member(
        session_cookie(request, service),
        user_id=user_id,
        expected_version=body.expected_version,
        role=body.role,
        status=body.status,
        request_id=request.state.request_id,
    )


@router.get("/invitations")
def invitations(
    request: Request,
    limit: PageLimit = DEFAULT_PAGE_SIZE,
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, object]:
    service = runtime(request)
    return service.governance.list_invitations(
        session_cookie(request, service), limit=limit, cursor=cursor
    )


@router.post("/invitations", status_code=201, dependencies=[Depends(require_csrf)])
def create_invitation(body: InvitationCreate, request: Request) -> dict[str, object]:
    service = runtime(request)
    return service.governance.create_invitation(
        session_cookie(request, service),
        email=body.email,
        role=body.role,
        request_id=request.state.request_id,
    )


@router.post("/invitations/{invitation_id}/revoke", dependencies=[Depends(require_csrf)])
def revoke_invitation(
    invitation_id: UUID, body: ExpectedVersion, request: Request
) -> dict[str, object]:
    service = runtime(request)
    return service.governance.revoke_invitation(
        session_cookie(request, service),
        invitation_id=invitation_id,
        expected_version=body.expected_version,
        request_id=request.state.request_id,
    )


@router.get("/audit")
def audit(
    request: Request,
    limit: PageLimit = DEFAULT_PAGE_SIZE,
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, object]:
    service = runtime(request)
    return service.governance.audit(session_cookie(request, service), limit=limit, cursor=cursor)
