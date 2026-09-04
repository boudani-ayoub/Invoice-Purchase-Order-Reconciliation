from decimal import Decimal
from pathlib import Path

from reconcile import (
    CurrencyAmount,
    IssueCode,
    ReconciliationStatus,
    load_goods_receipts,
    load_invoices,
    load_purchase_orders,
    reconcile,
)

SAMPLE_DATA_DIR = Path(__file__).parents[1] / "examples" / "sample_data"


def test_every_sample_scenario_has_expected_findings() -> None:
    purchase_orders = load_purchase_orders(SAMPLE_DATA_DIR / "purchase_orders.csv")
    receipts = load_goods_receipts(SAMPLE_DATA_DIR / "goods_receipts.csv")
    invoices = load_invoices(SAMPLE_DATA_DIR / "invoices.csv")

    results, summary = reconcile(purchase_orders, receipts, invoices)
    issues_by_line = {
        (result.invoice_number, result.invoice_line_number): result.issues for result in results
    }

    assert issues_by_line[("INV-001", 1)] == ()
    assert issues_by_line[("INV-002", 1)] == (IssueCode.QUANTITY_EXCEEDS_RECEIPT,)
    assert issues_by_line[("INV-003", 1)] == (IssueCode.PRICE_MISMATCH,)
    assert issues_by_line[("INV-004", 1)] == ()
    assert issues_by_line[("INV-005-A", 1)] == ()
    assert issues_by_line[("INV-005-B", 1)] == (
        IssueCode.QUANTITY_EXCEEDS_PO,
        IssueCode.QUANTITY_EXCEEDS_RECEIPT,
    )
    assert issues_by_line[("INV-006", 1)] == (IssueCode.MISSING_RECEIPT,)
    assert issues_by_line[("INV-007", 1)] == (IssueCode.SUPPLIER_MISMATCH,)
    assert issues_by_line[("INV-008", 1)] == ()
    assert issues_by_line[("INV-008", 2)] == ()
    assert issues_by_line[("INV-009", 1)] == (IssueCode.CURRENCY_MISMATCH,)
    assert issues_by_line[("INV-010", 1)] == (IssueCode.QUANTITY_EXCEEDS_PO,)
    assert issues_by_line[("INV-011", 1)] == (IssueCode.UNKNOWN_ITEM,)
    assert issues_by_line[("INV-UNKNOWN", 1)] == (IssueCode.UNKNOWN_PO,)
    assert issues_by_line[("INV-012", 1)] == (IssueCode.DUPLICATE_INVOICE,)
    assert issues_by_line[("INV-013", 1)] == ()

    duplicate_results = [result for result in results if result.invoice_number == "INV-012"]
    assert len(duplicate_results) == 2
    assert all(result.issues == (IssueCode.DUPLICATE_INVOICE,) for result in duplicate_results)

    assert summary.invoices_processed == 15
    assert summary.invoice_lines_processed == 17
    assert summary.matched_lines == 6
    assert summary.review_required_lines == 11
    assert summary.issue_counts == (
        (IssueCode.UNKNOWN_PO, 1),
        (IssueCode.UNKNOWN_ITEM, 1),
        (IssueCode.DUPLICATE_INVOICE, 2),
        (IssueCode.SUPPLIER_MISMATCH, 1),
        (IssueCode.CURRENCY_MISMATCH, 1),
        (IssueCode.MISSING_RECEIPT, 1),
        (IssueCode.QUANTITY_EXCEEDS_PO, 2),
        (IssueCode.QUANTITY_EXCEEDS_RECEIPT, 2),
        (IssueCode.PRICE_MISMATCH, 1),
    )
    assert summary.disputed_amounts == (
        CurrencyAmount(currency="EUR", amount=Decimal("2450.00")),
        CurrencyAmount(currency="MAD", amount=Decimal("10199.00")),
        CurrencyAmount(currency="USD", amount=Decimal("75.00")),
    )


def test_sample_result_statuses_follow_issue_presence() -> None:
    purchase_orders = load_purchase_orders(SAMPLE_DATA_DIR / "purchase_orders.csv")
    receipts = load_goods_receipts(SAMPLE_DATA_DIR / "goods_receipts.csv")
    invoices = load_invoices(SAMPLE_DATA_DIR / "invoices.csv")

    results, _ = reconcile(purchase_orders, receipts, invoices)

    for result in results:
        expected = (
            ReconciliationStatus.REVIEW_REQUIRED if result.issues else ReconciliationStatus.MATCHED
        )
        assert result.status is expected
