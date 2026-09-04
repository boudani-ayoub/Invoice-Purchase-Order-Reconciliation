from datetime import date
from decimal import Decimal

from test_reconciliation import invoice_line, po_line, receipt_line

from reconcile import IssueCode, ReconciliationStatus, reconcile


def test_exact_duplicate_rows_consume_capacity_once() -> None:
    duplicate = invoice_line(invoice_number="INV-A", quantity="70")
    later = invoice_line(
        invoice_number="INV-B",
        invoice_date=date(2026, 1, 4),
        quantity="50",
    )

    results, _ = reconcile(
        (po_line(),),
        (receipt_line(),),
        (duplicate, later, duplicate),
    )
    duplicates = [result for result in results if result.invoice_number == "INV-A"]
    later_result = next(result for result in results if result.invoice_number == "INV-B")

    assert len(duplicates) == 2
    assert all(result.issues == (IssueCode.DUPLICATE_INVOICE,) for result in duplicates)
    assert all(result.status is ReconciliationStatus.REVIEW_REQUIRED for result in duplicates)
    assert later_result.previously_invoiced_quantity == Decimal("70")
    assert later_result.supported_quantity == Decimal("30")


def test_conflicting_duplicate_quantities_consume_maximum_once() -> None:
    smaller = invoice_line(invoice_number="INV-A", quantity="70")
    larger = invoice_line(invoice_number="INV-A", quantity="90")
    later = invoice_line(
        invoice_number="INV-B",
        invoice_date=date(2026, 1, 4),
        quantity="20",
    )

    results, _ = reconcile(
        (po_line(),),
        (receipt_line(),),
        (smaller, later, larger),
    )
    duplicate_results = [result for result in results if result.invoice_number == "INV-A"]
    later_result = next(result for result in results if result.invoice_number == "INV-B")

    assert [result.supported_quantity for result in duplicate_results] == [
        Decimal("70"),
        Decimal("90"),
    ]
    assert all(IssueCode.DUPLICATE_INVOICE in result.issues for result in duplicate_results)
    assert later_result.previously_invoiced_quantity == Decimal("90")
    assert later_result.supported_quantity == Decimal("10")


def test_conflicting_duplicate_targets_consume_no_capacity() -> None:
    purchase_orders = (
        po_line(),
        po_line(line_number=2, item_code="ITEM-B"),
        po_line(po_number="PO-200", item_code="ITEM-C"),
    )
    receipts = (
        receipt_line(),
        receipt_line(
            receipt_id="REC-101",
            po_line_number=2,
            item_code="ITEM-B",
        ),
        receipt_line(
            receipt_id="REC-200",
            po_number="PO-200",
            item_code="ITEM-C",
        ),
    )
    duplicates = (
        invoice_line(invoice_number="INV-DUP", quantity="20"),
        invoice_line(
            invoice_number="INV-DUP",
            po_line_number=2,
            item_code="ITEM-B",
            quantity="30",
        ),
        invoice_line(
            invoice_number="INV-DUP",
            po_number="PO-200",
            item_code="ITEM-C",
            quantity="40",
        ),
    )
    later = invoice_line(
        invoice_number="INV-LATER",
        invoice_date=date(2026, 1, 4),
        quantity="100",
    )

    results, _ = reconcile(purchase_orders, receipts, (*duplicates, later))
    duplicate_results = [result for result in results if result.invoice_number == "INV-DUP"]
    later_result = next(result for result in results if result.invoice_number == "INV-LATER")

    assert all(result.issues[0] is IssueCode.DUPLICATE_INVOICE for result in duplicate_results)
    assert all(result.supported_quantity == Decimal("0") for result in duplicate_results)
    assert later_result.previously_invoiced_quantity == Decimal("0")
    assert later_result.status is ReconciliationStatus.MATCHED


def test_duplicate_price_conflicts_remain_visible_without_double_consumption() -> None:
    duplicates = (
        invoice_line(invoice_number="INV-DUP", quantity="10", price="10"),
        invoice_line(invoice_number="INV-DUP", quantity="10", price="12"),
    )

    results, summary = reconcile((po_line(),), (receipt_line(),), duplicates)

    assert results[0].issues == (IssueCode.DUPLICATE_INVOICE,)
    assert results[1].issues == (IssueCode.DUPLICATE_INVOICE, IssueCode.PRICE_MISMATCH)
    assert [result.potential_disputed_amount for result in results] == [
        Decimal("100.00"),
        Decimal("120.00"),
    ]
    assert summary.disputed_amounts[0].amount == Decimal("120.00")


def test_duplicate_results_are_invariant_to_row_order() -> None:
    rows = (
        invoice_line(invoice_number="INV-DUP", quantity="90", price="11"),
        invoice_line(invoice_number="INV-DUP", quantity="70", price="10"),
    )

    run_a = reconcile((po_line(),), (receipt_line(),), rows)
    run_b = reconcile((po_line(),), (receipt_line(),), tuple(reversed(rows)))

    assert run_a == run_b


def test_duplicate_financial_exposure_is_counted_once_in_summary() -> None:
    duplicate = invoice_line(invoice_number="INV-DUP", quantity="70")

    results, summary = reconcile(
        (po_line(),),
        (receipt_line(),),
        (duplicate, duplicate),
    )

    assert [result.potential_disputed_amount for result in results] == [
        Decimal("700.00"),
        Decimal("700.00"),
    ]
    assert summary.disputed_amounts[0].currency == "MAD"
    assert summary.disputed_amounts[0].amount == Decimal("700.00")


def test_duplicate_and_quantity_issues_have_stable_order() -> None:
    duplicate = invoice_line(invoice_number="INV-DUP", quantity="120")

    results, _ = reconcile(
        (po_line(),),
        (receipt_line(),),
        (duplicate, duplicate),
    )

    assert all(
        result.issues
        == (
            IssueCode.DUPLICATE_INVOICE,
            IssueCode.QUANTITY_EXCEEDS_PO,
            IssueCode.QUANTITY_EXCEEDS_RECEIPT,
        )
        for result in results
    )
