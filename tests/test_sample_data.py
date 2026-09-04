import csv
from pathlib import Path

import pytest

from reconcile.schemas import INPUT_SCHEMAS, CsvSchema

SAMPLE_DATA_DIR = Path(__file__).parents[1] / "examples" / "sample_data"


@pytest.mark.parametrize("schema", INPUT_SCHEMAS, ids=lambda schema: schema.filename)
def test_sample_file_uses_canonical_headers(schema: CsvSchema) -> None:
    sample_path = SAMPLE_DATA_DIR / schema.filename

    with sample_path.open(encoding="utf-8", newline="") as sample_file:
        reader = csv.reader(sample_file)
        headers = tuple(next(reader))
        rows = list(reader)

    assert headers == schema.headers
    assert rows
    assert all(len(row) == len(headers) for row in rows)


def test_sample_data_contains_multiple_receipts_for_one_po_line() -> None:
    with (SAMPLE_DATA_DIR / "goods_receipts.csv").open(encoding="utf-8", newline="") as file:
        receipts = list(csv.DictReader(file))

    po_004_receipts = [row for row in receipts if row["po_number"] == "PO-004"]

    assert len(po_004_receipts) == 3
    assert sum(int(row["received_quantity"]) for row in po_004_receipts) == 100


def test_sample_data_contains_cumulative_over_invoicing_case() -> None:
    with (SAMPLE_DATA_DIR / "invoices.csv").open(encoding="utf-8", newline="") as file:
        invoices = list(csv.DictReader(file))

    po_005_invoices = [row for row in invoices if row["po_number"] == "PO-005"]

    assert len(po_005_invoices) == 2
    assert sum(int(row["invoiced_quantity"]) for row in po_005_invoices) == 120


def test_sample_data_contains_a_multi_line_invoice() -> None:
    with (SAMPLE_DATA_DIR / "invoices.csv").open(encoding="utf-8", newline="") as file:
        invoices = list(csv.DictReader(file))

    invoice_lines = [row for row in invoices if row["invoice_number"] == "INV-008"]

    assert {row["line_number"] for row in invoice_lines} == {"1", "2"}
