# Phase A Completion Report

Date: 2026-09-04

Project: Invoice / Purchase Order Reconciliation

Scope: Project foundation only

## Outcome

Phase A is complete. The repository now has an installable Python package, explicit domain and
result models, centralized CSV contracts, configurable financial policy defaults, purposeful
sample data, pytest coverage for the foundation, Ruff configuration, and project documentation.

No CSV loader, reconciliation engine, report renderer, or CLI was implemented. Those features
belong to later phases and were intentionally not pulled into this foundation commit.

## Files created

| Path | Purpose |
| --- | --- |
| `.editorconfig` | Consistent editor whitespace and newline settings |
| `.gitattributes` | Stable repository line endings across operating systems |
| `.gitignore` | Python, virtual-environment, test, lint, and build exclusions |
| `LICENSE` | MIT license |
| `pyproject.toml` | Package metadata, Python requirement, development dependencies, pytest, and Ruff settings |
| `README.md` | Problem statement, architecture, schemas, assumptions, sample scenarios, setup, and roadmap |
| `src/reconcile/__init__.py` | Public domain API |
| `src/reconcile/config.py` | Immutable reconciliation policy configuration |
| `src/reconcile/models.py` | Purchase order, receipt, invoice, result, summary, status, and issue models |
| `src/reconcile/schemas.py` | Canonical CSV column definitions, keys, types, and duplicate policies |
| `examples/sample_data/purchase_orders.csv` | Purposeful PO fixtures |
| `examples/sample_data/goods_receipts.csv` | Purposeful receipt fixtures, including split deliveries |
| `examples/sample_data/invoices.csv` | Purposeful invoice fixtures, including mismatches and a duplicate row |
| `tests/test_config.py` | Configuration default and boundary tests |
| `tests/test_models.py` | Decimal preservation, immutability, and stable-code tests |
| `tests/test_schemas.py` | Schema identity, duplicate-policy, and numeric-type tests |
| `tests/test_sample_data.py` | Header, row-width, multi-receipt, cumulative-invoice, and multi-line tests |
| `docs/phase-a-report.md` | This implementation record |

## Architecture chosen

The package uses a `src/` layout so tests exercise the installed package structure instead of
accidentally importing from the repository root. Domain models, policy configuration, and input
contracts are separated now; loading, reconciliation, reporting, and CLI modules will be added
only when their phases begin.

The runtime currently uses the Python standard library only:

- frozen, slotted dataclasses for explicit immutable records
- `Decimal` for quantities and money
- `date` for parsed business dates
- string enums for stable machine-readable issue and status codes

Pytest and Ruff are development-only dependencies. Pydantic, pandas, Polars, and Typer were not
added because Phase A does not need them, and the V0.1 problem can remain lightweight until a
later phase demonstrates a concrete benefit.

## Input schemas

All inputs are UTF-8 CSV files with an exact header row. Dates use `YYYY-MM-DD`; currency codes
are uppercase three-letter values; quantities are positive decimals; prices are non-negative
decimals; and document and item identifiers are non-empty text.

### Purchase orders

Columns, in order:

```text
po_number,line_number,supplier_id,order_date,currency,item_code,description,ordered_quantity,unit_price
```

Line identity: `(po_number, line_number)`. Repeated identities will be rejected as invalid.

### Goods receipts

Columns, in order:

```text
receipt_id,line_number,po_number,po_line_number,receipt_date,item_code,received_quantity
```

Line identity: `(receipt_id, line_number)`. Repeated identities will be rejected as invalid.

### Supplier invoices

Columns, in order:

```text
invoice_number,line_number,supplier_id,invoice_date,po_number,po_line_number,currency,item_code,invoiced_quantity,unit_price
```

Line identity: `(supplier_id, invoice_number, line_number)`. Repeated identities are preserved
for the future engine to classify as `DUPLICATE_INVOICE`.

Line numbers were added to the initially suggested fields because row position and item code do
not uniquely identify a line in a multi-line document. Receipt and invoice rows also carry the
referenced PO line number plus item code, allowing Phase B to detect inconsistent references.

## Domain and result models

The foundation defines:

- `PurchaseOrderLine`
- `GoodsReceiptLine`
- `InvoiceLine`
- `ReconciliationResult`
- `ReconciliationSummary`
- `CurrencyAmount`
- `ReconciliationStatus`
- `IssueCode`
- `ReconciliationConfig`

The issue enum contains every V0.1 rule code from the brief. The line result reserves cumulative
quantity facts and one disputed amount, while the summary stores currency amounts separately.

## V0.1 assumptions recorded

- Quantities may be fractional but must be greater than zero; unit prices may be zero.
- The price tolerance defaults to 2%, is configurable, and will use an inclusive relative
  comparison against the PO price.
- When the PO price is zero, only a zero invoice price falls within tolerance.
- PO lines sharing a PO number must agree on supplier and currency.
- Lines sharing supplier and invoice number form one logical invoice and must agree on date and
  currency; an invoice may reference several PO lines.
- Receipt totals aggregate by PO number and PO line only after the item reference is validated.
- Invoice allocation order is invoice date, supplier ID, invoice number, then invoice line
  number; source row order has no effect.
- A resolvable invoice line consumes capacity even if supplier, currency, or price needs review.
  Unknown PO or item references do not consume capacity.
- Exact duplicate invoice-line rows consume capacity once while all copies require review.
- All supplied receipts participate in the current snapshot, even if a receipt date follows an
  invoice date.
- A missing receipt is missing evidence, not proof of a zero delivery.
- Money uses `ROUND_HALF_UP`, and totals remain separated by currency.

## Purposeful sample coverage

The sample files contain exact matching, partial receipt, price mismatch, three receipts against
one PO line, cumulative over-invoicing, missing receipt, supplier mismatch, a multi-line document,
currency mismatch, invoicing beyond the PO despite excessive receipt data, unknown item, unknown
PO, a repeated invoice-line identity, and a price inside tolerance.

Corrupted values such as negative quantities and malformed money are not mixed into the main
demonstration files because they would make the future example CLI fail as a whole. Phase B will
use isolated test fixtures for those validation failures.

## Verification performed

The project was installed as an editable package with its development extras inside a fresh
local `.venv` using Python 3.12.7.

| Check | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed; editable package and declared tools installed |
| `python -m pytest` | Passed; 18 tests |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; all applicable files formatted |
| `python -m pip check` | Passed; no broken requirements |
| `git diff --check` | Passed; no whitespace errors |

An early fixture-width assertion caught blank CSV records. The fixtures were corrected and the
assertion remains as regression protection.

## Unresolved ambiguity

Two limits need an explicit Phase C policy before reporting is implemented:

1. Line-level CSV data has no source-system occurrence ID. V0.1 can detect repeated invoice-line
   identities, but it cannot prove a whole document was re-imported if its second copy has
   changed line data. A source document ID would be required for that stronger guarantee.
2. The brief does not specify how to calculate one disputed amount when the same line has several
   findings, such as excess quantity and excess price. Phase C must define a non-double-counting
   formula before summary totals are implemented.

Neither ambiguity blocks Phase B input validation.

## Recommended next step

Implement Phase B only: create strict CSV loaders that consume the centralized schema contracts,
produce the domain dataclasses, validate document-level consistency and numeric/date formats,
and raise actionable errors containing the source filename, row number, column, rejected value,
and reason. Cover empty files, missing or extra columns, blank identifiers, duplicate PO/receipt
keys, preserved invoice duplicate keys, zero/negative quantities, malformed decimals and dates,
invalid currency codes, and inconsistent fields within the same document.
