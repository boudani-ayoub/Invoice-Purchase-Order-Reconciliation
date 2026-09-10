"""Explicit persistent multipart contracts and narrow history mutations."""

import json
from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import DataError

from reconcile.analysis.models import REQUIRED_SOURCES, AnalysisMode, SourceType
from reconcile.auth.policy import Permission
from reconcile.auth.service_errors import AuthError
from reconcile.persistence.imports import SourceEvidence
from reconcile.persistence.run_policy import (
    HISTORY_PAGE_MAX,
    HISTORY_PAGE_SIZE,
    NOTE_LIMIT,
    TITLE_LIMIT,
)
from reconcile.persistence.runs import Runs
from reconcile.web.auth import require_analysis, require_csrf, runtime, session_cookie
from reconcile.web.paths import RUNS_PATH
from reconcile.web.provenance import source_row_numbers
from reconcile.web.reports import load_analysis_sources, render_analysis, render_records

router = APIRouter(prefix=RUNS_PATH, tags=["Saved runs"])


def service(request: Request) -> Runs:
    return Runs(runtime(request).sessions, request.app.version)


def token(request: Request) -> str:
    return session_cookie(request, runtime(request))


async def create_run(request: Request, mode: AnalysisMode, uploads: dict[str, UploadFile]):
    from reconcile.web.app import _process_uploads

    raw = token(request)
    principal = await run_in_threadpool(
        runtime(request).sessions.authorize, raw, Permission.RUN_ANALYSIS
    )
    organization = principal.active_organization_id
    form = await request.form()
    if set(form) != set(REQUIRED_SOURCES[mode]) or len(form.multi_items()) != len(
        REQUIRED_SOURCES[mode]
    ):
        raise AuthError(422, "invalid_input", "Supply only the required source files.")

    def persist(paths, metadata):
        loaded = load_analysis_sources(paths)
        report = json.loads(render_records(mode, loaded))
        sources = tuple(
            SourceEvidence(
                SourceType(field),
                metadata[field].filename,
                metadata[field].size_bytes,
                metadata[field].sha256,
                records,
                source_row_numbers(paths[field]),
            )
            for field, records in loaded.items()
        )
        try:
            saved = service(request).create(
                raw, organization, mode, sources, report, request.state.request_id
            )
        except DataError:
            raise AuthError(
                422,
                "storage_capacity",
                "The source values cannot be stored losslessly. No run was saved.",
            ) from None
        return json.dumps(saved, ensure_ascii=False)

    return await _process_uploads(
        uploads,
        partial(render_analysis, mode),
        max_upload_bytes=request.app.state.max_upload_bytes,
        persist=persist,
    )


@router.post("/invoice-po", status_code=201, dependencies=[Depends(require_analysis)])
async def invoice_po(
    request: Request,
    purchase_orders: Annotated[UploadFile, File()],
    invoices: Annotated[UploadFile, File()],
):
    return await create_run(
        request, AnalysisMode.INVOICE_PO, {"purchase_orders": purchase_orders, "invoices": invoices}
    )


@router.post("/invoice-receipt", status_code=201, dependencies=[Depends(require_analysis)])
async def invoice_receipt(
    request: Request,
    receipts: Annotated[UploadFile, File()],
    invoices: Annotated[UploadFile, File()],
):
    return await create_run(
        request, AnalysisMode.INVOICE_RECEIPT, {"receipts": receipts, "invoices": invoices}
    )


@router.post("/po-receipt", status_code=201, dependencies=[Depends(require_analysis)])
async def po_receipt(
    request: Request,
    purchase_orders: Annotated[UploadFile, File()],
    receipts: Annotated[UploadFile, File()],
):
    return await create_run(
        request, AnalysisMode.PO_RECEIPT, {"purchase_orders": purchase_orders, "receipts": receipts}
    )


@router.post("/three-way", status_code=201, dependencies=[Depends(require_analysis)])
async def three_way(
    request: Request,
    purchase_orders: Annotated[UploadFile, File()],
    receipts: Annotated[UploadFile, File()],
    invoices: Annotated[UploadFile, File()],
):
    return await create_run(
        request,
        AnalysisMode.THREE_WAY,
        {"purchase_orders": purchase_orders, "receipts": receipts, "invoices": invoices},
    )


@router.get("")
def history(
    request: Request,
    mode: AnalysisMode | None = None,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=HISTORY_PAGE_MAX)] = HISTORY_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
):
    return service(request).list(
        token(request), mode=mode, archived=archived, limit=limit, cursor=cursor
    )


@router.get("/{run_id}")
def detail(request: Request, run_id: UUID):
    return service(request).detail(token(request), run_id)


class VersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    expected_version: int = Field(ge=1, strict=True)


class MetadataInput(VersionInput):
    title: str | None = Field(default=None, max_length=TITLE_LIMIT)
    note: str | None = Field(default=None, max_length=NOTE_LIMIT)

    @field_validator("title", "note")
    @classmethod
    def plain_text(cls, value):
        if value is None:
            return None
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Use valid Unicode text.") from None
        if "\x00" in value:
            raise ValueError("Null characters are not supported.")
        return value.strip() or None

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_fields_set.intersection({"title", "note"}):
            raise ValueError("Supply title or note.")
        return self


@router.patch("/{run_id}", dependencies=[Depends(require_csrf)])
def update_metadata(request: Request, run_id: UUID, body: MetadataInput):
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    return service(request).mutate(
        token(request), run_id, body.expected_version, changes, request.state.request_id
    )


@router.post("/{run_id}/archive", dependencies=[Depends(require_csrf)])
def archive(request: Request, run_id: UUID, body: VersionInput):
    return service(request).mutate(
        token(request), run_id, body.expected_version, {}, request.state.request_id, archive=True
    )


@router.post("/{run_id}/restore", dependencies=[Depends(require_csrf)])
def restore(request: Request, run_id: UUID, body: VersionInput):
    return service(request).mutate(
        token(request), run_id, body.expected_version, {}, request.state.request_id, archive=False
    )
