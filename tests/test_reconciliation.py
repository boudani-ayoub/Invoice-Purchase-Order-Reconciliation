from datetime import date
from decimal import ROUND_DOWN, Decimal

import pytest

from reconcile import (
    GoodsReceiptLine,
    InvoiceLine,
    IssueCode,
    PurchaseOrderLine,
    ReconciliationConfig,
    ReconciliationStatus,
    reconcile,
)


def po_line(
    *,
    po_number: str = "PO-100",
    line_number: int = 1,
    supplier_id: str = "SUP-ONE",
    currency: str = "MAD",
    item_code: str = "ITEM-A",
    quantity: str = "100",
    price: str = "10",
) -> PurchaseOrderLine:
    return PurchaseOrderLine(
        po_number=po_number,
        line_number=line_number,
        supplier_id=supplier_id,
        order_date=date(2026, 1, 1),
        currency=currency,
        item_code=item_code,
        description="Test item",
        ordered_quantity=Decimal(quantity),
        unit_price=Decimal(price),
    )


def receipt_line(
    *,
    receipt_id: str = "REC-100",
    po_number: str = "PO-100",
    po_line_number: int = 1,
    item_code: str = "ITEM-A",
    quantity: str = "100",
) -> GoodsReceiptLine:
    return GoodsReceiptLine(
        receipt_id=receipt_id,
        line_number=1,
        po_number=po_number,
        po_line_number=po_line_number,
        receipt_date=date(2026, 1, 2),
        item_code=item_code,
        received_quantity=Decimal(quantity),
    )


def invoice_line(
    *,
    invoice_number: str = "INV-100",
    line_number: int = 1,
    invoice_date: date = date(2026, 1, 3),
    supplier_id: str = "SUP-ONE",
    po_number: str = "PO-100",
    po_line_number: int = 1,
    currency: str = "MAD",
    item_code: str = "ITEM-A",
    quantity: str = "100",
    price: str = "10",
) -> InvoiceLine:
    return InvoiceLine(
        invoice_number=invoice_number,
        line_number=line_number,
        supplier_id=supplier_id,
        invoice_date=invoice_date,
        po_number=po_number,
        po_line_number=po_line_number,
        currency=currency,
        item_code=item_code,
        invoiced_quantity=Decimal(quantity),
        unit_price=Decimal(price),
    )


def reconcile_one(
    invoice: InvoiceLine,
    *,
    purchase_orders: tuple[PurchaseOrderLine, ...] | None = None,
    receipts: tuple[GoodsReceiptLine, ...] | None = None,
    config: ReconciliationConfig | None = None,
):
    results, summary = reconcile(
        (po_line(),) if purchase_orders is None else purchase_orders,
        (receipt_line(),) if receipts is None else receipts,
        (invoice,),
        config=config or ReconciliationConfig(),
    )
    return results[0], summary


def test_exact_po_line_match() -> None:
    result, _ = reconcile_one(invoice_line())

    assert result.status is ReconciliationStatus.MATCHED
    assert result.issues == ()
    assert result.ordered_quantity == Decimal("100")
    assert result.received_quantity == Decimal("100")
    assert result.supported_quantity == Decimal("100")


def test_unknown_po_is_not_allocated() -> None:
    result, _ = reconcile_one(invoice_line(po_number="PO-999"))

    assert result.issues == (IssueCode.UNKNOWN_PO,)
    assert result.ordered_quantity is None
    assert result.received_quantity is None
    assert result.supported_quantity is None
    assert result.potential_disputed_amount == Decimal("1000.00")


def test_unknown_po_line_is_unknown_item() -> None:
    result, _ = reconcile_one(invoice_line(po_line_number=99))

    assert result.issues == (IssueCode.UNKNOWN_ITEM,)
    assert result.supported_quantity is None


def test_mismatched_item_is_unknown_and_does_not_consume_capacity() -> None:
    invoices = (
        invoice_line(
            invoice_number="INV-BAD",
            invoice_date=date(2026, 1, 2),
            item_code="ITEM-OTHER",
        ),
        invoice_line(invoice_number="INV-GOOD", quantity="100"),
    )

    results, _ = reconcile((po_line(),), (receipt_line(),), invoices)
    by_number = {result.invoice_number: result for result in results}

    assert by_number["INV-BAD"].issues == (IssueCode.UNKNOWN_ITEM,)
    assert by_number["INV-BAD"].supported_quantity is None
    assert by_number["INV-GOOD"].status is ReconciliationStatus.MATCHED
    assert by_number["INV-GOOD"].previously_invoiced_quantity == Decimal("0")


def test_multiple_receipts_are_aggregated() -> None:
    receipts = (
        receipt_line(receipt_id="REC-A", quantity="40"),
        receipt_line(receipt_id="REC-B", quantity="35"),
        receipt_line(receipt_id="REC-C", quantity="25"),
    )

    result, _ = reconcile_one(invoice_line(), receipts=receipts)

    assert result.received_quantity == Decimal("100")
    assert result.status is ReconciliationStatus.MATCHED


def test_fractional_receipts_are_aggregated_exactly() -> None:
    receipts = (
        receipt_line(receipt_id="REC-A", quantity="0.10"),
        receipt_line(receipt_id="REC-B", quantity="0.15"),
    )
    purchase_orders = (po_line(quantity="0.25"),)

    result, _ = reconcile_one(
        invoice_line(quantity="0.25"),
        purchase_orders=purchase_orders,
        receipts=receipts,
    )

    assert result.received_quantity == Decimal("0.25")
    assert result.supported_quantity == Decimal("0.25")


def test_mismatched_receipt_item_does_not_inflate_capacity() -> None:
    receipts = (receipt_line(item_code="ITEM-OTHER"),)

    result, _ = reconcile_one(invoice_line(), receipts=receipts)

    assert result.received_quantity is None
    assert result.supported_quantity == Decimal("0")
    assert result.issues == (IssueCode.MISSING_RECEIPT,)


def test_missing_receipt_does_not_add_quantity_exceeds_receipt() -> None:
    result, _ = reconcile_one(invoice_line(), receipts=())

    assert result.issues == (IssueCode.MISSING_RECEIPT,)
    assert result.received_quantity is None
    assert result.supported_quantity == Decimal("0")


@pytest.mark.parametrize(
    ("price", "has_mismatch"),
    [("100", False), ("101", False), ("102", False), ("102.01", True)],
    ids=("exact", "inside", "boundary", "outside"),
)
def test_price_tolerance_is_decimal_and_inclusive(price: str, has_mismatch: bool) -> None:
    purchase_orders = (po_line(price="100"),)
    result, _ = reconcile_one(invoice_line(price=price), purchase_orders=purchase_orders)

    assert (IssueCode.PRICE_MISMATCH in result.issues) is has_mismatch


@pytest.mark.parametrize(
    ("invoice_price", "expected_issues"),
    [("0", ()), ("0.01", (IssueCode.PRICE_MISMATCH,))],
)
def test_zero_po_price_requires_zero_invoice_price(
    invoice_price: str,
    expected_issues: tuple[IssueCode, ...],
) -> None:
    purchase_orders = (po_line(price="0"),)
    invoice = invoice_line(price=invoice_price)

    result, _ = reconcile_one(invoice, purchase_orders=purchase_orders)

    assert result.issues == expected_issues


def test_price_tolerance_comes_from_configuration() -> None:
    config = ReconciliationConfig(price_tolerance_rate=Decimal("0.05"))
    result, _ = reconcile_one(
        invoice_line(price="104"),
        purchase_orders=(po_line(price="100"),),
        config=config,
    )

    assert result.status is ReconciliationStatus.MATCHED
    assert result.issues == ()


def test_allocation_is_invariant_to_invoice_source_order() -> None:
    early = invoice_line(
        invoice_number="INV-A",
        invoice_date=date(2026, 1, 3),
        quantity="70",
    )
    late = invoice_line(
        invoice_number="INV-B",
        invoice_date=date(2026, 1, 4),
        quantity="50",
    )

    run_a = reconcile((po_line(),), (receipt_line(),), (early, late))
    run_b = reconcile((po_line(),), (receipt_line(),), (late, early))

    assert run_a == run_b


def test_cumulative_allocation_prevents_reusing_full_capacity() -> None:
    invoices = (
        invoice_line(invoice_number="INV-A", quantity="70"),
        invoice_line(invoice_number="INV-B", quantity="50"),
    )

    results, _ = reconcile((po_line(),), (receipt_line(),), invoices)
    first, second = results

    assert first.supported_quantity == Decimal("70")
    assert second.previously_invoiced_quantity == Decimal("70")
    assert second.supported_quantity == Decimal("30")
    assert second.issues == (
        IssueCode.QUANTITY_EXCEEDS_PO,
        IssueCode.QUANTITY_EXCEEDS_RECEIPT,
    )


def test_receipt_capacity_is_cumulative() -> None:
    invoices = (
        invoice_line(invoice_number="INV-A", quantity="60"),
        invoice_line(invoice_number="INV-B", quantity="40"),
    )

    results, _ = reconcile(
        (po_line(),),
        (receipt_line(quantity="80"),),
        invoices,
    )

    assert results[1].supported_quantity == Decimal("20")
    assert results[1].issues == (IssueCode.QUANTITY_EXCEEDS_RECEIPT,)


def test_excess_receipt_cannot_legitimize_quantity_beyond_po() -> None:
    result, _ = reconcile_one(
        invoice_line(quantity="110"),
        receipts=(receipt_line(quantity="120"),),
    )

    assert result.supported_quantity == Decimal("100")
    assert result.issues == (IssueCode.QUANTITY_EXCEEDS_PO,)


@pytest.mark.parametrize(
    ("first", "expected_issue"),
    [
        (
            invoice_line(invoice_number="INV-A", supplier_id="SUP-OTHER", quantity="70"),
            IssueCode.SUPPLIER_MISMATCH,
        ),
        (
            invoice_line(invoice_number="INV-A", currency="USD", quantity="70"),
            IssueCode.CURRENCY_MISMATCH,
        ),
        (invoice_line(invoice_number="INV-A", price="12", quantity="70"), IssueCode.PRICE_MISMATCH),
    ],
    ids=("supplier", "currency", "price"),
)
def test_review_findings_still_consume_capacity(
    first: InvoiceLine, expected_issue: IssueCode
) -> None:
    later = invoice_line(
        invoice_number="INV-B",
        invoice_date=date(2026, 1, 4),
        quantity="50",
    )

    results, _ = reconcile((po_line(),), (receipt_line(),), (later, first))
    by_number = {result.invoice_number: result for result in results}

    assert expected_issue in by_number["INV-A"].issues
    assert by_number["INV-B"].previously_invoiced_quantity == Decimal("70")
    assert IssueCode.QUANTITY_EXCEEDS_PO in by_number["INV-B"].issues


def test_issue_order_is_stable_for_combined_findings() -> None:
    invoice = invoice_line(
        supplier_id="SUP-OTHER",
        currency="USD",
        quantity="120",
        price="12",
    )

    result, _ = reconcile_one(invoice, receipts=(receipt_line(quantity="80"),))

    assert result.issues == (
        IssueCode.SUPPLIER_MISMATCH,
        IssueCode.CURRENCY_MISMATCH,
        IssueCode.QUANTITY_EXCEEDS_PO,
        IssueCode.QUANTITY_EXCEEDS_RECEIPT,
        IssueCode.PRICE_MISMATCH,
    )


def test_missing_receipt_and_price_mismatch_are_both_reported() -> None:
    result, _ = reconcile_one(invoice_line(price="12"), receipts=())

    assert result.issues == (IssueCode.MISSING_RECEIPT, IssueCode.PRICE_MISMATCH)


@pytest.mark.parametrize(
    ("invoice", "purchase_orders", "receipts", "expected"),
    [
        (invoice_line(), (po_line(),), (receipt_line(),), "0.00"),
        (invoice_line(quantity="120"), (po_line(),), (receipt_line(),), "200.00"),
        (invoice_line(price="12"), (po_line(),), (receipt_line(),), "200.00"),
        (invoice_line(quantity="120", price="12"), (po_line(),), (receipt_line(),), "440.00"),
        (invoice_line(po_number="PO-999"), (po_line(),), (receipt_line(),), "1000.00"),
        (invoice_line(item_code="ITEM-X"), (po_line(),), (receipt_line(),), "1000.00"),
        (invoice_line(supplier_id="SUP-X"), (po_line(),), (receipt_line(),), "1000.00"),
        (invoice_line(currency="USD"), (po_line(),), (receipt_line(),), "1000.00"),
        (invoice_line(), (po_line(),), (), "1000.00"),
    ],
    ids=(
        "match",
        "quantity",
        "price",
        "quantity-and-price",
        "unknown-po",
        "unknown-item",
        "supplier",
        "currency",
        "missing-receipt",
    ),
)
def test_disputed_amount_policy(
    invoice: InvoiceLine,
    purchase_orders: tuple[PurchaseOrderLine, ...],
    receipts: tuple[GoodsReceiptLine, ...],
    expected: str,
) -> None:
    result, _ = reconcile_one(
        invoice,
        purchase_orders=purchase_orders,
        receipts=receipts,
    )

    assert result.potential_disputed_amount == Decimal(expected)


def test_tolerated_price_difference_is_matched_with_no_disputed_amount() -> None:
    result, _ = reconcile_one(
        invoice_line(quantity="2", price="101.50"),
        purchase_orders=(po_line(quantity="2", price="100"),),
        receipts=(receipt_line(quantity="2"),),
    )

    assert result.status is ReconciliationStatus.MATCHED
    assert result.potential_disputed_amount == Decimal("0.00")


def test_disputed_amount_uses_configured_rounding() -> None:
    config = ReconciliationConfig(money_decimal_places=2, money_rounding=ROUND_DOWN)
    result, _ = reconcile_one(
        invoice_line(po_number="PO-999", quantity="1", price="1.009"),
        config=config,
    )

    assert result.potential_disputed_amount == Decimal("1.00")
