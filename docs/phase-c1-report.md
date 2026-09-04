# Phase C.1 Correction Report

Date: 2026-09-04

Project: Invoice / Purchase Order Reconciliation

Scope: Result-contract and disputed-exposure corrections only

## Outcome

Phase C.1 is complete. `ReconciliationResult` now preserves the full invoice-line identity and
the limited source context required by Phase D reporting. The exposure calculation now treats a
price inside tolerance as accepted when another issue, such as excess quantity, requires review.

No terminal renderer, JSON or CSV export, CLI, database, API, web interface, OCR, or file-output
functionality was added.

## Repository starting point

Work started from the clean, pushed Phase C head on `main`:

```text
45b2690 docs: record phase C completion
```

The original `docs/phase-c-report.md` correctly described the push state at the time it was
written. Its commits were pushed afterward, so that historical report was left unchanged.

## Findings verified

### Incomplete result identity

Confirmed. Invoice lines and duplicate groups use:

```text
(supplier_id, invoice_number, line_number)
```

The former result model omitted `supplier_id`, so results from two suppliers sharing an invoice
number and line number could not be distinguished without rejoining the invoice input.

### Tolerated prices included in exposure

Confirmed. Review lines without a full-exposure issue valued supported quantity at the PO price
in every case. If an accepted invoice price differed from the PO price, an unrelated quantity
finding caused that tolerated difference to appear in the disputed amount. A lower tolerated
price could also offset exposure from unsupported quantity.

## Result-model decision

The result contract is:

```text
supplier_id
invoice_number
invoice_line_number
invoice_date
po_number
po_line_number
item_code
status
issues
ordered_quantity
received_quantity
previously_invoiced_quantity
current_invoiced_quantity
supported_quantity
invoice_unit_price
po_unit_price
potential_disputed_amount
currency
```

Four fields were added:

- `supplier_id` completes the established invoice-line identity.
- `invoice_date` provides report ordering and context without requiring the original invoice.
- `invoice_unit_price` explains the invoice value and disputed exposure.
- `po_unit_price` explains the comparison baseline and is optional because unresolved references
  have no trusted matching PO item.

For `UNKNOWN_PO` and `UNKNOWN_ITEM`, `po_unit_price` is `None`. The engine does not expose an
unrelated PO-line price as support or replace unknown data with a known zero value.

## Disputed-amount policy

Let:

```text
invoice amount = current invoiced quantity * invoice unit price
```

- No issues: disputed amount is zero.
- `UNKNOWN_PO`, `UNKNOWN_ITEM`, `DUPLICATE_INVOICE`, `SUPPLIER_MISMATCH`, or
  `CURRENCY_MISMATCH`: disputed amount is the full invoice amount.
- Resolved line with a price inside tolerance: supported quantity is valued at the accepted
  invoice price.
- Resolved line with `PRICE_MISMATCH`: supported quantity is valued at the PO price.
- `MISSING_RECEIPT`: supported quantity remains zero, so the full invoice amount is exposed when
  no other full-exposure issue applies.

The non-full-exposure formula remains:

```text
disputed amount = max(invoice amount - supported amount, 0)
```

Only the supported unit-price baseline changes according to whether the price is accepted.

## Regression examples

Against 100 ordered and received units at a PO price of `100.00`:

| Invoice | Price policy | Supported | Potential disputed amount |
| --- | --- | ---: | ---: |
| `120 * 101.50` | within 2% tolerance | 100 | `20 * 101.50 = 2030.00` |
| `120 * 99.00` | within 2% tolerance | 100 | `20 * 99.00 = 1980.00` |
| `120 * 120.00` | `PRICE_MISMATCH` | 100 | `14400 - 10000 = 4400.00` |

Receipt-limited and cumulative-allocation regressions also verify that tolerated prices use the
invoice price only for the quantity actually supported. Allocation behavior itself was not
changed.

## Verification

Verification used Python 3.12.7 from the project `.venv`:

| Command | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed |
| `python -m pytest -vv` | Passed: 135 passed, 0 failed |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed: 21 files already formatted |
| `python -m pip check` | Passed: no broken requirements |
| `git diff --check` | Passed |
| `git diff --cached --check` | Passed |

A manual public-API run loaded all three sample CSV files with `load_purchase_orders`,
`load_goods_receipts`, and `load_invoices`, then called `reconcile`. The first result exposed the
new supplier, date, invoice-price, and PO-price fields with their expected typed values.

## Sample-data regression

The corrected policy does not change the sample totals. `INV-013` is inside tolerance and fully
matched, so its disputed amount remains zero.

```text
results: 17
matched: 6
review required: 11
issues: UNKNOWN_PO=1, UNKNOWN_ITEM=1, DUPLICATE_INVOICE=2,
        SUPPLIER_MISMATCH=1, CURRENCY_MISMATCH=1, MISSING_RECEIPT=1,
        QUANTITY_EXCEEDS_PO=2, QUANTITY_EXCEEDS_RECEIPT=2, PRICE_MISMATCH=1
disputed: EUR=2450.00, MAD=10199.00, USD=75.00
```

Existing tests continue to cover exact and conflicting duplicates, conservative capacity use,
duplicate-safe summary exposure, unknown references, supplier and currency mismatches, missing
receipts, exact matches, and deterministic sample findings.

## Remaining decision before Phase D

The result contract is ready for reporting. One earlier presentation question remains: invalid
receipt references are excluded from capacity but do not have their own findings model. Phase D
should initially report invoice-line consequences only unless a separate source-quality contract
is deliberately designed later.

## Exact next step

Start Phase D with tests that define stable terminal, JSON, and CSV representations of the
existing results and authoritative summary. Preserve typed internal values until the reporting
boundary, serialize missing `po_unit_price` explicitly, and use summary disputed totals rather
than recomputing totals from result rows. Stop before CLI integration, which belongs to Phase E.
