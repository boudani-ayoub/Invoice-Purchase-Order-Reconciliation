"""Domain and result models independent of file loading and presentation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class IssueCode(StrEnum):
    UNKNOWN_PO = "UNKNOWN_PO"
    UNKNOWN_ITEM = "UNKNOWN_ITEM"
    SUPPLIER_MISMATCH = "SUPPLIER_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    QUANTITY_EXCEEDS_RECEIPT = "QUANTITY_EXCEEDS_RECEIPT"
    QUANTITY_EXCEEDS_PO = "QUANTITY_EXCEEDS_PO"
    MISSING_RECEIPT = "MISSING_RECEIPT"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"


@dataclass(frozen=True, slots=True)
class PurchaseOrderLine:
    po_number: str
    line_number: int
    supplier_id: str
    order_date: date
    currency: str
    item_code: str
    description: str
    ordered_quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class GoodsReceiptLine:
    receipt_id: str
    line_number: int
    po_number: str
    po_line_number: int
    receipt_date: date
    item_code: str
    received_quantity: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    invoice_number: str
    line_number: int
    supplier_id: str
    invoice_date: date
    po_number: str
    po_line_number: int
    currency: str
    item_code: str
    invoiced_quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    supplier_id: str
    invoice_number: str
    invoice_line_number: int
    invoice_date: date
    po_number: str
    po_line_number: int
    item_code: str
    status: ReconciliationStatus
    issues: tuple[IssueCode, ...]
    ordered_quantity: Decimal | None
    received_quantity: Decimal | None
    previously_invoiced_quantity: Decimal
    current_invoiced_quantity: Decimal
    supported_quantity: Decimal | None
    invoice_unit_price: Decimal
    po_unit_price: Decimal | None
    potential_disputed_amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class CurrencyAmount:
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    invoices_processed: int
    invoice_lines_processed: int
    matched_lines: int
    review_required_lines: int
    issue_counts: tuple[tuple[IssueCode, int], ...]
    disputed_amounts: tuple[CurrencyAmount, ...]
