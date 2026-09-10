"""Typed HTTP reports; the legacy report retains its original renderer."""

import json
from collections.abc import Mapping
from dataclasses import fields
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from reconcile import load_goods_receipts, load_invoices, load_purchase_orders, reconcile
from reconcile.analysis import analyze_invoice_po, analyze_invoice_receipt, analyze_po_receipt
from reconcile.analysis.models import (
    AnalysisMode,
    FulfillmentStatus,
    InvoicePoResult,
    InvoiceReceiptResult,
    OrphanReceipt,
    PoReceiptResult,
)
from reconcile.models import (
    CurrencyAmount,
    GoodsReceiptLine,
    InvoiceLine,
    IssueCode,
    PurchaseOrderLine,
    ReconciliationResult,
)


class InvoiceSummary(BaseModel):
    invoices_processed: int
    invoice_lines_processed: int
    matched_lines: int
    review_required_lines: int
    issue_counts: dict[IssueCode, int]


class InvoicePoSummaryResponse(InvoiceSummary):
    disputed_amounts: dict[str, str]


class InvoiceReceiptSummaryResponse(InvoiceSummary):
    unsupported_amounts: dict[str, str]


class PoReceiptSummaryResponse(BaseModel):
    purchase_orders_processed: int
    po_lines_processed: int
    receipt_lines_processed: int
    status_counts: dict[FulfillmentStatus, int]
    orphan_receipt_lines: int
    outstanding_values: dict[str, str]
    over_received_values: dict[str, str]


class InvoicePoReport(BaseModel):
    mode: Literal[AnalysisMode.INVOICE_PO] = AnalysisMode.INVOICE_PO
    summary: InvoicePoSummaryResponse
    results: tuple[InvoicePoResult, ...]


class InvoiceReceiptReport(BaseModel):
    mode: Literal[AnalysisMode.INVOICE_RECEIPT] = AnalysisMode.INVOICE_RECEIPT
    summary: InvoiceReceiptSummaryResponse
    results: tuple[InvoiceReceiptResult, ...]


class PoReceiptReport(BaseModel):
    mode: Literal[AnalysisMode.PO_RECEIPT] = AnalysisMode.PO_RECEIPT
    summary: PoReceiptSummaryResponse
    results: tuple[PoReceiptResult, ...]
    orphan_receipts: tuple[OrphanReceipt, ...]


class ThreeWayReport(BaseModel):
    mode: Literal[AnalysisMode.THREE_WAY] = AnalysisMode.THREE_WAY
    summary: InvoicePoSummaryResponse
    results: tuple[ReconciliationResult, ...]


AnalysisReport = Annotated[
    InvoicePoReport | InvoiceReceiptReport | PoReceiptReport | ThreeWayReport,
    Field(discriminator="mode"),
]


def _summary_mapping(summary: object) -> dict[str, object]:
    mapping = {}
    for field in fields(summary):
        value = getattr(summary, field.name)
        if isinstance(value, tuple):
            value = (
                {entry.currency: format(entry.amount, "f") for entry in value}
                if value and isinstance(value[0], CurrencyAmount)
                else dict(value)
            )
        mapping[field.name] = value
    return mapping


def render_analysis(mode: AnalysisMode, paths: Mapping[str, Path]) -> str:
    return render_records(mode, load_analysis_sources(paths))


def load_analysis_sources(
    paths: Mapping[str, Path],
) -> dict[str, tuple[PurchaseOrderLine | GoodsReceiptLine | InvoiceLine, ...]]:
    loaders = {
        "purchase_orders": load_purchase_orders,
        "receipts": load_goods_receipts,
        "invoices": load_invoices,
    }
    return {field: loaders[field](path) for field, path in paths.items()}


def render_records(mode: AnalysisMode, sources: Mapping[str, tuple]) -> str:
    match mode:
        case AnalysisMode.INVOICE_PO:
            rows, summary = analyze_invoice_po(sources["purchase_orders"], sources["invoices"])
            report = InvoicePoReport(results=rows, summary=_summary_mapping(summary))
        case AnalysisMode.INVOICE_RECEIPT:
            rows, summary = analyze_invoice_receipt(sources["receipts"], sources["invoices"])
            report = InvoiceReceiptReport(results=rows, summary=_summary_mapping(summary))
        case AnalysisMode.PO_RECEIPT:
            rows, orphans, summary = analyze_po_receipt(
                sources["purchase_orders"],
                sources["receipts"],
            )
            report = PoReceiptReport(
                results=rows, orphan_receipts=orphans, summary=_summary_mapping(summary)
            )
        case AnalysisMode.THREE_WAY:
            rows, summary = reconcile(
                sources["purchase_orders"],
                sources["receipts"],
                sources["invoices"],
            )
            report = ThreeWayReport(results=rows, summary=_summary_mapping(summary))
        case _:
            raise ValueError("Unsupported analysis mode")
    return json.dumps(report.model_dump(), default=_wire_value, indent=2, ensure_ascii=False) + "\n"


def _wire_value(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("Unsupported report value")
