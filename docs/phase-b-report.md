# Phase B Completion Report

Date: 2026-09-04

Project: Invoice / Purchase Order Reconciliation

Scope: Phase A corrections and Phase B validated CSV ingestion only

## Outcome

Phase B is complete. The repository now provides a strict, schema-driven ingestion layer that
turns the three V0.1 CSV sources into immutable domain records. It reports structural and scalar
problems as actionable, structured validation issues while preserving valid business
discrepancies for the future reconciliation engine.

This is not yet a functioning invoice reconciliation application. No cross-dataset matching,
receipt aggregation, invoice allocation, discrepancy classification, reporting, or CLI was
implemented.

## Repository history

Development started from the preserved Phase A commit:

```text
73ba4f5 chore: establish phase A project foundation
```

Phase A corrections and Phase B implementation were recorded in these local commits:

```text
1c6de57 fix: tighten phase A package and schema contracts
49fc6d6 feat: add strict CSV loading and validation
49c82f3 fix: require plain decimal CSV values
```

The branch is `main`. These Phase B commits were not pushed because the continuation brief
explicitly says not to push without a separate request.

## Phase A corrections

### Installed-package test isolation

Removed `pythonpath = ["src"]` from pytest configuration. Tests now depend on the documented
editable installation instead of receiving a direct source-path shortcut.

Added `tests/test_packaging.py`, which reads the project version from `pyproject.toml` and checks
that the installed `invoice-purchase-order-reconciliation` distribution exposes the same version
through `importlib.metadata`.

This was verified by reinstalling with `python -m pip install -e ".[dev]"` and running the suite
through the virtual environment. The corrected foundation passed 20 tests before Phase B work
started.

### Explicit blank-text policy

Added `ColumnType.NON_EMPTY_TEXT` and assigned it to required identifiers in all three schemas.
The PO `description` remains `ColumnType.TEXT` and may be an empty string.

The uniform V0.1 whitespace policy is rejection: no cell may contain leading or trailing
whitespace. Loaders do not silently strip or otherwise normalize source values.

### Validation/reconciliation boundary

The README now distinguishes the two concerns explicitly:

- Phase B determines whether one source file can become structurally valid domain records.
- Phase C will determine whether valid records agree across datasets.

Valid discrepancy data—including unknown PO references, mismatched items, supplier or currency
differences, excessive quantities, prices beyond tolerance, and missing receipt scenarios—passes
loading unchanged.

## Files created or modified

| Path | Change |
| --- | --- |
| `pyproject.toml` | Removed pytest source-path injection |
| `src/reconcile/schemas.py` | Added explicit text policy and schema-driven document consistency metadata |
| `src/reconcile/errors.py` | Added structured validation issue and aggregate exception models |
| `src/reconcile/loaders.py` | Added strict CSV reading, scalar conversion, and source-level validation |
| `src/reconcile/__init__.py` | Exposed loaders and validation errors as public API |
| `tests/test_packaging.py` | Added installed-distribution metadata smoke test |
| `tests/test_loaders.py` | Added comprehensive loader and phase-boundary coverage |
| `tests/test_schemas.py` | Added blank, duplicate, and consistency-contract tests |
| `README.md` | Documented Phase B API, behavior, boundaries, errors, limitations, and next step |
| `docs/phase-b-report.md` | Added this completion record |

The purposeful files under `examples/sample_data/` were not changed or corrupted for negative
tests. Malformed inputs are generated in isolated pytest temporary directories.

## Loader architecture

The public functions are:

```python
from reconcile import load_goods_receipts, load_invoices, load_purchase_orders
```

They return:

```text
load_purchase_orders(...) -> tuple[PurchaseOrderLine, ...]
load_goods_receipts(...)  -> tuple[GoodsReceiptLine, ...]
load_invoices(...)        -> tuple[InvoiceLine, ...]
```

The implementation uses the standard `csv` module in strict mode. A shared internal pipeline
reads the canonical schema, validates every recoverable row, constructs the requested dataclass,
and then applies source-level identity and same-document consistency rules. There are no runtime
third-party dependencies.

Records remain in source order. Phase C owns the already-documented deterministic allocation
order and must not rely on input row position.

## Structural validation

Each loader:

- opens the source as UTF-8 with CSV-safe newline handling
- reports missing files, invalid UTF-8, and malformed CSV through the domain error model
- rejects empty files and files containing only a header
- requires the exact canonical header names and order
- distinguishes missing, unexpected, duplicated, and reordered header columns
- rejects rows whose field count differs from the header
- collects all recoverable scalar errors in the file before raising
- constructs immutable domain dataclasses only from fully valid rows

CSV parser corruption is fail-fast because continuing after an unterminated or otherwise invalid
quoted record would make later row boundaries unreliable. Scalar validation remains aggregated.

## Scalar validation

- `TEXT` permits an empty string; `NON_EMPTY_TEXT` does not.
- Every cell rejects leading or trailing whitespace without normalization.
- Positive integers use ASCII digits only and must be greater than zero.
- Positive decimals must be finite and greater than zero.
- Non-negative decimals must be finite and zero or greater.
- Decimal strings use plain unsigned base-10 notation with an optional fractional part.
  Scientific notation, digit separators, leading plus signs, `.5`, and `1.` are rejected.
- Dates must use the exact `YYYY-MM-DD` shape and represent a real calendar date.
- Currencies must match the syntactic `[A-Z]{3}` contract; no ISO-4217 registry is embedded.

Successful conversion produces `int`, `Decimal`, and `datetime.date` values as appropriate.

## Duplicate and consistency behavior

| Source | Identity | Duplicate behavior |
| --- | --- | --- |
| Purchase order | `(po_number, line_number)` | Rejected; issue points to the first CSV row |
| Goods receipt | `(receipt_id, line_number)` | Rejected; issue points to the first CSV row |
| Invoice | `(supplier_id, invoice_number, line_number)` | Preserved unchanged for Phase C review |

Purchase-order lines sharing a `po_number` must agree on `supplier_id`, `order_date`, and
`currency`.

Invoice lines sharing `(supplier_id, invoice_number)` must agree on `invoice_date` and
`currency`. Grouping includes the supplier so two suppliers may legitimately reuse the same
invoice number.

No goods-receipt document consistency constraints were invented because the current schema does
not identify additional receipt-level fields that the brief requires to be uniform.

## Error model

`CsvValidationIssue` is an immutable structured record containing:

```text
source
row_number
column
value
reason
```

`CsvValidationError` carries a tuple of one or more issues and renders them in a readable form.
Raw `csv.Error`, `UnicodeDecodeError`, `OSError`, `decimal.InvalidOperation`, integer parsing
errors, and date parsing errors are translated at the loader boundary.

## Phase-boundary proof

Tests load the unchanged demonstration invoices and confirm records representing all of these
future findings survive ingestion:

- unknown PO
- item different from the referenced PO line
- supplier different from the PO supplier
- currency different from the PO currency
- invoice quantity beyond the PO
- missing receipt evidence

The invoice loader receives only an invoice path and has no PO or receipt input, making accidental
cross-file validation impossible through its public API.

## Verification performed

Final verification used Python 3.12.7 inside the project `.venv`.

| Command | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed; editable distribution installed |
| `python -m pytest -vv` | Passed; 76 passed, 0 failed |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed |
| `python -m pip check` | Passed; no broken requirements |
| `git diff --check` and `git diff --cached --check` | Passed |

The suite covers valid typed records, fractional quantities, zero prices, blank descriptions,
headers, row widths, file and CSV failures, whitespace, integers, decimals including non-finite
values, strict decimal spelling, dates, currencies, aggregated errors, duplicate policy,
document consistency, source order, packaging metadata, sample fixtures, and the Phase B/Phase C
boundary.

## Manual public-API verification

The three demonstration sources were loaded separately through the exported package functions:

```text
purchase_orders.csv: 14 records
goods_receipts.csv: 15 records
invoices.csv: 17 records
```

The invoice count includes the intentional duplicate row and the invoice referencing `PO-999`.

## Remaining ambiguity before Phase C

1. The CSV has no source-system invoice occurrence ID. Repeated line identities are detectable,
   but a copied whole invoice with changed line data cannot be proven to be the same occurrence.
2. Conflicting rows may share one invoice-line identity. Phase B correctly preserves them, but
   Phase C must decide whether neither, one canonical row, or a conservative quantity consumes
   PO and receipt capacity. Exact duplicate rows already have the documented consume-once intent.
3. A line may have several findings at once. Phase C needs one explicit disputed-amount formula
   that does not double count excess quantity and price differences in later summary totals.

These decisions should be captured as rule tests before the engine is implemented.

## Exact next step

Begin Phase C with tests for PO-line indexing and receipt aggregation, followed by deterministic
invoice ordering and cumulative capacity allocation. Resolve conflicting duplicate allocation
and the line-level disputed-amount formula first. Then implement each issue code as pure domain
logic accepting already validated tuples and `ReconciliationConfig`. Stop before report rendering
or CLI integration.
