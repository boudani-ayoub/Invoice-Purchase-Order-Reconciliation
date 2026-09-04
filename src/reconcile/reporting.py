"""Pure renderers for reconciliation results and authoritative summaries."""

import csv
import json
from collections.abc import Iterable
from decimal import Decimal
from io import StringIO

from reconcile.models import ReconciliationResult, ReconciliationStatus, ReconciliationSummary

_RESULT_FIELDS = (
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

_SUMMARY_METRICS = (
    "invoices_processed",
    "invoice_lines_processed",
    "matched_lines",
    "review_required_lines",
)

_SEPARATOR = "-" * 60
_TITLE_SEPARATOR = "=" * 60


def render_json_report(
    results: Iterable[ReconciliationResult],
    summary: ReconciliationSummary,
) -> str:
    """Render one deterministic JSON document containing summary and row results."""

    report = {
        "summary": _summary_to_mapping(summary),
        "results": [_result_to_mapping(result) for result in results],
    }
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def render_csv_results(results: Iterable[ReconciliationResult]) -> str:
    """Render detailed reconciliation results as one stable CSV table."""

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_RESULT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for result in results:
        row = _result_to_mapping(result)
        row["issues"] = "|".join(issue.value for issue in result.issues)
        writer.writerow({key: "" if value is None else value for key, value in row.items()})
    return output.getvalue()


def render_csv_summary(summary: ReconciliationSummary) -> str:
    """Render authoritative summary metrics, issues, and currency totals as CSV."""

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("category", "key", "value"))
    for metric in _SUMMARY_METRICS:
        writer.writerow(("metric", metric, getattr(summary, metric)))
    for issue, count in summary.issue_counts:
        writer.writerow(("issue", issue.value, count))
    for disputed in summary.disputed_amounts:
        writer.writerow(("disputed_amount", disputed.currency, _decimal_to_string(disputed.amount)))
    return output.getvalue()


def render_terminal_report(
    results: Iterable[ReconciliationResult],
    summary: ReconciliationSummary,
) -> str:
    """Render a concise plain-text report focused on lines requiring review."""

    review_results = tuple(
        result for result in results if result.status is ReconciliationStatus.REVIEW_REQUIRED
    )
    lines = [
        _TITLE_SEPARATOR,
        "INVOICE / PURCHASE ORDER RECONCILIATION",
        _TITLE_SEPARATOR,
        "",
        "SUMMARY",
        _SEPARATOR,
        f"Invoices processed: {summary.invoices_processed}",
        f"Invoice lines processed: {summary.invoice_lines_processed}",
        f"Matched: {summary.matched_lines}",
        f"Review required: {summary.review_required_lines}",
        "",
        "ISSUES",
        _SEPARATOR,
    ]
    if summary.issue_counts:
        lines.extend(f"{issue.value}: {count}" for issue, count in summary.issue_counts)
    else:
        lines.append("No issues recorded.")

    lines.extend(("", "POTENTIAL DISPUTED AMOUNTS", _SEPARATOR))
    if summary.disputed_amounts:
        lines.extend(
            f"{amount.currency}: {_decimal_to_string(amount.amount)}"
            for amount in summary.disputed_amounts
        )
    else:
        lines.append("No disputed amounts.")

    lines.extend(("", "REVIEW REQUIRED", _SEPARATOR))
    if not review_results:
        lines.append("No invoice lines require review.")
    else:
        for index, result in enumerate(review_results):
            if index:
                lines.append("")
            lines.extend(_terminal_result_lines(result))

    return "\n".join(lines) + "\n"


def _result_to_mapping(result: ReconciliationResult) -> dict[str, object]:
    return {
        "supplier_id": result.supplier_id,
        "invoice_number": result.invoice_number,
        "invoice_line_number": result.invoice_line_number,
        "invoice_date": result.invoice_date.isoformat(),
        "po_number": result.po_number,
        "po_line_number": result.po_line_number,
        "item_code": result.item_code,
        "status": result.status.value,
        "issues": [issue.value for issue in result.issues],
        "ordered_quantity": _optional_decimal_to_string(result.ordered_quantity),
        "received_quantity": _optional_decimal_to_string(result.received_quantity),
        "previously_invoiced_quantity": _decimal_to_string(result.previously_invoiced_quantity),
        "current_invoiced_quantity": _decimal_to_string(result.current_invoiced_quantity),
        "supported_quantity": _optional_decimal_to_string(result.supported_quantity),
        "invoice_unit_price": _decimal_to_string(result.invoice_unit_price),
        "po_unit_price": _optional_decimal_to_string(result.po_unit_price),
        "potential_disputed_amount": _decimal_to_string(result.potential_disputed_amount),
        "currency": result.currency,
    }


def _summary_to_mapping(summary: ReconciliationSummary) -> dict[str, object]:
    return {
        "invoices_processed": summary.invoices_processed,
        "invoice_lines_processed": summary.invoice_lines_processed,
        "matched_lines": summary.matched_lines,
        "review_required_lines": summary.review_required_lines,
        "issue_counts": {issue.value: count for issue, count in summary.issue_counts},
        "disputed_amounts": {
            amount.currency: _decimal_to_string(amount.amount)
            for amount in summary.disputed_amounts
        },
    }


def _terminal_result_lines(result: ReconciliationResult) -> tuple[str, ...]:
    return (
        (
            f"{result.supplier_id} | {result.invoice_number} | "
            f"line {result.invoice_line_number} | {result.invoice_date.isoformat()}"
        ),
        f"PO: {result.po_number}/{result.po_line_number} | Item: {result.item_code}",
        f"Issues: {'|'.join(issue.value for issue in result.issues)}",
        (
            f"Invoice quantity: {_decimal_to_string(result.current_invoiced_quantity)} | "
            f"Supported quantity: {_terminal_optional_decimal(result.supported_quantity)}"
        ),
        (
            f"Invoice unit price: {_decimal_to_string(result.invoice_unit_price)} | "
            f"PO unit price: {_terminal_optional_decimal(result.po_unit_price)}"
        ),
        (f"Disputed: {_decimal_to_string(result.potential_disputed_amount)} {result.currency}"),
    )


def _decimal_to_string(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal_to_string(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_to_string(value)


def _terminal_optional_decimal(value: Decimal | None) -> str:
    return "-" if value is None else _decimal_to_string(value)
