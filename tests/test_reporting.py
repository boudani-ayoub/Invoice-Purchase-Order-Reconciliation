import csv
import json
from io import StringIO

import pytest
from test_reconciliation import invoice_line, po_line, receipt_line

from reconcile import (
    IssueCode,
    reconcile,
    render_csv_results,
    render_csv_summary,
    render_json_report,
    render_terminal_report,
)

RESULT_FIELDS = (
    "supplier_id",
    "invoice_number",
    "invoice_line_number",
    "invoice_date",
    "po_number",
    "po_line_number",
    "item_code",
    "status",
    "issues",
    "ordered_quantity",
    "received_quantity",
    "previously_invoiced_quantity",
    "current_invoiced_quantity",
    "supported_quantity",
    "invoice_unit_price",
    "po_unit_price",
    "potential_disputed_amount",
    "currency",
)


def duplicate_run():
    duplicate = invoice_line(invoice_number="INV-DUP", quantity="70")
    return reconcile((po_line(),), (receipt_line(),), (duplicate, duplicate))


def empty_run():
    return reconcile((po_line(),), (receipt_line(),), ())


def test_json_result_schema_uses_explicit_serialization_contract() -> None:
    results, summary = reconcile(
        (po_line(quantity="0.25", price="101.50"),),
        (receipt_line(quantity="0.25"),),
        (invoice_line(quantity="0.25", price="101.50"),),
    )

    rendered = render_json_report(results, summary)
    report = json.loads(rendered)
    result = report["results"][0]

    assert rendered.endswith("\n")
    assert list(report) == ["summary", "results"]
    assert tuple(result) == RESULT_FIELDS
    assert result == {
        "supplier_id": "SUP-ONE",
        "invoice_number": "INV-100",
        "invoice_line_number": 1,
        "invoice_date": "2026-01-03",
        "po_number": "PO-100",
        "po_line_number": 1,
        "item_code": "ITEM-A",
        "status": "MATCHED",
        "issues": [],
        "ordered_quantity": "0.25",
        "received_quantity": "0.25",
        "previously_invoiced_quantity": "0",
        "current_invoiced_quantity": "0.25",
        "supported_quantity": "0.25",
        "invoice_unit_price": "101.50",
        "po_unit_price": "101.50",
        "potential_disputed_amount": "0.00",
        "currency": "MAD",
    }


def test_json_review_result_uses_stable_enum_values_and_issue_order() -> None:
    results, summary = reconcile(
        (po_line(price="10"),),
        (receipt_line(quantity="80"),),
        (
            invoice_line(
                supplier_id="SUP-OTHER",
                currency="USD",
                quantity="120",
                price="12",
            ),
        ),
    )

    result = json.loads(render_json_report(results, summary))["results"][0]

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["issues"] == [
        "SUPPLIER_MISMATCH",
        "CURRENCY_MISMATCH",
        "QUANTITY_EXCEEDS_PO",
        "QUANTITY_EXCEEDS_RECEIPT",
        "PRICE_MISMATCH",
    ]


@pytest.mark.parametrize(
    ("po_number", "item_code", "expected_issue"),
    [
        ("PO-UNKNOWN", "ITEM-A", "UNKNOWN_PO"),
        ("PO-100", "ITEM-UNKNOWN", "UNKNOWN_ITEM"),
    ],
)
def test_json_unknown_reference_uses_null_for_unknown_po_values(
    po_number: str,
    item_code: str,
    expected_issue: str,
) -> None:
    results, summary = reconcile(
        (po_line(),),
        (receipt_line(),),
        (invoice_line(po_number=po_number, item_code=item_code),),
    )

    result = json.loads(render_json_report(results, summary))["results"][0]

    assert result["issues"] == [expected_issue]
    assert result["ordered_quantity"] is None
    assert result["received_quantity"] is None
    assert result["supported_quantity"] is None
    assert result["po_unit_price"] is None


def test_json_summary_uses_duplicate_safe_authoritative_totals() -> None:
    results, summary = duplicate_run()

    report = json.loads(render_json_report(results, summary))

    assert [row["potential_disputed_amount"] for row in report["results"]] == [
        "700.00",
        "700.00",
    ]
    assert report["summary"] == {
        "invoices_processed": 1,
        "invoice_lines_processed": 2,
        "matched_lines": 0,
        "review_required_lines": 2,
        "issue_counts": {"DUPLICATE_INVOICE": 2},
        "disputed_amounts": {"MAD": "700.00"},
    }


def test_json_empty_run_has_complete_schema() -> None:
    results, summary = empty_run()

    report = json.loads(render_json_report(results, summary))

    assert report == {
        "summary": {
            "invoices_processed": 0,
            "invoice_lines_processed": 0,
            "matched_lines": 0,
            "review_required_lines": 0,
            "issue_counts": {},
            "disputed_amounts": {},
        },
        "results": [],
    }


def test_csv_results_use_stable_schema_values_and_blank_optionals() -> None:
    results, _ = reconcile(
        (po_line(),),
        (receipt_line(),),
        (
            invoice_line(invoice_number="INV-MATCH"),
            invoice_line(invoice_number="INV-UNKNOWN", po_number="PO-UNKNOWN"),
        ),
    )

    rendered = render_csv_results(results)
    rows = list(csv.DictReader(StringIO(rendered)))

    assert "\r\n" not in rendered
    assert tuple(rows[0]) == RESULT_FIELDS
    assert len(rows) == 2
    assert rows[0]["status"] == "MATCHED"
    assert rows[0]["issues"] == ""
    assert rows[0]["invoice_date"] == "2026-01-03"
    assert rows[0]["ordered_quantity"] == "100"
    assert rows[0]["invoice_unit_price"] == "10"
    assert rows[0]["potential_disputed_amount"] == "0.00"
    assert rows[1]["issues"] == "UNKNOWN_PO"
    assert rows[1]["ordered_quantity"] == ""
    assert rows[1]["received_quantity"] == ""
    assert rows[1]["supported_quantity"] == ""
    assert rows[1]["po_unit_price"] == ""


def test_csv_results_encode_multiple_issues_with_pipe_separator() -> None:
    results, _ = reconcile(
        (po_line(),),
        (receipt_line(quantity="80"),),
        (invoice_line(quantity="120", price="12"),),
    )

    row = next(csv.DictReader(StringIO(render_csv_results(results))))

    assert row["issues"] == ("QUANTITY_EXCEEDS_PO|QUANTITY_EXCEEDS_RECEIPT|PRICE_MISMATCH")


def test_csv_results_quote_special_characters_and_preserve_lf() -> None:
    supplier_id = 'SUP,"SPECIAL"'
    item_code = "ITEM,\nSPECIAL"
    results, _ = reconcile(
        (po_line(supplier_id=supplier_id, item_code=item_code),),
        (receipt_line(item_code=item_code),),
        (invoice_line(supplier_id=supplier_id, item_code=item_code),),
    )

    rendered = render_csv_results(results)
    row = next(csv.DictReader(StringIO(rendered)))

    assert "\r\n" not in rendered
    assert row["supplier_id"] == supplier_id
    assert row["item_code"] == item_code


def test_csv_empty_results_still_contain_header() -> None:
    results, _ = empty_run()

    assert render_csv_results(results) == ",".join(RESULT_FIELDS) + "\n"


def test_csv_summary_uses_one_stable_duplicate_safe_schema() -> None:
    results, summary = duplicate_run()

    rendered = render_csv_summary(summary)
    result_rows = list(csv.DictReader(StringIO(render_csv_results(results))))
    rows = list(csv.reader(StringIO(rendered)))

    assert "\r\n" not in rendered
    assert [row["potential_disputed_amount"] for row in result_rows] == [
        "700.00",
        "700.00",
    ]
    assert rows == [
        ["category", "key", "value"],
        ["metric", "invoices_processed", "1"],
        ["metric", "invoice_lines_processed", "2"],
        ["metric", "matched_lines", "0"],
        ["metric", "review_required_lines", "2"],
        ["issue", "DUPLICATE_INVOICE", "2"],
        ["disputed_amount", "MAD", "700.00"],
    ]
    assert "1400.00" not in rendered


def test_csv_empty_summary_still_contains_core_metrics() -> None:
    _, summary = empty_run()

    assert list(csv.reader(StringIO(render_csv_summary(summary)))) == [
        ["category", "key", "value"],
        ["metric", "invoices_processed", "0"],
        ["metric", "invoice_lines_processed", "0"],
        ["metric", "matched_lines", "0"],
        ["metric", "review_required_lines", "0"],
    ]


def test_terminal_report_contains_actionable_review_details() -> None:
    results, summary = reconcile(
        (po_line(price="100"),),
        (receipt_line(quantity="80"),),
        (invoice_line(invoice_number="INV-REVIEW", quantity="100", price="101"),),
    )

    rendered = render_terminal_report(results, summary)

    assert "Invoices processed: 1" in rendered
    assert "Matched: 0" in rendered
    assert "Review required: 1" in rendered
    assert "QUANTITY_EXCEEDS_RECEIPT: 1" in rendered
    assert "MAD: 2020.00" in rendered
    assert "SUP-ONE | INV-REVIEW | line 1 | 2026-01-03" in rendered
    assert "PO: PO-100/1 | Item: ITEM-A" in rendered
    assert "Issues: QUANTITY_EXCEEDS_RECEIPT" in rendered
    assert "Invoice quantity: 100 | Supported quantity: 80" in rendered
    assert "Invoice unit price: 101 | PO unit price: 100" in rendered
    assert "Disputed: 2020.00 MAD" in rendered


def test_terminal_unknown_po_uses_human_readable_missing_values() -> None:
    results, summary = reconcile(
        (po_line(),),
        (receipt_line(),),
        (invoice_line(po_number="PO-UNKNOWN"),),
    )

    rendered = render_terminal_report(results, summary)

    assert "Supported quantity: -" in rendered
    assert "PO unit price: -" in rendered
    assert "None" not in rendered


def test_terminal_report_uses_duplicate_safe_authoritative_total() -> None:
    results, summary = duplicate_run()

    rendered = render_terminal_report(results, summary)

    assert rendered.count("Disputed: 700.00 MAD") == 2
    assert rendered.count("MAD: 700.00") == 1
    assert "1400.00" not in rendered


def test_terminal_empty_run_is_explicit() -> None:
    results, summary = empty_run()

    rendered = render_terminal_report(results, summary)

    assert "Invoices processed: 0" in rendered
    assert "Invoice lines processed: 0" in rendered
    assert "Matched: 0" in rendered
    assert "Review required: 0" in rendered
    assert "No invoice lines require review." in rendered


def test_renderers_are_deterministic_and_preserve_result_order() -> None:
    results, summary = reconcile(
        (po_line(),),
        (receipt_line(),),
        (
            invoice_line(invoice_number="INV-A", quantity="40"),
            invoice_line(invoice_number="INV-B", quantity="60"),
        ),
    )
    reversed_results = tuple(reversed(results))

    json_output = render_json_report(reversed_results, summary)
    csv_output = render_csv_results(reversed_results)
    terminal_output = render_terminal_report(reversed_results, summary)

    assert json_output == render_json_report(reversed_results, summary)
    assert csv_output == render_csv_results(reversed_results)
    assert terminal_output == render_terminal_report(reversed_results, summary)
    assert "INV-A" not in terminal_output
    assert "INV-B" not in terminal_output
    assert [row["invoice_number"] for row in json.loads(json_output)["results"]] == [
        "INV-B",
        "INV-A",
    ]
    assert [row["invoice_number"] for row in csv.DictReader(StringIO(csv_output))] == [
        "INV-B",
        "INV-A",
    ]


def test_sample_fixture_renders_all_formats() -> None:
    from pathlib import Path

    from reconcile import load_goods_receipts, load_invoices, load_purchase_orders

    sample_dir = Path(__file__).parents[1] / "examples" / "sample_data"
    purchase_orders = load_purchase_orders(sample_dir / "purchase_orders.csv")
    receipts = load_goods_receipts(sample_dir / "goods_receipts.csv")
    invoices = load_invoices(sample_dir / "invoices.csv")
    results, summary = reconcile(purchase_orders, receipts, invoices)

    json_report = json.loads(render_json_report(results, summary))
    result_rows = list(csv.DictReader(StringIO(render_csv_results(results))))
    summary_rows = list(csv.reader(StringIO(render_csv_summary(summary))))
    terminal_report = render_terminal_report(results, summary)

    assert len(json_report["results"]) == len(result_rows) == 17
    assert json_report["summary"]["invoices_processed"] == 15
    assert json_report["summary"]["invoice_lines_processed"] == 17
    assert json_report["summary"]["matched_lines"] == 6
    assert json_report["summary"]["review_required_lines"] == 11
    assert json_report["summary"]["issue_counts"] == {
        "UNKNOWN_PO": 1,
        "UNKNOWN_ITEM": 1,
        "DUPLICATE_INVOICE": 2,
        "SUPPLIER_MISMATCH": 1,
        "CURRENCY_MISMATCH": 1,
        "MISSING_RECEIPT": 1,
        "QUANTITY_EXCEEDS_PO": 2,
        "QUANTITY_EXCEEDS_RECEIPT": 2,
        "PRICE_MISMATCH": 1,
    }
    assert json_report["summary"]["disputed_amounts"] == {
        "EUR": "2450.00",
        "MAD": "10199.00",
        "USD": "75.00",
    }
    for invoice_number in ("INV-011", "INV-UNKNOWN"):
        csv_row = next(row for row in result_rows if row["invoice_number"] == invoice_number)
        json_row = next(
            row for row in json_report["results"] if row["invoice_number"] == invoice_number
        )
        assert csv_row["po_unit_price"] == ""
        assert json_row["po_unit_price"] is None
    assert isinstance(json_report["results"][0]["invoice_unit_price"], str)
    assert ["disputed_amount", "MAD", "10199.00"] in summary_rows
    assert "Review required: 11" in terminal_report
    assert "MAD: 10199.00" in terminal_report
    assert IssueCode.UNKNOWN_PO.value in terminal_report
