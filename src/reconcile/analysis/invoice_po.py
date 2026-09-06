"""Invoice matching against ordered capacity and commercial terms."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import fields
from decimal import Decimal

from reconcile.analysis.models import InvoicePoResult, InvoicePoSummary
from reconcile.config import ReconciliationConfig
from reconcile.invoice_helpers import (
    PoLineKey,
    _consume_group_capacity,
    _disputed_amount,
    _group_invoices,
    _invoice_target,
    _order_issues,
    _price_is_within_tolerance,
    _resolve_po_line,
    _round_money,
    _summarize,
)
from reconcile.models import InvoiceLine, IssueCode, PurchaseOrderLine, ReconciliationStatus


def analyze_invoice_po(
    purchase_orders: Iterable[PurchaseOrderLine],
    invoices: Iterable[InvoiceLine],
    *,
    config: ReconciliationConfig | None = None,
) -> tuple[tuple[InvoicePoResult, ...], InvoicePoSummary]:
    policy = config or ReconciliationConfig()
    orders, invoice_lines = tuple(purchase_orders), tuple(invoices)
    po_index = {(po.po_number, po.line_number): po for po in orders}
    po_numbers = {po.po_number for po in orders}
    consumed: dict[PoLineKey, Decimal] = defaultdict(Decimal)
    results: list[InvoicePoResult] = []
    exposures: list[tuple[str, Decimal]] = []
    for group in _group_invoices(invoice_lines):
        ambiguous = len({_invoice_target(row) for row in group}) > 1
        group_results = []
        for invoice in group:
            issues = {IssueCode.DUPLICATE_INVOICE} if len(group) > 1 else set()
            po, reference_issue = _resolve_po_line(invoice, po_index, po_numbers)
            previous = Decimal(0)
            supported = None
            if reference_issue:
                issues.add(reference_issue)
            if po is not None:
                previous = consumed[(po.po_number, po.line_number)]
                supported = (
                    Decimal(0)
                    if ambiguous
                    else min(
                        invoice.invoiced_quantity, max(po.ordered_quantity - previous, Decimal(0))
                    )
                )
                if invoice.supplier_id != po.supplier_id:
                    issues.add(IssueCode.SUPPLIER_MISMATCH)
                if invoice.currency != po.currency:
                    issues.add(IssueCode.CURRENCY_MISMATCH)
                if previous + invoice.invoiced_quantity > po.ordered_quantity:
                    issues.add(IssueCode.QUANTITY_EXCEEDS_PO)
                if not _price_is_within_tolerance(invoice.unit_price, po.unit_price, policy):
                    issues.add(IssueCode.PRICE_MISMATCH)
            ordered_issues = _order_issues(issues)
            exposure = (
                _round_money(invoice.invoiced_quantity * invoice.unit_price, policy)
                if po is None
                else _disputed_amount(invoice, po, supported, ordered_issues, policy)
            )
            group_results.append(
                InvoicePoResult(
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
                    issues=ordered_issues,
                    previously_invoiced_quantity=previous,
                    current_invoiced_quantity=invoice.invoiced_quantity,
                    supported_quantity=supported,
                    invoice_unit_price=invoice.unit_price,
                    currency=invoice.currency,
                    ordered_quantity=po.ordered_quantity if po else None,
                    po_unit_price=po.unit_price if po else None,
                    potential_disputed_amount=exposure,
                )
            )
        results.extend(group_results)
        if not ambiguous:
            _consume_group_capacity(group, po_index, consumed)
        exposures.append(
            (group[0].currency, max(row.potential_disputed_amount for row in group_results))
        )
    summary = _summarize(invoice_lines, tuple(results), exposures, policy)
    return tuple(results), InvoicePoSummary(
        **{field.name: getattr(summary, field.name) for field in fields(summary)}
    )
