import csv
from pathlib import Path

import pytest

from reconcile import CsvValidationError, load_purchase_orders


def test_oversized_csv_field_is_reported_as_controlled_validation_error(
    tmp_path: Path,
) -> None:
    oversized_description = "x" * (csv.field_size_limit() + 1)
    source = tmp_path / "purchase_orders.csv"
    source.write_text(
        "po_number,line_number,supplier_id,order_date,currency,item_code,description,"
        "ordered_quantity,unit_price\n"
        f"PO-100,1,SUP-ONE,2026-02-01,MAD,ITEM-A,{oversized_description},10,25.50\n",
        encoding="utf-8",
        newline="",
    )

    with pytest.raises(CsvValidationError) as captured:
        load_purchase_orders(source)

    assert len(captured.value.issues) == 1
    assert captured.value.issues[0].column == "<row>"
    assert "invalid CSV" in captured.value.issues[0].reason
    assert "field larger than field limit" in captured.value.issues[0].reason
