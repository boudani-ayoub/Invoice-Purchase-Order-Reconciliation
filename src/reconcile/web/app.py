"""FastAPI adapter for stateless reconciliation requests."""

import logging
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from reconcile import (
    CsvValidationError,
    load_goods_receipts,
    load_invoices,
    load_purchase_orders,
    reconcile,
    render_json_report,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 64 * 1024

_DISTRIBUTION_NAME = "invoice-purchase-order-reconciliation"
_INTERNAL_FILENAMES = {
    "purchase_orders": "purchase_orders.csv",
    "receipts": "goods_receipts.csv",
    "invoices": "invoices.csv",
}
_FIELD_BY_FILENAME = {filename: field for field, filename in _INTERNAL_FILENAMES.items()}
_LOGGER = logging.getLogger(__name__)


class _FileTooLargeError(Exception):
    def __init__(self, field: str, max_bytes: int) -> None:
        self.field = field
        self.max_bytes = max_bytes
        super().__init__(f"{field} exceeds the {max_bytes}-byte upload limit")


def create_app(*, max_upload_bytes: int = MAX_UPLOAD_BYTES) -> FastAPI:
    """Create the stateless HTTP application."""

    application = FastAPI(
        title="Invoice / Purchase Order Reconciliation API",
        version=version(_DISTRIBUTION_NAME),
        description=("Stateless HTTP access to the existing deterministic reconciliation engine."),
    )

    @application.exception_handler(Exception)
    async def internal_error_handler(request: Request, error: Exception) -> JSONResponse:
        _LOGGER.exception("Unhandled reconciliation API error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Internal server error."},
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
        try:
            with _request_directory() as directory:
                paths: dict[str, Path] = {}
                try:
                    for field, upload in uploads.items():
                        path = Path(directory) / _INTERNAL_FILENAMES[field]
                        await _write_upload(
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
                    report = await run_in_threadpool(
                        _render_reconciliation,
                        paths["purchase_orders"],
                        paths["receipts"],
                        paths["invoices"],
                    )
                except CsvValidationError as error:
                    return JSONResponse(
                        status_code=422,
                        content=_validation_error_response(error),
                    )

                return Response(content=report, media_type="application/json")
        finally:
            for upload in uploads.values():
                await upload.close()

    return application


def _request_directory() -> TemporaryDirectory[str]:
    return TemporaryDirectory(prefix="reconcile-api-")


async def _write_upload(
    upload: UploadFile,
    destination: Path,
    *,
    field: str,
    max_bytes: int,
) -> None:
    size = 0
    with destination.open("xb") as destination_file:
        while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise _FileTooLargeError(field, max_bytes)
            destination_file.write(chunk)


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
