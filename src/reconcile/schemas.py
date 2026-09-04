"""Canonical CSV contracts for the three V0.1 input files."""

from dataclasses import dataclass
from enum import StrEnum


class ColumnType(StrEnum):
    TEXT = "text"
    NON_EMPTY_TEXT = "non-empty text"
    POSITIVE_INTEGER = "positive integer"
    ISO_DATE = "ISO 8601 date (YYYY-MM-DD)"
    CURRENCY_CODE = "three-letter uppercase currency code"
    POSITIVE_DECIMAL = "positive decimal"
    NON_NEGATIVE_DECIMAL = "non-negative decimal"


class DuplicatePolicy(StrEnum):
    REJECT = "reject as invalid source data"
    REVIEW = "preserve for reconciliation review"


@dataclass(frozen=True, slots=True)
class ColumnDefinition:
    name: str
    data_type: ColumnType
    description: str


@dataclass(frozen=True, slots=True)
class CsvSchema:
    filename: str
    columns: tuple[ColumnDefinition, ...]
    key_columns: tuple[str, ...]
    duplicate_policy: DuplicatePolicy

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


PURCHASE_ORDER_SCHEMA = CsvSchema(
    filename="purchase_orders.csv",
    columns=(
        ColumnDefinition("po_number", ColumnType.NON_EMPTY_TEXT, "Supplier-facing PO identifier"),
        ColumnDefinition("line_number", ColumnType.POSITIVE_INTEGER, "Line number within the PO"),
        ColumnDefinition("supplier_id", ColumnType.NON_EMPTY_TEXT, "Internal supplier identifier"),
        ColumnDefinition("order_date", ColumnType.ISO_DATE, "Date the PO was issued"),
        ColumnDefinition("currency", ColumnType.CURRENCY_CODE, "PO line currency"),
        ColumnDefinition("item_code", ColumnType.NON_EMPTY_TEXT, "Purchased item identifier"),
        ColumnDefinition("description", ColumnType.TEXT, "Human-readable item description"),
        ColumnDefinition("ordered_quantity", ColumnType.POSITIVE_DECIMAL, "Quantity ordered"),
        ColumnDefinition("unit_price", ColumnType.NON_NEGATIVE_DECIMAL, "Agreed unit price"),
    ),
    key_columns=("po_number", "line_number"),
    duplicate_policy=DuplicatePolicy.REJECT,
)

GOODS_RECEIPT_SCHEMA = CsvSchema(
    filename="goods_receipts.csv",
    columns=(
        ColumnDefinition(
            "receipt_id", ColumnType.NON_EMPTY_TEXT, "Goods receipt document identifier"
        ),
        ColumnDefinition(
            "line_number", ColumnType.POSITIVE_INTEGER, "Line number within the receipt"
        ),
        ColumnDefinition("po_number", ColumnType.NON_EMPTY_TEXT, "Referenced PO identifier"),
        ColumnDefinition(
            "po_line_number", ColumnType.POSITIVE_INTEGER, "Referenced PO line number"
        ),
        ColumnDefinition(
            "receipt_date", ColumnType.ISO_DATE, "Date goods were recorded as received"
        ),
        ColumnDefinition("item_code", ColumnType.NON_EMPTY_TEXT, "Received item identifier"),
        ColumnDefinition("received_quantity", ColumnType.POSITIVE_DECIMAL, "Quantity received"),
    ),
    key_columns=("receipt_id", "line_number"),
    duplicate_policy=DuplicatePolicy.REJECT,
)

INVOICE_SCHEMA = CsvSchema(
    filename="invoices.csv",
    columns=(
        ColumnDefinition(
            "invoice_number", ColumnType.NON_EMPTY_TEXT, "Supplier-issued invoice identifier"
        ),
        ColumnDefinition(
            "line_number", ColumnType.POSITIVE_INTEGER, "Line number within the invoice"
        ),
        ColumnDefinition(
            "supplier_id", ColumnType.NON_EMPTY_TEXT, "Supplier identifier on the invoice"
        ),
        ColumnDefinition("invoice_date", ColumnType.ISO_DATE, "Date the invoice was issued"),
        ColumnDefinition("po_number", ColumnType.NON_EMPTY_TEXT, "Referenced PO identifier"),
        ColumnDefinition(
            "po_line_number", ColumnType.POSITIVE_INTEGER, "Referenced PO line number"
        ),
        ColumnDefinition("currency", ColumnType.CURRENCY_CODE, "Invoice line currency"),
        ColumnDefinition("item_code", ColumnType.NON_EMPTY_TEXT, "Invoiced item identifier"),
        ColumnDefinition("invoiced_quantity", ColumnType.POSITIVE_DECIMAL, "Quantity invoiced"),
        ColumnDefinition("unit_price", ColumnType.NON_NEGATIVE_DECIMAL, "Invoiced unit price"),
    ),
    key_columns=("supplier_id", "invoice_number", "line_number"),
    duplicate_policy=DuplicatePolicy.REVIEW,
)

INPUT_SCHEMAS = (PURCHASE_ORDER_SCHEMA, GOODS_RECEIPT_SCHEMA, INVOICE_SCHEMA)
