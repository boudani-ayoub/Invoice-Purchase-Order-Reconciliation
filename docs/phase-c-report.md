# Phase C Completion Report

Date: 2026-09-04

Project: Invoice / Purchase Order Reconciliation

Scope: Deterministic three-way reconciliation and cumulative invoice allocation only

## Outcome

Phase C is complete. The project now reconciles validated purchase-order, goods-receipt, and
invoice domain records through a pure in-memory API. It produces deterministic row-level results
and a summary with per-currency, duplicate-safe potential disputed totals.

No terminal report renderer, JSON or CSV exporter, CLI, database, API, web interface, OCR, or
other later-phase functionality was added.

## Repository history

Phase C started from the accepted and pushed Phase B commit point:

```text
a24598f docs: record phase B completion
```

The engine and policy tests were added in this local commit:

```text
e5264d6 feat: add deterministic reconciliation engine
```

The branch is `main`. Phase C commits were not pushed because the brief says not to push without
a separate request.

## Policies resolved

### Duplicate identity and allocation

Invoice duplicate groups use:

```text
(supplier_id, invoice_number, line_number)
```

- Every input row in a group of two or more receives `DUPLICATE_INVOICE`.
- Exact copies consume their shared invoiced quantity once.
- Conflicting quantities consume the maximum quantity once when every row names the same
  `(po_number, po_line_number, item_code)` target.
- A group with conflicting PO number, PO line, or item targets consumes no capacity because no
  single allocation target is defensible.
- Price differences do not change the capacity target. Each price remains visible through its
  row result and may independently produce `PRICE_MISMATCH`.

Grouping occurs before cumulative allocation, so source order cannot select a canonical copy.

### Duplicate financial exposure

Each duplicate row exposes its own full invoice extended amount. This makes the financial reason
for review visible without designating an arbitrary copy as canonical.

The summary counts a duplicate identity group once, using the maximum rounded row exposure. It
does not sum every duplicate result. This is a conservative V0.1 policy and prevents accidental
double counting in official totals.

### Missing receipt evidence

When a valid PO/item reference has no valid matching receipt:

```text
received_quantity = None
supported_quantity = 0
issues = MISSING_RECEIPT
```

`QUANTITY_EXCEEDS_RECEIPT` is not also added merely because evidence is missing. `None` preserves
the distinction between absent evidence and a known received quantity of zero, while zero support
is used only for financial exposure.

### Invoice order

Canonical processing and output order is:

```text
invoice_date
supplier_id
invoice_number
line_number
po_number
po_line_number
item_code
invoiced_quantity
unit_price
currency
```

The fields after line number are deterministic content tie-breaks. Completely identical rows
produce identical results, so their relative order is not observable. Allocation and output are
invariant to source-row permutation.

### Issue order and status

Issue tuples use one named policy order:

```text
UNKNOWN_PO
UNKNOWN_ITEM
DUPLICATE_INVOICE
SUPPLIER_MISMATCH
CURRENCY_MISMATCH
MISSING_RECEIPT
QUANTITY_EXCEEDS_PO
QUANTITY_EXCEEDS_RECEIPT
PRICE_MISMATCH
```

No issues means `MATCHED`; one or more means `REVIEW_REQUIRED`.

### Disputed amount

Unknown references, duplicate identities, supplier mismatches, and currency mismatches use the
full invoice extended amount.

Other review lines use:

```text
invoice amount   = invoiced quantity * invoice unit price
supported amount = supported quantity * PO unit price
disputed amount  = max(invoice amount - supported amount, 0)
```

This avoids independently summing overlapping quantity and price findings. A fully matched line,
including a price difference inside tolerance, has zero disputed amount. If another finding makes
the line reviewable, the documented PO-price baseline applies to its supported quantity.

Amounts are quantized with `ReconciliationConfig.money_decimal_places` and
`ReconciliationConfig.money_rounding`. The defaults remain two places and `ROUND_HALF_UP`.

## Implementation

### Files added

| Path | Purpose |
| --- | --- |
| `src/reconcile/reconciliation.py` | Pure indexing, aggregation, allocation, classification, exposure, and summary logic |
| `tests/test_reconciliation.py` | PO resolution, receipts, tolerance, ordering, allocation, issue, and exposure tests |
| `tests/test_reconciliation_duplicates.py` | Exact, conflicting, ambiguous-target, ordering, and summary duplicate tests |
| `tests/test_reconciliation_summary.py` | Counts, logical invoice identity, currencies, and empty-run tests |
| `tests/test_sample_reconciliation.py` | Explicit expected findings and totals for every demonstration scenario |
| `docs/phase-c-report.md` | This completion record |

### Files modified

| Path | Change |
| --- | --- |
| `src/reconcile/__init__.py` | Exported the public `reconcile` function |
| `src/reconcile/config.py` | Rejected non-finite tolerances and invalid Decimal rounding modes |
| `tests/test_config.py` | Covered the strengthened financial configuration boundary |
| `README.md` | Corrected the Phase B wording and documented Phase C behavior and limitations |

The existing sample CSV files and Phase B loaders were not changed.

### Public API

```python
from reconcile import reconcile

results, summary = reconcile(
    purchase_orders,
    receipts,
    invoices,
    config=ReconciliationConfig(),
)
```

The arguments accept in-memory iterables of the Phase B domain dataclasses. The return value is:

```text
tuple[tuple[ReconciliationResult, ...], ReconciliationSummary]
```

No paths or scenario-specific identifiers are embedded in the engine. Price tolerance and money
rounding come from configuration; stable V0.1 rule order and exposure categories are centralized
as named policy constants.

### Core algorithm

1. Build a PO-line index by `(po_number, line_number)`.
2. Aggregate matching receipt evidence by `(po_number, po_line_number)` using `Decimal`.
3. Sort invoices by the canonical content key and group duplicate identities.
4. Resolve each row to a trusted PO/item target or classify `UNKNOWN_PO`/`UNKNOWN_ITEM`.
5. Calculate row findings and supported quantity from remaining ordered and receipt capacity.
6. Consume each unambiguous identity group's maximum quantity once.
7. Round row exposure according to configuration.
8. Build stable counts and per-currency totals, taking duplicate group exposure once.

The approximate complexity is:

```text
PO indexing          O(P)
receipt aggregation  O(R)
invoice ordering     O(I log I)
invoice processing   O(I)
```

## Sample-data results

| Scenario | Result | Issues | Disputed amount |
| --- | --- | --- | --- |
| `INV-001` / `PO-001` exact match | `MATCHED` | none | `0.00 MAD` |
| `INV-002` / `PO-002` partial receipt | `REVIEW_REQUIRED` | `QUANTITY_EXCEEDS_RECEIPT` | `84.00 MAD` |
| `INV-003` / `PO-003` price mismatch | `REVIEW_REQUIRED` | `PRICE_MISMATCH` | `75.00 USD` |
| `INV-004` / `PO-004` three receipts | `MATCHED` | none | `0.00 MAD` |
| `INV-005-A` / `PO-005` first invoice | `MATCHED` | none | `0.00 EUR` |
| `INV-005-B` / `PO-005` cumulative excess | `REVIEW_REQUIRED` | `QUANTITY_EXCEEDS_PO`, `QUANTITY_EXCEEDS_RECEIPT` | `1700.00 EUR` |
| `INV-006` / `PO-006` no receipt | `REVIEW_REQUIRED` | `MISSING_RECEIPT` | `2160.00 MAD` |
| `INV-007` / `PO-007` supplier mismatch | `REVIEW_REQUIRED` | `SUPPLIER_MISMATCH` | `2800.00 MAD` |
| `INV-008` line 1 / `PO-008` | `MATCHED` | none | `0.00 EUR` |
| `INV-008` line 2 / `PO-008` | `MATCHED` | none | `0.00 EUR` |
| `INV-009` / `PO-009` currency mismatch | `REVIEW_REQUIRED` | `CURRENCY_MISMATCH` | `750.00 EUR` |
| `INV-010` / `PO-010` beyond PO | `REVIEW_REQUIRED` | `QUANTITY_EXCEEDS_PO` | `275.00 MAD` |
| `INV-011` / `PO-011` wrong item | `REVIEW_REQUIRED` | `UNKNOWN_ITEM` | `800.00 MAD` |
| `INV-UNKNOWN` / `PO-999` | `REVIEW_REQUIRED` | `UNKNOWN_PO` | `800.00 MAD` |
| `INV-012` copy 1 / `PO-012` | `REVIEW_REQUIRED` | `DUPLICATE_INVOICE` | `3280.00 MAD` |
| `INV-012` copy 2 / `PO-012` | `REVIEW_REQUIRED` | `DUPLICATE_INVOICE` | `3280.00 MAD` |
| `INV-013` / `PO-013` inside tolerance | `MATCHED` | none | `0.00 USD` |

The summary includes the `INV-012` exposure once, not twice.

## Verification performed

Final verification used Python 3.12.7 in the project `.venv`.

| Command | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed; editable package installed |
| `python -m pytest -vv` | Passed; 128 passed, 0 failed |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed |
| `python -m pip check` | Passed; no broken requirements |
| `git diff --check` and `git diff --cached --check` | Passed |

The reconciliation tests were written before the engine. Their initial run failed at collection
because the public `reconcile` API did not exist, then passed after the implementation.

## Manual API verification

The installed package loaded all three sample files and reconciled them through the public API:

```text
results: 17
matched: 6
review_required: 11
issues: UNKNOWN_PO=1, UNKNOWN_ITEM=1, DUPLICATE_INVOICE=2,
        SUPPLIER_MISMATCH=1, CURRENCY_MISMATCH=1, MISSING_RECEIPT=1,
        QUANTITY_EXCEEDS_PO=2, QUANTITY_EXCEEDS_RECEIPT=2, PRICE_MISMATCH=1
disputed: EUR=2450.00, MAD=10199.00, USD=75.00
```

## Remaining decisions before Phase D

No Phase C rule is left unresolved. Two presentation decisions remain:

1. Receipt rows with unknown or mismatched PO/item references are deliberately excluded from
   capacity but have no receipt-level findings model. Decide whether Phase D should expose a
   separate source-evidence warning section or only show the resulting invoice findings.
2. `ReconciliationResult` intentionally follows the original compact schema and does not include
   supplier, invoice date, unit prices, or a flag indicating whether its duplicate exposure was
   included in the summary. Before export formats are fixed, decide whether to extend the result
   model or require renderers to receive the original invoice records alongside results.

The lack of a source-system invoice occurrence ID also remains a V0.1 data limitation: changed
copies of a whole invoice cannot always be proven to be the same imported document.

## Exact next step

Begin Phase D by defining report-schema tests before rendering code. Preserve the Phase C summary
as the authoritative source for financial totals, especially duplicate-safe per-currency amounts.
Then implement pure terminal, JSON, and CSV renderers around existing results and summary. Decide
the two presentation questions above before committing a stable machine-readable schema. Stop
before adding a CLI; command-line integration belongs to Phase E.
