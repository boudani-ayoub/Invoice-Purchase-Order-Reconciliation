"""Strict CSV loaders for structurally valid reconciliation source records."""

import csv
import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Never, TypeVar

from reconcile.errors import CsvValidationError, CsvValidationIssue
from reconcile.models import GoodsReceiptLine, InvoiceLine, PurchaseOrderLine
from reconcile.schemas import (
    GOODS_RECEIPT_SCHEMA,
    INVOICE_SCHEMA,
    PURCHASE_ORDER_SCHEMA,
    ColumnDefinition,
    ColumnType,
    CsvSchema,
    DuplicatePolicy,
)

SourcePath = str | Path
RecordT = TypeVar("RecordT")


def load_purchase_orders(source: SourcePath) -> tuple[PurchaseOrderLine, ...]:
    return _load_records(source, PURCHASE_ORDER_SCHEMA, PurchaseOrderLine)


def load_goods_receipts(source: SourcePath) -> tuple[GoodsReceiptLine, ...]:
    return _load_records(source, GOODS_RECEIPT_SCHEMA, GoodsReceiptLine)


def load_invoices(source: SourcePath) -> tuple[InvoiceLine, ...]:
    return _load_records(source, INVOICE_SCHEMA, InvoiceLine)


def _load_records(
    source: SourcePath,
    schema: CsvSchema,
    record_type: Callable[..., RecordT],
) -> tuple[RecordT, ...]:
    source_path = Path(source)
    rows = _read_rows(source_path, schema)
    issues: list[CsvValidationIssue] = []
    records_with_rows: list[tuple[int, RecordT]] = []

    for row_number, row in rows:
        if len(row) != len(schema.headers):
            issues.append(
                CsvValidationIssue(
                    source=source_path,
                    row_number=row_number,
                    column="<row>",
                    value=",".join(row),
                    reason=(f"expected {len(schema.headers)} fields but received {len(row)}"),
                )
            )
            continue

        parsed: dict[str, Any] = {}
        issue_count_before_row = len(issues)
        for definition, value in zip(schema.columns, row, strict=True):
            try:
                parsed[definition.name] = _parse_value(definition, value)
            except ValueError as error:
                issues.append(
                    CsvValidationIssue(
                        source=source_path,
                        row_number=row_number,
                        column=definition.name,
                        value=value,
                        reason=str(error),
                    )
                )

        if len(issues) == issue_count_before_row:
            records_with_rows.append((row_number, record_type(**parsed)))

    _validate_identities(source_path, schema, records_with_rows, issues)
    _validate_document_consistency(source_path, schema, records_with_rows, issues)

    if issues:
        raise CsvValidationError(issues)

    return tuple(record for _, record in records_with_rows)


def _read_rows(source: Path, schema: CsvSchema) -> list[tuple[int, list[str]]]:
    try:
        with source.open(encoding="utf-8", newline="") as source_file:
            reader = csv.reader(source_file, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                _raise_file_issue(source, 1, "<header>", "", "file is empty")
            except csv.Error as error:
                _raise_file_issue(source, reader.line_num, "<header>", "", f"invalid CSV: {error}")

            _validate_header(source, schema, header)

            rows: list[tuple[int, list[str]]] = []
            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    break
                except csv.Error as error:
                    _raise_file_issue(
                        source,
                        reader.line_num,
                        "<row>",
                        "",
                        f"invalid CSV: {error}",
                    )
                rows.append((reader.line_num, row))
    except UnicodeDecodeError as error:
        raise CsvValidationError(
            (
                CsvValidationIssue(
                    source=source,
                    row_number=None,
                    column="<file>",
                    value="",
                    reason="file is not valid UTF-8",
                ),
            )
        ) from error
    except OSError as error:
        raise CsvValidationError(
            (
                CsvValidationIssue(
                    source=source,
                    row_number=None,
                    column="<file>",
                    value=str(source),
                    reason=f"unable to read file: {error.strerror or error}",
                ),
            )
        ) from error

    if not rows:
        _raise_file_issue(source, 2, "<row>", "", "file contains a header but no data rows")
    return rows


def _validate_header(source: Path, schema: CsvSchema, header: list[str]) -> None:
    received = tuple(header)
    if received == schema.headers:
        return

    duplicates = sorted({name for name in received if received.count(name) > 1})
    missing = [name for name in schema.headers if name not in received]
    unexpected = [name for name in received if name not in schema.headers]

    if duplicates:
        reason = f"header contains duplicate columns: {', '.join(duplicates)}"
    elif missing or unexpected:
        parts = []
        if missing:
            parts.append(f"missing columns: {', '.join(missing)}")
        if unexpected:
            parts.append(f"unexpected columns: {', '.join(unexpected)}")
        reason = "; ".join(parts)
    else:
        reason = "column order does not match the V0.1 contract"

    expected_header = ",".join(schema.headers)
    received_header = ",".join(received)
    _raise_file_issue(
        source,
        1,
        "<header>",
        received_header,
        f"invalid header; expected: {expected_header}; {reason}",
    )


def _parse_value(definition: ColumnDefinition, value: str) -> object:
    if value != value.strip():
        raise ValueError(f"{definition.name} must not contain leading or trailing whitespace")

    match definition.data_type:
        case ColumnType.TEXT:
            return value
        case ColumnType.NON_EMPTY_TEXT:
            if not value:
                raise ValueError(f"{definition.name} must not be blank")
            return value
        case ColumnType.POSITIVE_INTEGER:
            if re.fullmatch(r"[0-9]+", value) is None or int(value) <= 0:
                raise ValueError(f"{definition.name} must be an integer greater than zero")
            return int(value)
        case ColumnType.POSITIVE_DECIMAL:
            return _parse_decimal(definition.name, value, positive=True)
        case ColumnType.NON_NEGATIVE_DECIMAL:
            return _parse_decimal(definition.name, value, positive=False)
        case ColumnType.ISO_DATE:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                raise ValueError(f"{definition.name} must be a valid date in YYYY-MM-DD format")
            try:
                return date.fromisoformat(value)
            except ValueError as error:
                raise ValueError(
                    f"{definition.name} must be a valid date in YYYY-MM-DD format"
                ) from error
        case ColumnType.CURRENCY_CODE:
            if re.fullmatch(r"[A-Z]{3}", value) is None:
                raise ValueError(
                    f"{definition.name} must be a three-letter uppercase currency code"
                )
            return value

    raise TypeError(f"unsupported schema column type: {definition.data_type}")


def _parse_decimal(name: str, value: str, *, positive: bool) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        requirement = "greater than zero" if positive else "zero or greater"
        raise ValueError(f"{name} must be a finite decimal {requirement}") from error

    if not parsed.is_finite():
        requirement = "greater than zero" if positive else "zero or greater"
        raise ValueError(f"{name} must be a finite decimal {requirement}")

    is_out_of_range = parsed <= 0 if positive else parsed < 0
    if is_out_of_range:
        requirement = "greater than zero" if positive else "zero or greater"
        raise ValueError(f"{name} must be a finite decimal {requirement}")
    return parsed


def _validate_identities(
    source: Path,
    schema: CsvSchema,
    records_with_rows: list[tuple[int, RecordT]],
    issues: list[CsvValidationIssue],
) -> None:
    if schema.duplicate_policy is DuplicatePolicy.REVIEW:
        return

    first_rows: dict[tuple[object, ...], int] = {}
    for row_number, record in records_with_rows:
        key = tuple(getattr(record, column) for column in schema.key_columns)
        first_row = first_rows.setdefault(key, row_number)
        if first_row != row_number:
            issues.append(
                CsvValidationIssue(
                    source=source,
                    row_number=row_number,
                    column=",".join(schema.key_columns),
                    value=",".join(str(part) for part in key),
                    reason=f"duplicate record identity; first seen at CSV row {first_row}",
                )
            )


def _validate_document_consistency(
    source: Path,
    schema: CsvSchema,
    records_with_rows: list[tuple[int, RecordT]],
    issues: list[CsvValidationIssue],
) -> None:
    if not schema.document_key_columns:
        return

    first_records: dict[tuple[object, ...], tuple[int, RecordT]] = {}
    for row_number, record in records_with_rows:
        document_key = tuple(getattr(record, column) for column in schema.document_key_columns)
        if document_key not in first_records:
            first_records[document_key] = (row_number, record)
            continue

        first_row, first_record = first_records[document_key]
        for column in schema.consistent_columns:
            value = getattr(record, column)
            expected = getattr(first_record, column)
            if value != expected:
                issues.append(
                    CsvValidationIssue(
                        source=source,
                        row_number=row_number,
                        column=column,
                        value=str(value),
                        reason=(
                            f"{column} must match the value {expected!s} from CSV row {first_row} "
                            "for the same document"
                        ),
                    )
                )


def _raise_file_issue(
    source: Path,
    row_number: int | None,
    column: str,
    value: str,
    reason: str,
) -> Never:
    raise CsvValidationError(
        (
            CsvValidationIssue(
                source=source,
                row_number=row_number,
                column=column,
                value=value,
                reason=reason,
            ),
        )
    )
