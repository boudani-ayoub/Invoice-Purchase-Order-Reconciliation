"""Pure, deterministic three-way reconciliation for validated domain records."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from decimal import Decimal

from reconcile.config import ReconciliationConfig
from reconcile.models import (
    CurrencyAmount,
    GoodsReceiptLine,
    InvoiceLine,
    IssueCode,
    PurchaseOrderLine,
    ReconciliationResult,
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


def reconcile(
    purchase_orders: Iterable[PurchaseOrderLine],
    receipts: Iterable[GoodsReceiptLine],
    invoices: Iterable[InvoiceLine],
    *,
    config: ReconciliationConfig | None = None,
) -> tuple[tuple[ReconciliationResult, ...], ReconciliationSummary]:
    """Reconcile validated records without mutating inputs or accessing external state."""

    policy = config or ReconciliationConfig()
    purchase_order_lines = tuple(purchase_orders)
    receipt_lines = tuple(receipts)
    invoice_lines = tuple(invoices)

    po_index = {(po.po_number, po.line_number): po for po in purchase_order_lines}
    po_numbers = {po.po_number for po in purchase_order_lines}
    receipt_totals = _aggregate_receipts(po_index, receipt_lines)
    invoice_groups = _group_invoices(invoice_lines)

    consumed_quantities: dict[PoLineKey, Decimal] = defaultdict(Decimal)
    results: list[ReconciliationResult] = []
    group_exposures: list[tuple[str, Decimal]] = []

    for group in invoice_groups:
        is_duplicate = len(group) > 1
        targets = {_invoice_target(invoice) for invoice in group}
        has_ambiguous_target = is_duplicate and len(targets) > 1
        group_results = tuple(
            _reconcile_invoice_line(
                invoice,
                po_index=po_index,
                po_numbers=po_numbers,
                receipt_totals=receipt_totals,
                consumed_quantities=consumed_quantities,
                is_duplicate=is_duplicate,
                allocation_allowed=not has_ambiguous_target,
                config=policy,
            )
            for invoice in group
        )
        results.extend(group_results)

        if not has_ambiguous_target:
            _consume_group_capacity(group, po_index, consumed_quantities)

        group_exposures.append(
            (
                group[0].currency,
                max(result.potential_disputed_amount for result in group_results),
            )
        )

    result_tuple = tuple(results)
    summary = _summarize(invoice_lines, result_tuple, group_exposures, policy)
    return result_tuple, summary


def _aggregate_receipts(
    po_index: dict[PoLineKey, PurchaseOrderLine],
    receipts: tuple[GoodsReceiptLine, ...],
) -> dict[PoLineKey, Decimal]:
    totals: dict[PoLineKey, Decimal] = defaultdict(Decimal)
    for receipt in receipts:
        key = (receipt.po_number, receipt.po_line_number)
        po = po_index.get(key)
        if po is not None and receipt.item_code == po.item_code:
            totals[key] += receipt.received_quantity
    return dict(totals)


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


def _reconcile_invoice_line(
    invoice: InvoiceLine,
    *,
    po_index: dict[PoLineKey, PurchaseOrderLine],
    po_numbers: set[str],
    receipt_totals: dict[PoLineKey, Decimal],
    consumed_quantities: dict[PoLineKey, Decimal],
    is_duplicate: bool,
    allocation_allowed: bool,
    config: ReconciliationConfig,
) -> ReconciliationResult:
    issues: set[IssueCode] = set()
    if is_duplicate:
        issues.add(IssueCode.DUPLICATE_INVOICE)

    po, reference_issue = _resolve_po_line(invoice, po_index, po_numbers)
    if reference_issue is not None:
        issues.add(reference_issue)
        ordered_issues = _order_issues(issues)
        return ReconciliationResult(
            supplier_id=invoice.supplier_id,
            invoice_number=invoice.invoice_number,
            invoice_line_number=invoice.line_number,
            invoice_date=invoice.invoice_date,
            po_number=invoice.po_number,
            po_line_number=invoice.po_line_number,
            item_code=invoice.item_code,
            status=ReconciliationStatus.REVIEW_REQUIRED,
            issues=ordered_issues,
            ordered_quantity=None,
            received_quantity=None,
            previously_invoiced_quantity=Decimal(0),
            current_invoiced_quantity=invoice.invoiced_quantity,
            supported_quantity=None,
            invoice_unit_price=invoice.unit_price,
            po_unit_price=None,
            potential_disputed_amount=_round_money(
                invoice.invoiced_quantity * invoice.unit_price,
                config,
            ),
            currency=invoice.currency,
        )

    key = (po.po_number, po.line_number)
    previously_invoiced = consumed_quantities[key]
    received_quantity = receipt_totals.get(key)

    if invoice.supplier_id != po.supplier_id:
        issues.add(IssueCode.SUPPLIER_MISMATCH)
    if invoice.currency != po.currency:
        issues.add(IssueCode.CURRENCY_MISMATCH)
    if received_quantity is None:
        issues.add(IssueCode.MISSING_RECEIPT)
    if previously_invoiced + invoice.invoiced_quantity > po.ordered_quantity:
        issues.add(IssueCode.QUANTITY_EXCEEDS_PO)
    if (
        received_quantity is not None
        and previously_invoiced + invoice.invoiced_quantity > received_quantity
    ):
        issues.add(IssueCode.QUANTITY_EXCEEDS_RECEIPT)
    if not _price_is_within_tolerance(invoice.unit_price, po.unit_price, config):
        issues.add(IssueCode.PRICE_MISMATCH)

    supported_quantity = _supported_quantity(
        invoice.invoiced_quantity,
        po.ordered_quantity,
        received_quantity,
        previously_invoiced,
        allocation_allowed=allocation_allowed,
    )
    ordered_issues = _order_issues(issues)
    status = (
        ReconciliationStatus.REVIEW_REQUIRED if ordered_issues else ReconciliationStatus.MATCHED
    )
    disputed_amount = _disputed_amount(
        invoice,
        po,
        supported_quantity,
        ordered_issues,
        config,
    )

    return ReconciliationResult(
        supplier_id=invoice.supplier_id,
        invoice_number=invoice.invoice_number,
        invoice_line_number=invoice.line_number,
        invoice_date=invoice.invoice_date,
        po_number=invoice.po_number,
        po_line_number=invoice.po_line_number,
        item_code=invoice.item_code,
        status=status,
        issues=ordered_issues,
        ordered_quantity=po.ordered_quantity,
        received_quantity=received_quantity,
        previously_invoiced_quantity=previously_invoiced,
        current_invoiced_quantity=invoice.invoiced_quantity,
        supported_quantity=supported_quantity,
        invoice_unit_price=invoice.unit_price,
        po_unit_price=po.unit_price,
        potential_disputed_amount=disputed_amount,
        currency=invoice.currency,
    )


def _supported_quantity(
    invoiced_quantity: Decimal,
    ordered_quantity: Decimal,
    received_quantity: Decimal | None,
    previously_invoiced: Decimal,
    *,
    allocation_allowed: bool,
) -> Decimal:
    if not allocation_allowed or received_quantity is None:
        return Decimal(0)

    remaining_po = max(ordered_quantity - previously_invoiced, Decimal(0))
    remaining_receipts = max(received_quantity - previously_invoiced, Decimal(0))
    return min(invoiced_quantity, remaining_po, remaining_receipts)


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
    results: tuple[ReconciliationResult, ...],
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
