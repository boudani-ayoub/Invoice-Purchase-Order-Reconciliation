"""Authenticated FastAPI adapter for transient analyses and saved runs."""

import os
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from functools import partial
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from reconcile import (
    CsvValidationError,
    load_goods_receipts,
    load_invoices,
    load_purchase_orders,
    reconcile,
    render_json_report,
)
from reconcile.analysis.models import AnalysisMode
from reconcile.auth.config import CSRF_HEADER
from reconcile.auth.config import origin as validate_origin
from reconcile.auth.runtime import AuthRuntime
from reconcile.auth.service_errors import AuthError
from reconcile.web.auth import require_analysis
from reconcile.web.auth import router as auth_router
from reconcile.web.auth_body import AuthBodyLimitMiddleware
from reconcile.web.paths import ANALYSES_PATH
from reconcile.web.provenance import UploadedSource, safe_filename
from reconcile.web.reports import (
    InvoicePoReport,
    InvoiceReceiptReport,
    PoReceiptReport,
    ThreeWayReport,
    render_analysis,
)
from reconcile.web.request_security import AnalysisGateMiddleware, RequestIdMiddleware
from reconcile.web.safe_errors import SafeErrorsMiddleware

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 64 * 1024
ALLOWED_ORIGINS_ENV = "RECONCILE_ALLOWED_ORIGINS"

_DISTRIBUTION_NAME = "invoice-purchase-order-reconciliation"
_INTERNAL_FILENAMES = {
    "purchase_orders": "purchase_orders.csv",
    "receipts": "goods_receipts.csv",
    "invoices": "invoices.csv",
}
_FIELD_BY_FILENAME = {filename: field for field, filename in _INTERNAL_FILENAMES.items()}


class _FileTooLargeError(Exception):
    def __init__(self, field: str, max_bytes: int) -> None:
        self.field = field
        self.max_bytes = max_bytes
        super().__init__(f"{field} exceeds the {max_bytes}-byte upload limit")


def create_app(
    *,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
    allowed_origins: str | Sequence[str] | None = None,
    auth: AuthRuntime | None = None,
) -> FastAPI:
    """Create the authenticated application; injected services are owned by their caller."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.auth is None:
            app.state.auth = await run_in_threadpool(AuthRuntime.from_environment)
        try:
            yield
        finally:
            if auth is None:
                app.state.auth.close()

    docs_enabled = (
        auth.settings.docs_enabled
        if auth
        else os.environ.get(
            "AUTH_DOCS_ENABLED", str(os.environ.get("APP_ENV") == "development")
        ).lower()
        == "true"
    )

    application = FastAPI(
        title="Invoice / Purchase Order Reconciliation API",
        version=version(_DISTRIBUTION_NAME),
        description="Authenticated organization-scoped procurement analyses and saved history.",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    application.state.auth = auth
    application.state.max_upload_bytes = max_upload_bytes
    application.add_middleware(AuthBodyLimitMiddleware)
    application.add_middleware(AnalysisGateMiddleware)
    application.add_middleware(SafeErrorsMiddleware)
    application.add_middleware(RequestIdMiddleware)
    application.include_router(auth_router)
    from reconcile.web.runs import router as runs_router
    from reconcile.web.workflow import router as workflow_router

    application.include_router(runs_router)
    application.include_router(workflow_router)
    configured_origins = _resolve_allowed_origins(allowed_origins)
    if configured_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(configured_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Content-Type", CSRF_HEADER],
            expose_headers=["X-Request-ID"],
        )

    @application.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.exception_handler(AuthError)
    async def auth_error_handler(request: Request, error: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"error": error.code, "message": error.message},
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(RequestValidationError)
    async def input_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_input",
                "message": "Check the supplied fields.",
                "detail": [
                    {"loc": item["loc"], "type": item["type"], "msg": item["msg"]}
                    for item in error.errors()
                ],
            },
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/health", summary="Check API availability")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": application.version}

    @application.post(
        "/api/v1/reconcile",
        summary="Reconcile uploaded purchase orders, receipts, and invoices",
        response_class=JSONResponse,
        response_description="The existing deterministic reconciliation JSON report.",
        responses={
            413: {"description": "An uploaded file exceeds the per-file size limit."},
            422: {"description": "A required upload is missing or CSV validation failed."},
            500: {"description": "An unexpected internal error occurred."},
        },
        dependencies=[Depends(require_analysis)],
    )
    async def reconcile_uploads(
        purchase_orders: Annotated[
            UploadFile,
            File(description="Purchase-order CSV input."),
        ],
        receipts: Annotated[
            UploadFile,
            File(description="Goods-receipt CSV input."),
        ],
        invoices: Annotated[
            UploadFile,
            File(description="Supplier-invoice CSV input."),
        ],
    ) -> Response:
        uploads = {
            "purchase_orders": purchase_orders,
            "receipts": receipts,
            "invoices": invoices,
        }
        return await _process_uploads(
            uploads,
            lambda paths: _render_reconciliation(
                paths["purchase_orders"],
                paths["receipts"],
                paths["invoices"],
            ),
            max_upload_bytes=max_upload_bytes,
        )

    @application.post(
        f"{ANALYSES_PATH}/{AnalysisMode.INVOICE_PO}",
        response_model=InvoicePoReport,
        dependencies=[Depends(require_analysis)],
    )
    async def invoice_po_uploads(
        purchase_orders: Annotated[UploadFile, File()],
        invoices: Annotated[UploadFile, File()],
    ) -> Response:
        return await _process_uploads(
            {"purchase_orders": purchase_orders, "invoices": invoices},
            partial(render_analysis, AnalysisMode.INVOICE_PO),
            max_upload_bytes=max_upload_bytes,
        )

    @application.post(
        f"{ANALYSES_PATH}/{AnalysisMode.INVOICE_RECEIPT}",
        response_model=InvoiceReceiptReport,
        dependencies=[Depends(require_analysis)],
    )
    async def invoice_receipt_uploads(
        receipts: Annotated[UploadFile, File()],
        invoices: Annotated[UploadFile, File()],
    ) -> Response:
        return await _process_uploads(
            {"receipts": receipts, "invoices": invoices},
            partial(render_analysis, AnalysisMode.INVOICE_RECEIPT),
            max_upload_bytes=max_upload_bytes,
        )

    @application.post(
        f"{ANALYSES_PATH}/{AnalysisMode.PO_RECEIPT}",
        response_model=PoReceiptReport,
        dependencies=[Depends(require_analysis)],
    )
    async def po_receipt_uploads(
        purchase_orders: Annotated[UploadFile, File()],
        receipts: Annotated[UploadFile, File()],
    ) -> Response:
        return await _process_uploads(
            {"purchase_orders": purchase_orders, "receipts": receipts},
            partial(render_analysis, AnalysisMode.PO_RECEIPT),
            max_upload_bytes=max_upload_bytes,
        )

    @application.post(
        f"{ANALYSES_PATH}/{AnalysisMode.THREE_WAY}",
        response_model=ThreeWayReport,
        dependencies=[Depends(require_analysis)],
    )
    async def three_way_uploads(
        purchase_orders: Annotated[UploadFile, File()],
        receipts: Annotated[UploadFile, File()],
        invoices: Annotated[UploadFile, File()],
    ) -> Response:
        return await _process_uploads(
            {"purchase_orders": purchase_orders, "receipts": receipts, "invoices": invoices},
            partial(render_analysis, AnalysisMode.THREE_WAY),
            max_upload_bytes=max_upload_bytes,
        )

    return application


async def _process_uploads(
    uploads: dict[str, UploadFile],
    renderer: Callable[[dict[str, Path]], str],
    *,
    max_upload_bytes: int,
    persist: Callable[[dict[str, Path], dict[str, UploadedSource]], str] | None = None,
) -> Response:
    try:
        with _request_directory() as directory:
            paths: dict[str, Path] = {}
            metadata: dict[str, UploadedSource] = {}
            try:
                for field, upload in uploads.items():
                    path = Path(directory) / _INTERNAL_FILENAMES[field]
                    metadata[field] = await _write_upload(
                        upload,
                        path,
                        field=field,
                        max_bytes=max_upload_bytes,
                    )
                    paths[field] = path
            except _FileTooLargeError as error:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "file_too_large",
                        "file": error.field,
                        "max_bytes": error.max_bytes,
                    },
                )

            try:
                report = (
                    await run_in_threadpool(persist, paths, metadata)
                    if persist
                    else await run_in_threadpool(renderer, paths)
                )
            except CsvValidationError as error:
                return JSONResponse(
                    status_code=422,
                    content=_validation_error_response(error),
                )

            return Response(
                content=report, media_type="application/json", status_code=201 if persist else 200
            )
    finally:
        for upload in uploads.values():
            await upload.close()


def _request_directory() -> TemporaryDirectory[str]:
    return TemporaryDirectory(prefix="reconcile-api-")


def _resolve_allowed_origins(
    allowed_origins: str | Sequence[str] | None,
) -> tuple[str, ...]:
    if allowed_origins is None:
        configured = os.environ.get(ALLOWED_ORIGINS_ENV, "").split(",")
    elif isinstance(allowed_origins, str):
        configured = (allowed_origins,)
    else:
        configured = allowed_origins
    origins: list[str] = []
    for value in configured:
        origin = value.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            raise ValueError(f"{ALLOWED_ORIGINS_ENV} does not accept wildcard origins")

        try:
            validate_origin(origin)
        except ValueError:
            raise ValueError(f"Invalid origin configured in {ALLOWED_ORIGINS_ENV}") from None
        if origin not in origins:
            origins.append(origin)

    return tuple(origins)


async def _write_upload(
    upload: UploadFile,
    destination: Path,
    *,
    field: str,
    max_bytes: int,
) -> UploadedSource:
    size = 0
    digest = sha256()
    with destination.open("xb") as destination_file:
        while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise _FileTooLargeError(field, max_bytes)
            destination_file.write(chunk)
            digest.update(chunk)
    return UploadedSource(safe_filename(upload.filename), size, digest.hexdigest())


def _render_reconciliation(
    purchase_order_path: Path,
    receipt_path: Path,
    invoice_path: Path,
) -> str:
    purchase_orders = load_purchase_orders(purchase_order_path)
    receipts = load_goods_receipts(receipt_path)
    invoices = load_invoices(invoice_path)
    results, summary = reconcile(purchase_orders, receipts, invoices)
    return render_json_report(results, summary)


def _validation_error_response(error: CsvValidationError) -> dict[str, object]:
    return {
        "error": "validation_error",
        "message": "Uploaded CSV data failed validation.",
        "issues": [
            {
                "file": _FIELD_BY_FILENAME.get(issue.source.name, issue.source.name),
                "source": issue.source.name,
                "row": issue.row_number,
                "column": issue.column,
                "value": issue.value,
                "reason": issue.reason,
            }
            for issue in error.issues
        ],
    }


app = create_app()
