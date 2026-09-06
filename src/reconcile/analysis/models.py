"""Mode-specific reports and canonical workflow identifiers."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from reconcile.models import CurrencyAmount, IssueCode, ReconciliationStatus, ReconciliationSummary


class AnalysisMode(StrEnum):
    INVOICE_PO = "invoice-po"
    INVOICE_RECEIPT = "invoice-receipt"
    PO_RECEIPT = "po-receipt"
    THREE_WAY = "three-way"


class SourceType(StrEnum):
    PURCHASE_ORDERS = "purchase_orders"
    RECEIPTS = "receipts"
    INVOICES = "invoices"


REQUIRED_SOURCES = {
    AnalysisMode.INVOICE_PO: (SourceType.PURCHASE_ORDERS, SourceType.INVOICES),
    AnalysisMode.INVOICE_RECEIPT: (SourceType.RECEIPTS, SourceType.INVOICES),
    AnalysisMode.PO_RECEIPT: (SourceType.PURCHASE_ORDERS, SourceType.RECEIPTS),
    AnalysisMode.THREE_WAY: tuple(SourceType),
}


@dataclass(frozen=True, slots=True)
class InvoiceAnalysisLine:
    supplier_id: str
    invoice_number: str
    invoice_line_number: int
    invoice_date: date
    po_number: str
    po_line_number: int
    item_code: str
    status: ReconciliationStatus
    issues: tuple[IssueCode, ...]
    previously_invoiced_quantity: Decimal
    current_invoiced_quantity: Decimal
    supported_quantity: Decimal | None
    invoice_unit_price: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class InvoicePoResult(InvoiceAnalysisLine):
    ordered_quantity: Decimal | None
    po_unit_price: Decimal | None
    potential_disputed_amount: Decimal


@dataclass(frozen=True, slots=True)
class InvoicePoSummary(ReconciliationSummary):
    pass


@dataclass(frozen=True, slots=True)
class InvoiceReceiptResult(InvoiceAnalysisLine):
    received_quantity: Decimal
    potential_unsupported_amount: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceReceiptSummary:
    invoices_processed: int
    invoice_lines_processed: int
    matched_lines: int
    review_required_lines: int
    issue_counts: tuple[tuple[IssueCode, int], ...]
    unsupported_amounts: tuple[CurrencyAmount, ...]


class FulfillmentStatus(StrEnum):
    FULLY_RECEIVED = "FULLY_RECEIVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    NOT_RECEIVED = "NOT_RECEIVED"
    OVER_RECEIVED = "OVER_RECEIVED"


@dataclass(frozen=True, slots=True)
class PoReceiptResult:
    po_number: str
    po_line_number: int
    item_code: str
    supplier_id: str
    status: FulfillmentStatus
    ordered_quantity: Decimal
    received_quantity: Decimal
    outstanding_quantity: Decimal
    over_received_quantity: Decimal
    po_unit_price: Decimal
    currency: str
    outstanding_ordered_value: Decimal
    over_received_reference_value: Decimal


@dataclass(frozen=True, slots=True)
class OrphanReceipt:
    receipt_id: str
    receipt_line_number: int
    receipt_date: date
    po_number: str
    po_line_number: int
    item_code: str
    received_quantity: Decimal
    issue: IssueCode


@dataclass(frozen=True, slots=True)
class PoReceiptSummary:
    purchase_orders_processed: int
    po_lines_processed: int
    receipt_lines_processed: int
    status_counts: tuple[tuple[FulfillmentStatus, int], ...]
    orphan_receipt_lines: int
    outstanding_values: tuple[CurrencyAmount, ...]
    over_received_values: tuple[CurrencyAmount, ...]
