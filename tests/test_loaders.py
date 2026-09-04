import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from reconcile import (
    CsvValidationError,
    GoodsReceiptLine,
    InvoiceLine,
    PurchaseOrderLine,
    load_goods_receipts,
    load_invoices,
    load_purchase_orders,
)
from reconcile.schemas import GOODS_RECEIPT_SCHEMA, INVOICE_SCHEMA, PURCHASE_ORDER_SCHEMA, CsvSchema

SAMPLE_DATA_DIR = Path(__file__).parents[1] / "examples" / "sample_data"

VALID_PO = {
    "po_number": "PO-100",
    "line_number": "1",
    "supplier_id": "SUP-ONE",
    "order_date": "2026-02-01",
    "currency": "MAD",
    "item_code": "ITEM-A",
    "description": "Office item",
    "ordered_quantity": "10",
    "unit_price": "25.50",
}

VALID_RECEIPT = {
    "receipt_id": "REC-100",
    "line_number": "1",
    "po_number": "PO-100",
    "po_line_number": "1",
    "receipt_date": "2026-02-03",
    "item_code": "ITEM-A",
    "received_quantity": "10",
}

VALID_INVOICE = {
    "invoice_number": "INV-100",
    "line_number": "1",
    "supplier_id": "SUP-ONE",
    "invoice_date": "2026-02-04",
    "po_number": "PO-100",
    "po_line_number": "1",
    "currency": "MAD",
    "item_code": "ITEM-A",
    "invoiced_quantity": "10",
    "unit_price": "25.50",
}


def write_rows(
    tmp_path: Path,
    schema: CsvSchema,
    rows: list[dict[str, str]],
) -> Path:
    path = tmp_path / schema.filename
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=schema.headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_raw(tmp_path: Path, content: str, filename: str = "purchase_orders.csv") -> Path:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8", newline="")
    return path


def test_valid_purchase_order_loads_domain_types(tmp_path: Path) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO])

    records = load_purchase_orders(path)

    assert records == (
        PurchaseOrderLine(
            po_number="PO-100",
            line_number=1,
            supplier_id="SUP-ONE",
            order_date=date(2026, 2, 1),
            currency="MAD",
            item_code="ITEM-A",
            description="Office item",
            ordered_quantity=Decimal("10"),
            unit_price=Decimal("25.50"),
        ),
    )


def test_valid_goods_receipt_loads_domain_types(tmp_path: Path) -> None:
    path = write_rows(tmp_path, GOODS_RECEIPT_SCHEMA, [VALID_RECEIPT])

    records = load_goods_receipts(path)

    assert isinstance(records, tuple)
    assert isinstance(records[0], GoodsReceiptLine)
    assert records[0].line_number == 1
    assert records[0].receipt_date == date(2026, 2, 3)
    assert records[0].received_quantity == Decimal("10")


def test_valid_invoice_loads_domain_types(tmp_path: Path) -> None:
    path = write_rows(tmp_path, INVOICE_SCHEMA, [VALID_INVOICE])

    records = load_invoices(path)

    assert isinstance(records, tuple)
    assert isinstance(records[0], InvoiceLine)
    assert records[0].po_line_number == 1
    assert records[0].invoice_date == date(2026, 2, 4)
    assert records[0].unit_price == Decimal("25.50")


def test_fractional_quantity_zero_price_and_blank_description_are_valid(tmp_path: Path) -> None:
    row = VALID_PO | {
        "description": "",
        "ordered_quantity": "0.25",
        "unit_price": "0",
    }
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [row])

    record = load_purchase_orders(path)[0]

    assert record.description == ""
    assert record.ordered_quantity == Decimal("0.25")
    assert record.unit_price == Decimal("0")


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = write_raw(tmp_path, "")

    with pytest.raises(CsvValidationError) as captured:
        load_purchase_orders(path)

    assert captured.value.issues[0].row_number == 1
    assert captured.value.issues[0].column == "<header>"
    assert captured.value.issues[0].reason == "file is empty"


def test_header_without_data_rows_is_rejected(tmp_path: Path) -> None:
    path = write_raw(tmp_path, ",".join(PURCHASE_ORDER_SCHEMA.headers) + "\n")

    with pytest.raises(CsvValidationError, match="no data rows"):
        load_purchase_orders(path)


def test_missing_source_is_reported_as_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"

    with pytest.raises(CsvValidationError) as captured:
        load_purchase_orders(path)

    issue = captured.value.issues[0]
    assert issue.row_number is None
    assert issue.column == "<file>"
    assert "unable to read file" in issue.reason


def test_non_utf8_source_is_rejected_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "purchase_orders.csv"
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(CsvValidationError, match="not valid UTF-8"):
        load_purchase_orders(path)


def test_malformed_csv_is_rejected_cleanly(tmp_path: Path) -> None:
    content = ",".join(PURCHASE_ORDER_SCHEMA.headers) + '\n"unterminated\n'
    path = write_raw(tmp_path, content)

    with pytest.raises(CsvValidationError, match="invalid CSV") as captured:
        load_purchase_orders(path)

    assert captured.value.issues[0].row_number == 2
    assert captured.value.issues[0].column == "<row>"


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        (PURCHASE_ORDER_SCHEMA.headers[:-1], "missing columns: unit_price"),
        (PURCHASE_ORDER_SCHEMA.headers + ("unexpected",), "unexpected columns: unexpected"),
        (
            (
                PURCHASE_ORDER_SCHEMA.headers[1],
                PURCHASE_ORDER_SCHEMA.headers[0],
                *PURCHASE_ORDER_SCHEMA.headers[2:],
            ),
            "column order does not match",
        ),
        (
            (PURCHASE_ORDER_SCHEMA.headers[0], *PURCHASE_ORDER_SCHEMA.headers[:-1]),
            "header contains duplicate columns: po_number",
        ),
    ],
    ids=("missing", "extra", "reordered", "duplicate"),
)
def test_invalid_headers_are_actionable(
    tmp_path: Path,
    headers: tuple[str, ...],
    reason: str,
) -> None:
    path = write_raw(tmp_path, ",".join(headers) + "\nvalue\n")

    with pytest.raises(CsvValidationError) as captured:
        load_purchase_orders(path)

    issue = captured.value.issues[0]
    assert issue.row_number == 1
    assert issue.column == "<header>"
    assert reason in issue.reason
    assert "expected:" in issue.reason


def test_row_with_wrong_field_count_is_rejected(tmp_path: Path) -> None:
    content = ",".join(PURCHASE_ORDER_SCHEMA.headers) + "\nPO-100,1\n"
    path = write_raw(tmp_path, content)

    with pytest.raises(CsvValidationError, match="expected 9 fields but received 2"):
        load_purchase_orders(path)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("po_number", "", "must not be blank"),
        ("supplier_id", "   ", "must not contain leading or trailing whitespace"),
        ("item_code", " ITEM-A", "must not contain leading or trailing whitespace"),
        ("ordered_quantity", "10 ", "must not contain leading or trailing whitespace"),
    ],
)
def test_required_text_values_are_validated(
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO | {field: value}])

    with pytest.raises(CsvValidationError) as captured:
        load_purchase_orders(path)

    issue = captured.value.issues[0]
    assert issue.column == field
    assert issue.value == value
    assert reason in issue.reason


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "abc"])
def test_invalid_positive_integers_are_rejected(tmp_path: Path, value: str) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO | {"line_number": value}])

    with pytest.raises(CsvValidationError, match="integer greater than zero"):
        load_purchase_orders(path)


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "abc", "NaN", "Infinity", "+10", "1e2", "1_000", ".5", "1."],
)
def test_invalid_positive_decimals_are_rejected(tmp_path: Path, value: str) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO | {"ordered_quantity": value}])

    with pytest.raises(CsvValidationError, match="finite decimal greater than zero"):
        load_purchase_orders(path)


@pytest.mark.parametrize("value", ["-0.01", "NaN", "Infinity"])
def test_invalid_non_negative_decimals_are_rejected(tmp_path: Path, value: str) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO | {"unit_price": value}])

    with pytest.raises(CsvValidationError, match="finite decimal zero or greater"):
        load_purchase_orders(path)


@pytest.mark.parametrize("value", ["banana", "2026-02-30", "02/01/2026"])
def test_invalid_dates_are_rejected(tmp_path: Path, value: str) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO | {"order_date": value}])

    with pytest.raises(CsvValidationError, match="valid date in YYYY-MM-DD format"):
        load_purchase_orders(path)


@pytest.mark.parametrize("value", ["mad", "US", "USDD", "123"])
def test_invalid_currency_codes_are_rejected(tmp_path: Path, value: str) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO | {"currency": value}])

    with pytest.raises(CsvValidationError, match="three-letter uppercase currency code"):
        load_purchase_orders(path)


def test_multiple_row_errors_are_collected(tmp_path: Path) -> None:
    rows = [
        VALID_PO | {"ordered_quantity": "-3"},
        VALID_PO | {"line_number": "2", "order_date": "banana"},
    ]
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, rows)

    with pytest.raises(CsvValidationError) as captured:
        load_purchase_orders(path)

    assert [(issue.row_number, issue.column) for issue in captured.value.issues] == [
        (2, "ordered_quantity"),
        (3, "order_date"),
    ]
    assert str(path) in str(captured.value)
    assert "value: '-3'" in str(captured.value)


def test_duplicate_purchase_order_line_is_rejected(tmp_path: Path) -> None:
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO, VALID_PO])

    with pytest.raises(CsvValidationError, match="duplicate record identity") as captured:
        load_purchase_orders(path)

    assert captured.value.issues[0].row_number == 3
    assert "first seen at CSV row 2" in captured.value.issues[0].reason


def test_duplicate_goods_receipt_line_is_rejected(tmp_path: Path) -> None:
    path = write_rows(tmp_path, GOODS_RECEIPT_SCHEMA, [VALID_RECEIPT, VALID_RECEIPT])

    with pytest.raises(CsvValidationError, match="duplicate record identity"):
        load_goods_receipts(path)


def test_duplicate_invoice_line_is_preserved(tmp_path: Path) -> None:
    conflicting_copy = VALID_INVOICE | {"invoiced_quantity": "11"}
    path = write_rows(tmp_path, INVOICE_SCHEMA, [VALID_INVOICE, conflicting_copy])

    records = load_invoices(path)

    assert len(records) == 2
    assert [record.invoiced_quantity for record in records] == [Decimal("10"), Decimal("11")]


@pytest.mark.parametrize("field", ["supplier_id", "currency", "order_date"])
def test_inconsistent_purchase_order_document_is_rejected(tmp_path: Path, field: str) -> None:
    replacements = {
        "supplier_id": "SUP-TWO",
        "currency": "USD",
        "order_date": "2026-02-02",
    }
    second_line = VALID_PO | {
        "line_number": "2",
        "item_code": "ITEM-B",
        field: replacements[field],
    }
    path = write_rows(tmp_path, PURCHASE_ORDER_SCHEMA, [VALID_PO, second_line])

    with pytest.raises(CsvValidationError) as captured:
        load_purchase_orders(path)

    assert captured.value.issues[0].column == field
    assert "same document" in captured.value.issues[0].reason


@pytest.mark.parametrize(
    ("field", "value"),
    [("invoice_date", "2026-02-05"), ("currency", "USD")],
)
def test_inconsistent_invoice_document_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    second_line = VALID_INVOICE | {
        "line_number": "2",
        "item_code": "ITEM-B",
        field: value,
    }
    path = write_rows(tmp_path, INVOICE_SCHEMA, [VALID_INVOICE, second_line])

    with pytest.raises(CsvValidationError) as captured:
        load_invoices(path)

    assert captured.value.issues[0].column == field


def test_goods_receipt_loader_does_not_invent_document_constraints(tmp_path: Path) -> None:
    second_line = VALID_RECEIPT | {
        "line_number": "2",
        "receipt_date": "2026-02-04",
        "item_code": "ITEM-B",
    }
    path = write_rows(tmp_path, GOODS_RECEIPT_SCHEMA, [VALID_RECEIPT, second_line])

    records = load_goods_receipts(path)

    assert len(records) == 2


def test_sample_files_load_through_public_api() -> None:
    purchase_orders = load_purchase_orders(SAMPLE_DATA_DIR / PURCHASE_ORDER_SCHEMA.filename)
    receipts = load_goods_receipts(SAMPLE_DATA_DIR / GOODS_RECEIPT_SCHEMA.filename)
    invoices = load_invoices(SAMPLE_DATA_DIR / INVOICE_SCHEMA.filename)

    assert len(purchase_orders) == 14
    assert len(receipts) == 15
    assert len(invoices) == 17


def test_reconciliation_findings_survive_invoice_loading() -> None:
    invoices = load_invoices(SAMPLE_DATA_DIR / INVOICE_SCHEMA.filename)
    loaded_invoice_numbers = {invoice.invoice_number for invoice in invoices}

    assert {
        "INV-UNKNOWN",
        "INV-011",
        "INV-007",
        "INV-009",
        "INV-010",
        "INV-006",
    } <= loaded_invoice_numbers


def test_records_preserve_source_order(tmp_path: Path) -> None:
    second = VALID_INVOICE | {"invoice_number": "INV-099"}
    path = write_rows(tmp_path, INVOICE_SCHEMA, [VALID_INVOICE, second])

    records = load_invoices(path)

    assert [record.invoice_number for record in records] == ["INV-100", "INV-099"]
