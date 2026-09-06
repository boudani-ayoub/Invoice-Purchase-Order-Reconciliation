"""Receiving and fulfillment, including unresolved receipt evidence."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from decimal import Decimal

from reconcile.analysis.models import (
    FulfillmentStatus,
    OrphanReceipt,
    PoReceiptResult,
    PoReceiptSummary,
)
from reconcile.config import ReconciliationConfig
from reconcile.invoice_helpers import _round_money
from reconcile.models import CurrencyAmount, GoodsReceiptLine, IssueCode, PurchaseOrderLine


def analyze_po_receipt(
    purchase_orders: Iterable[PurchaseOrderLine],
    receipts: Iterable[GoodsReceiptLine],
    *,
    config: ReconciliationConfig | None = None,
) -> tuple[tuple[PoReceiptResult, ...], tuple[OrphanReceipt, ...], PoReceiptSummary]:
    policy = config or ReconciliationConfig()
    orders, receipt_lines = tuple(purchase_orders), tuple(receipts)
    po_index = {(po.po_number, po.line_number): po for po in orders}
    po_numbers = {po.po_number for po in orders}
    totals: dict[tuple[str, int], Decimal] = defaultdict(Decimal)
    orphans = []
    for receipt in sorted(receipt_lines, key=lambda row: (row.receipt_id, row.line_number)):
        key = (receipt.po_number, receipt.po_line_number)
        po = po_index.get(key)
        issue = None
        if receipt.po_number not in po_numbers:
            issue = IssueCode.UNKNOWN_PO
        elif po is None:
            issue = IssueCode.UNKNOWN_ITEM
        elif po.item_code != receipt.item_code:
            issue = IssueCode.RECEIPT_ITEM_MISMATCH
        if issue:
            orphans.append(
                OrphanReceipt(
                    receipt_id=receipt.receipt_id,
                    receipt_line_number=receipt.line_number,
                    receipt_date=receipt.receipt_date,
                    po_number=receipt.po_number,
                    po_line_number=receipt.po_line_number,
                    item_code=receipt.item_code,
                    received_quantity=receipt.received_quantity,
                    issue=issue,
                )
            )
        else:
            totals[key] += receipt.received_quantity
    results = []
    outstanding_values: dict[str, Decimal] = defaultdict(Decimal)
    excess_values: dict[str, Decimal] = defaultdict(Decimal)
    for key, po in sorted(po_index.items()):
        received = totals[key]
        outstanding = max(po.ordered_quantity - received, Decimal(0))
        excess = max(received - po.ordered_quantity, Decimal(0))
        if not received:
            status = FulfillmentStatus.NOT_RECEIVED
        elif excess:
            status = FulfillmentStatus.OVER_RECEIVED
        elif outstanding:
            status = FulfillmentStatus.PARTIALLY_RECEIVED
        else:
            status = FulfillmentStatus.FULLY_RECEIVED
        outstanding_value = _round_money(outstanding * po.unit_price, policy)
        excess_value = _round_money(excess * po.unit_price, policy)
        outstanding_values[po.currency] += outstanding_value
        excess_values[po.currency] += excess_value
        results.append(
            PoReceiptResult(
                po_number=po.po_number,
                po_line_number=po.line_number,
                item_code=po.item_code,
                supplier_id=po.supplier_id,
                status=status,
                ordered_quantity=po.ordered_quantity,
                received_quantity=received,
                outstanding_quantity=outstanding,
                over_received_quantity=excess,
                po_unit_price=po.unit_price,
                currency=po.currency,
                outstanding_ordered_value=outstanding_value,
                over_received_reference_value=excess_value,
            )
        )
    counts = Counter(row.status for row in results)
    return (
        tuple(results),
        tuple(orphans),
        PoReceiptSummary(
            purchase_orders_processed=len(po_numbers),
            po_lines_processed=len(orders),
            receipt_lines_processed=len(receipt_lines),
            status_counts=tuple((status, counts[status]) for status in FulfillmentStatus),
            orphan_receipt_lines=len(orphans),
            outstanding_values=tuple(
                CurrencyAmount(currency, amount)
                for currency, amount in sorted(outstanding_values.items())
                if amount
            ),
            over_received_values=tuple(
                CurrencyAmount(currency, amount)
                for currency, amount in sorted(excess_values.items())
                if amount
            ),
        ),
    )
