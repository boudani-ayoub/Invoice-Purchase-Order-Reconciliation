"""Receipt coverage without assumptions about unavailable purchase-order terms."""

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from reconcile.analysis.models import InvoiceReceiptResult, InvoiceReceiptSummary
from reconcile.config import ReconciliationConfig
from reconcile.invoice_helpers import (
    InvoiceTarget,
    _group_invoices,
    _invoice_target,
    _order_issues,
    _round_money,
    _summarize,
)
from reconcile.models import GoodsReceiptLine, InvoiceLine, IssueCode, ReconciliationStatus


def analyze_invoice_receipt(
    receipts: Iterable[GoodsReceiptLine],
    invoices: Iterable[InvoiceLine],
    *,
    config: ReconciliationConfig | None = None,
) -> tuple[tuple[InvoiceReceiptResult, ...], InvoiceReceiptSummary]:
    policy = config or ReconciliationConfig()
    invoice_lines = tuple(invoices)
    totals: dict[InvoiceTarget, Decimal] = defaultdict(Decimal)
    references: set[tuple[str, int]] = set()
    for receipt in sorted(receipts, key=lambda row: (row.receipt_id, row.line_number)):
        totals[(receipt.po_number, receipt.po_line_number, receipt.item_code)] += (
            receipt.received_quantity
        )
        references.add((receipt.po_number, receipt.po_line_number))
    consumed: dict[InvoiceTarget, Decimal] = defaultdict(Decimal)
    results: list[InvoiceReceiptResult] = []
    exposures: list[tuple[str, Decimal]] = []
    for group in _group_invoices(invoice_lines):
        ambiguous = len({_invoice_target(row) for row in group}) > 1
        group_results = []
        for invoice in group:
            key = _invoice_target(invoice)
            previous, received = consumed[key], totals.get(key, Decimal(0))
            issues = {IssueCode.DUPLICATE_INVOICE} if len(group) > 1 else set()
            if key not in totals:
                issues.add(IssueCode.MISSING_RECEIPT)
                if key[:2] in references:
                    issues.add(IssueCode.RECEIPT_ITEM_MISMATCH)
            elif previous + invoice.invoiced_quantity > received:
                issues.add(IssueCode.QUANTITY_EXCEEDS_RECEIPT)
            supported = (
                Decimal(0)
                if ambiguous
                else min(invoice.invoiced_quantity, max(received - previous, Decimal(0)))
            )
            unsupported = (
                invoice.invoiced_quantity
                if len(group) > 1
                else invoice.invoiced_quantity - supported
            )
            group_results.append(
                InvoiceReceiptResult(
                    supplier_id=invoice.supplier_id,
                    invoice_number=invoice.invoice_number,
                    invoice_line_number=invoice.line_number,
                    invoice_date=invoice.invoice_date,
                    po_number=invoice.po_number,
                    po_line_number=invoice.po_line_number,
                    item_code=invoice.item_code,
                    status=ReconciliationStatus.REVIEW_REQUIRED
                    if issues
                    else ReconciliationStatus.MATCHED,
                    issues=_order_issues(issues),
                    previously_invoiced_quantity=previous,
                    current_invoiced_quantity=invoice.invoiced_quantity,
                    supported_quantity=supported,
                    invoice_unit_price=invoice.unit_price,
                    currency=invoice.currency,
                    received_quantity=received,
                    potential_unsupported_amount=_round_money(
                        unsupported * invoice.unit_price, policy
                    ),
                )
            )
        results.extend(group_results)
        if not ambiguous and _invoice_target(group[0]) in totals:
            consumed[_invoice_target(group[0])] += max(row.invoiced_quantity for row in group)
        exposures.append(
            (group[0].currency, max(row.potential_unsupported_amount for row in group_results))
        )
    summary = _summarize(invoice_lines, tuple(results), exposures, policy)
    return tuple(results), InvoiceReceiptSummary(
        invoices_processed=summary.invoices_processed,
        invoice_lines_processed=summary.invoice_lines_processed,
        matched_lines=summary.matched_lines,
        review_required_lines=summary.review_required_lines,
        issue_counts=summary.issue_counts,
        unsupported_amounts=summary.disputed_amounts,
    )
