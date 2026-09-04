from decimal import Decimal

from test_reconciliation import invoice_line, po_line, receipt_line

from reconcile import CurrencyAmount, IssueCode, reconcile


def test_summary_counts_logical_invoices_rows_statuses_and_issues() -> None:
    purchase_orders = (
        po_line(po_number="PO-MAD", currency="MAD"),
        po_line(po_number="PO-USD", currency="USD"),
    )
    receipts = (
        receipt_line(po_number="PO-MAD"),
        receipt_line(receipt_id="REC-USD", po_number="PO-USD"),
    )
    duplicate = invoice_line(
        invoice_number="INV-MAD",
        po_number="PO-MAD",
        quantity="120",
    )
    invoices = (
        duplicate,
        duplicate,
        invoice_line(
            invoice_number="INV-USD",
            po_number="PO-USD",
            currency="USD",
        ),
    )

    _, summary = reconcile(purchase_orders, receipts, invoices)

    assert summary.invoices_processed == 2
    assert summary.invoice_lines_processed == 3
    assert summary.matched_lines == 1
    assert summary.review_required_lines == 2
    assert summary.issue_counts == (
        (IssueCode.DUPLICATE_INVOICE, 2),
        (IssueCode.QUANTITY_EXCEEDS_PO, 2),
        (IssueCode.QUANTITY_EXCEEDS_RECEIPT, 2),
    )
    assert summary.disputed_amounts == (CurrencyAmount(currency="MAD", amount=Decimal("1200.00")),)


def test_disputed_totals_remain_separate_and_currency_sorted() -> None:
    invoices = (
        invoice_line(
            invoice_number="INV-USD",
            po_number="PO-UNKNOWN",
            currency="USD",
            price="5",
        ),
        invoice_line(
            invoice_number="INV-EUR",
            po_number="PO-UNKNOWN",
            currency="EUR",
            price="7",
        ),
    )

    _, summary = reconcile((po_line(),), (), invoices)

    assert summary.disputed_amounts == (
        CurrencyAmount(currency="EUR", amount=Decimal("700.00")),
        CurrencyAmount(currency="USD", amount=Decimal("500.00")),
    )


def test_fully_matched_run_has_no_disputed_currency_totals() -> None:
    _, summary = reconcile((po_line(),), (receipt_line(),), (invoice_line(),))

    assert summary.disputed_amounts == ()


def test_empty_invoice_collection_produces_empty_summary() -> None:
    results, summary = reconcile((po_line(),), (receipt_line(),), ())

    assert results == ()
    assert summary.invoices_processed == 0
    assert summary.invoice_lines_processed == 0
    assert summary.matched_lines == 0
    assert summary.review_required_lines == 0
    assert summary.issue_counts == ()
    assert summary.disputed_amounts == ()


def test_same_invoice_number_from_two_suppliers_counts_as_two_invoices() -> None:
    invoices = (
        invoice_line(invoice_number="INV-SHARED", supplier_id="SUP-A"),
        invoice_line(invoice_number="INV-SHARED", supplier_id="SUP-B"),
    )

    _, summary = reconcile((po_line(),), (receipt_line(),), invoices)

    assert summary.invoices_processed == 2
