"""Shared invoice identity, allocation, exposure, and summary helpers."""

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Protocol

from reconcile.config import ReconciliationConfig
from reconcile.models import (
    CurrencyAmount,
    InvoiceLine,
    IssueCode,
    PurchaseOrderLine,
    ReconciliationStatus,
    ReconciliationSummary,
)

PoLineKey = tuple[str, int]
InvoiceIdentity = tuple[str, str, int]
InvoiceTarget = tuple[str, int, str]

ISSUE_ORDER = (
    IssueCode.UNKNOWN_PO,
    IssueCode.UNKNOWN_ITEM,
    IssueCode.DUPLICATE_INVOICE,
    IssueCode.SUPPLIER_MISMATCH,
    IssueCode.CURRENCY_MISMATCH,
    IssueCode.MISSING_RECEIPT,
    IssueCode.QUANTITY_EXCEEDS_PO,
    IssueCode.QUANTITY_EXCEEDS_RECEIPT,
    IssueCode.PRICE_MISMATCH,
    IssueCode.RECEIPT_ITEM_MISMATCH,
    IssueCode.OVER_RECEIVED,
)

FULL_EXPOSURE_ISSUES = frozenset(
    {
        IssueCode.UNKNOWN_PO,
        IssueCode.UNKNOWN_ITEM,
        IssueCode.DUPLICATE_INVOICE,
        IssueCode.SUPPLIER_MISMATCH,
        IssueCode.CURRENCY_MISMATCH,
    }
)


class InvoiceOutcome(Protocol):
    @property
    def status(self) -> ReconciliationStatus: ...

    @property
    def issues(self) -> tuple[IssueCode, ...]: ...


def _group_invoices(invoices: tuple[InvoiceLine, ...]) -> tuple[tuple[InvoiceLine, ...], ...]:
    groups: dict[InvoiceIdentity, list[InvoiceLine]] = {}
    for invoice in sorted(invoices, key=_invoice_sort_key):
        groups.setdefault(_invoice_identity(invoice), []).append(invoice)
    return tuple(tuple(group) for group in groups.values())


def _invoice_sort_key(invoice: InvoiceLine) -> tuple[object, ...]:
    return (
        invoice.invoice_date,
        invoice.supplier_id,
        invoice.invoice_number,
        invoice.line_number,
        invoice.po_number,
        invoice.po_line_number,
        invoice.item_code,
        invoice.invoiced_quantity,
        invoice.unit_price,
        invoice.currency,
    )


def _invoice_identity(invoice: InvoiceLine) -> InvoiceIdentity:
    return invoice.supplier_id, invoice.invoice_number, invoice.line_number


def _invoice_target(invoice: InvoiceLine) -> InvoiceTarget:
    return invoice.po_number, invoice.po_line_number, invoice.item_code


def _resolve_po_line(
    invoice: InvoiceLine,
    po_index: dict[PoLineKey, PurchaseOrderLine],
    po_numbers: set[str],
) -> tuple[PurchaseOrderLine | None, IssueCode | None]:
    if invoice.po_number not in po_numbers:
        return None, IssueCode.UNKNOWN_PO

    po = po_index.get((invoice.po_number, invoice.po_line_number))
    if po is None or invoice.item_code != po.item_code:
        return None, IssueCode.UNKNOWN_ITEM
    return po, None


def _price_is_within_tolerance(
    invoice_price: Decimal,
    po_price: Decimal,
    config: ReconciliationConfig,
) -> bool:
    return abs(invoice_price - po_price) <= po_price * config.price_tolerance_rate


def _disputed_amount(
    invoice: InvoiceLine,
    po: PurchaseOrderLine,
    supported_quantity: Decimal,
    issues: tuple[IssueCode, ...],
    config: ReconciliationConfig,
) -> Decimal:
    if not issues:
        return _round_money(Decimal(0), config)

    invoice_amount = invoice.invoiced_quantity * invoice.unit_price
    if FULL_EXPOSURE_ISSUES.intersection(issues):
        return _round_money(invoice_amount, config)

    accepted_unit_price = (
        po.unit_price if IssueCode.PRICE_MISMATCH in issues else invoice.unit_price
    )
    supported_amount = supported_quantity * accepted_unit_price
    return _round_money(max(invoice_amount - supported_amount, Decimal(0)), config)


def _consume_group_capacity(
    group: tuple[InvoiceLine, ...],
    po_index: dict[PoLineKey, PurchaseOrderLine],
    consumed_quantities: dict[PoLineKey, Decimal],
) -> None:
    invoice = group[0]
    key = (invoice.po_number, invoice.po_line_number)
    po = po_index.get(key)
    if po is None or invoice.item_code != po.item_code:
        return

    consumed_quantities[key] += max(row.invoiced_quantity for row in group)


def _order_issues(issues: set[IssueCode]) -> tuple[IssueCode, ...]:
    return tuple(issue for issue in ISSUE_ORDER if issue in issues)


def _round_money(amount: Decimal, config: ReconciliationConfig) -> Decimal:
    quantum = Decimal(1).scaleb(-config.money_decimal_places)
    return amount.quantize(quantum, rounding=config.money_rounding)


def _summarize(
    invoices: tuple[InvoiceLine, ...],
    results: tuple[InvoiceOutcome, ...],
    group_exposures: list[tuple[str, Decimal]],
    config: ReconciliationConfig,
) -> ReconciliationSummary:
    issue_counter = Counter(issue for result in results for issue in result.issues)
    disputed_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for currency, amount in group_exposures:
        disputed_by_currency[currency] += amount

    return ReconciliationSummary(
        invoices_processed=len(
            {(invoice.supplier_id, invoice.invoice_number) for invoice in invoices}
        ),
        invoice_lines_processed=len(invoices),
        matched_lines=sum(result.status is ReconciliationStatus.MATCHED for result in results),
        review_required_lines=sum(
            result.status is ReconciliationStatus.REVIEW_REQUIRED for result in results
        ),
        issue_counts=tuple(
            (issue, issue_counter[issue]) for issue in ISSUE_ORDER if issue_counter[issue]
        ),
        disputed_amounts=tuple(
            CurrencyAmount(currency=currency, amount=_round_money(amount, config))
            for currency, amount in sorted(disputed_by_currency.items())
            if amount
        ),
    )
