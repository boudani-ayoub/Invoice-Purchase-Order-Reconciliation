# Phase D Completion Report

Date: 2026-09-04

Project: Invoice / Purchase Order Reconciliation

Scope: Stable terminal, JSON, and CSV reporting only

## Outcome

Phase D is complete. The package now renders existing `ReconciliationResult` rows and their
`ReconciliationSummary` as deterministic terminal text, one JSON document, a detailed results
CSV, and a separate summary CSV. Renderers return strings and have no filesystem side effects.

No command-line parser, database, API, web interface, authentication, OCR, integration, or new
business rule was added.

## Repository starting point

Work started from the clean, pushed Phase C.1 head on `main`:

```text
5cf4958 docs: record phase C.1 corrections
```

The accepted reconciliation engine and its duplicate, allocation, and exposure policies were not
modified.

## Architecture

Reporting is contained in `src/reconcile/reporting.py`. It accepts only existing domain outputs:

```text
ReconciliationResult rows + ReconciliationSummary -> rendered string
```

The module does not load input files, reconcile records, calculate support, classify issues,
deduplicate exposure, or write output files.

## Public API

```python
render_terminal_report(results, summary) -> str
render_json_report(results, summary) -> str
render_csv_results(results) -> str
render_csv_summary(summary) -> str
```

These functions are exported from `reconcile`. Internal mapping and Decimal helpers remain
private.

## Schema decisions

### Shared primitive rules

- Dates serialize with `date.isoformat()` as `YYYY-MM-DD`.
- `Decimal` values use fixed-point string formatting and never pass through a float.
- Quantity and price scale is not forced to money precision.
- Enum values use stable public codes such as `MATCHED` and `PRICE_MISMATCH`.
- Incoming result order is preserved.
- Rendered documents use deterministic `\n` line endings and end with a newline.

### JSON

The top-level field order is `summary`, then `results`. Summary fields and result fields are built
explicitly in their documented order. Decimal values are strings, missing values are `null`, and
issues are arrays of strings. JSON uses an indent of two and `ensure_ascii=False`.

Summary issue counts and disputed totals are JSON objects constructed in the order already
provided by `ReconciliationSummary`.

### Detailed CSV

The detailed CSV contains one row per reconciliation result with this header:

```text
supplier_id,invoice_number,invoice_line_number,invoice_date,po_number,po_line_number,item_code,status,issues,ordered_quantity,received_quantity,previously_invoiced_quantity,current_invoiced_quantity,supported_quantity,invoice_unit_price,po_unit_price,potential_disputed_amount,currency
```

Missing optional values use empty cells. Multiple issues use `|` in their existing order. Python's
`csv.DictWriter` handles identifiers containing commas, quotes, or newlines.

### Summary CSV

The summary is a separate tidy CSV with one schema:

```text
category,key,value
```

Four metric rows come first, followed by issue rows in summary order and disputed-amount rows in
summary currency order. Empty summaries still contain the four metric rows.

### Terminal

The plain-text report contains summary counts, issue counts, disputed totals, and detailed entries
for review-required lines. Matched rows contribute to the matched count but are not printed
individually. Unknown quantities and PO prices display as `-`, never Python `None`.

## Duplicate financial rule

Detailed row values are explanatory. `ReconciliationSummary.disputed_amounts` is authoritative.
No renderer derives official totals by summing `result.potential_disputed_amount`.

The explicit regression fixture produces:

```text
duplicate row A disputed: 700.00 MAD
duplicate row B disputed: 700.00 MAD
official summary disputed: 700.00 MAD
```

JSON contains both detailed rows and the one summary total. Detailed CSV contains both rows,
summary CSV contains `disputed_amount,MAD,700.00`, and the terminal summary shows `MAD: 700.00`.
None reports `1400.00` as the official total.

## Empty-run behavior

- JSON contains zero summary metrics, empty summary objects, and an empty results array.
- Detailed CSV contains its header.
- Summary CSV contains its header and four zero metric rows.
- Terminal output displays zero counts and `No invoice lines require review.`

## Verification

Verification used Python 3.12.7 from the project `.venv`:

| Command | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed |
| `python -m pytest -vv` | Passed: 153 passed, 0 failed |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed: 25 files already formatted |
| `python -m pip check` | Passed: no broken requirements |
| `git diff --check` | Passed |
| `git diff --cached --check` | Passed |

Manual verification loaded all three sample CSVs, reconciled them, rendered all four strings, and
parsed the JSON and both CSV outputs with the Python standard library. It also confirmed Decimal
strings, unknown-reference null/blank PO prices, visible duplicate rows, and duplicate-safe
summary totals.

## Sample fixture

All formats preserve the accepted Phase C.1 summary:

```text
results: 17
matched: 6
review required: 11
issues: UNKNOWN_PO=1, UNKNOWN_ITEM=1, DUPLICATE_INVOICE=2,
        SUPPLIER_MISMATCH=1, CURRENCY_MISMATCH=1, MISSING_RECEIPT=1,
        QUANTITY_EXCEEDS_PO=2, QUANTITY_EXCEEDS_RECEIPT=2, PRICE_MISMATCH=1
disputed: EUR=2450.00, MAD=10199.00, USD=75.00
```

## Scope check

Phase D added presentation only. There is no CLI, filesystem output API, database, HTTP API, UI,
receipt-level findings model, or change to Phase C reconciliation behavior.

## Remaining decisions before Phase E

The rendering contracts are complete. Phase E still needs explicit CLI decisions for:

- input path option names and required arguments;
- selecting terminal, JSON, or the two CSV outputs;
- stdout versus output-file behavior and overwrite policy;
- validation/runtime exit codes and stderr messages.

These are orchestration concerns and do not require changing the reporting schemas.

## Exact next step

Start Phase E with tests for a `main(argv)` boundary that accepts the three input CSV paths,
selects an existing renderer, writes to stdout or explicit destinations, and maps validation or
usage failures to documented nonzero exit codes. Add a project script entry point only after that
behavior is fixed. Do not duplicate loader, reconciliation, or reporting logic in the CLI.
