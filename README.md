# Invoice / Purchase Order Reconciliation

A local-first Python application for three-way matching between purchase orders,
goods receipts, and supplier invoices. The project models the controls an accounts-payable
team applies before approving an invoice for payment.

> **Current status:** Phase E is complete. The project provides validated CSV ingestion,
> deterministic reconciliation, terminal/JSON/CSV reporting, and an installable command-line
> workflow. Phase F is reserved for CI and portfolio documentation polish.

## Why this project exists

An invoice should only be paid when its supplier, currency, items, quantities, and prices
agree with both the purchase order and the available receipt evidence. Real procurement data
also contains partial deliveries, several receipts, several invoices, and duplicate records.
This project is designed to handle those cases deterministically without hiding accounting
decisions inside data-manipulation code.

## Architecture

```text
src/reconcile/
├── __main__.py     # python -m reconcile entry point
├── cli.py          # Argument parsing and workflow orchestration
├── config.py       # Business policy configuration
├── errors.py       # Structured source-validation issues
├── loaders.py      # Strict, schema-driven CSV ingestion
├── models.py       # Immutable domain and result objects
├── reconciliation.py # Pure reconciliation and cumulative allocation
├── reporting.py    # Deterministic terminal, JSON, and CSV rendering
└── schemas.py      # Canonical CSV contracts

examples/sample_data/  # Purpose-built demonstration data
tests/                 # Foundation and fixture-contract tests
```

The domain package does not depend on a CLI framework or report formatting. Loaders convert CSV
cells into domain records but do not compare datasets. This keeps the future reconciliation
engine independently testable. The project uses only the Python standard library at runtime:
dataclasses make the data contracts explicit, and `Decimal` prevents binary floating-point
arithmetic from entering financial calculations.

## Input contracts

All files are UTF-8 CSV documents with one header row. Column names and order are exact.
Identifiers are non-empty text, dates use `YYYY-MM-DD`, line numbers are positive integers,
quantities are positive decimal strings, prices are non-negative decimal strings, and
currencies are uppercase three-letter codes. Phase B enforces these constraints and reports
row-level errors.

Required identifiers have a distinct `NON_EMPTY_TEXT` schema type. `description` uses `TEXT` and
may be blank. Values containing leading or trailing whitespace will be rejected consistently
rather than silently normalized.

### `purchase_orders.csv`

| Column | Type | Meaning |
| --- | --- | --- |
| `po_number` | text | Supplier-facing PO identifier |
| `line_number` | positive integer | Line number within the PO |
| `supplier_id` | text | Internal supplier identifier |
| `order_date` | ISO date | Date the PO was issued |
| `currency` | currency code | PO line currency |
| `item_code` | text | Purchased item identifier |
| `description` | text | Human-readable item description |
| `ordered_quantity` | positive decimal | Quantity ordered |
| `unit_price` | non-negative decimal | Agreed unit price |

Line identity: `(po_number, line_number)`. Repeated identities are invalid source data.

### `goods_receipts.csv`

| Column | Type | Meaning |
| --- | --- | --- |
| `receipt_id` | text | Goods receipt document identifier |
| `line_number` | positive integer | Line number within the receipt |
| `po_number` | text | Referenced PO identifier |
| `po_line_number` | positive integer | Referenced PO line |
| `receipt_date` | ISO date | Date goods were recorded as received |
| `item_code` | text | Received item identifier |
| `received_quantity` | positive decimal | Quantity received |

Line identity: `(receipt_id, line_number)`. Repeated identities are invalid source data.

### `invoices.csv`

| Column | Type | Meaning |
| --- | --- | --- |
| `invoice_number` | text | Supplier-issued invoice identifier |
| `line_number` | positive integer | Line number within the invoice |
| `supplier_id` | text | Supplier identifier on the invoice |
| `invoice_date` | ISO date | Date the invoice was issued |
| `po_number` | text | Referenced PO identifier |
| `po_line_number` | positive integer | Referenced PO line |
| `currency` | currency code | Invoice line currency |
| `item_code` | text | Invoiced item identifier |
| `invoiced_quantity` | positive decimal | Quantity invoiced |
| `unit_price` | non-negative decimal | Invoiced unit price |

Line identity: `(supplier_id, invoice_number, line_number)`. Repeated identities are preserved
so the reconciliation engine can classify them as `DUPLICATE_INVOICE`.

Explicit line numbers avoid relying on row order and allow one document to contain the same
item more than once. Keeping both the line reference and item code also lets the reconciliation
engine detect an invoice or receipt that points to a PO line but names the wrong item.

## V0.1 reconciliation assumptions

- Quantities may be fractional and use `Decimal`; zero and negative source quantities are
  invalid rather than business events.
- Unit prices are non-negative financial decimals. The default tolerance is a relative 2%
  difference from the PO price, and the comparison boundary is inclusive.
- A PO line belongs to the PO supplier and currency shown on that row. All lines for a PO are
  expected to agree on those document-level values.
- Lines sharing a supplier and invoice number form one logical invoice and are expected to
  agree on invoice date and currency. One invoice may reference several PO lines.
- Receipt quantities will be aggregated by `(po_number, po_line_number)` after verifying the
  receipt item matches the referenced PO line.
- Invoice consumption will be deterministic: invoice date, supplier ID, invoice number, then
  invoice line number. CSV row order will not affect the result.
- Earlier invoice quantities with a valid PO-line reference consume ordered and received
  capacity before later invoice lines, even when price, supplier, or currency needs review.
  Unknown PO/item references do not consume capacity.
- Exact duplicate invoice-line rows are all review findings but consume capacity only once.
  Conflicting quantities sharing an identity consume the maximum once when their target agrees.
  A duplicate group with conflicting PO/item targets consumes no capacity.
- Reconciliation is a current snapshot: all supplied receipts count even when their receipt
  date is later than the invoice date. An as-of-date mode is outside V0.1.
- Missing receipt evidence means `MISSING_RECEIPT`; it is not represented as a confirmed zero
  delivery.
- Price tolerance is inclusive and relative to the PO price:
  `abs(invoice price - PO price) <= PO price * tolerance`. When the PO price is zero, only a
  zero invoice price matches.
- Disputed amounts are rounded using the configured precision and rounding mode, defaulting to
  two places and `ROUND_HALF_UP`, and totals remain separated by currency.
- In V0.1, supplier plus invoice number identifies one logical invoice. Repeated instances of
  the same invoice-line identity are preserved and marked for review. Detecting a repeated whole
  document with changed line data needs source-document identity that the current CSV does not
  provide; this remains an explicit limitation.

## Purposeful sample data

The files in [`examples/sample_data`](examples/sample_data) are deterministic fixtures, not
random generated rows.

| Record | Scenario represented |
| --- | --- |
| `PO-001` | Exact match |
| `PO-002` | Invoice quantity exceeds a partial receipt |
| `PO-003` | Unit price outside tolerance |
| `PO-004` | Three receipts aggregated against one PO line |
| `PO-005` | Two invoices cumulatively exceed ordered and received quantity |
| `PO-006` | Missing receipt evidence |
| `PO-007` | Supplier mismatch |
| `PO-008` | Multi-line PO, receipt, and invoice |
| `PO-009` | Currency mismatch |
| `PO-010` | Invoice exceeds the PO despite an excessive receipt quantity |
| `PO-011` | Invoice item differs from the referenced PO line |
| `PO-012` | Repeated invoice-line key for duplicate detection |
| `PO-013` | Price difference inside the default tolerance |
| `PO-999` | Invoice references an unknown PO |

The duplicate row in `invoices.csv` is intentional.

## Loading validated records

Install the package, then use the public loader functions:

```python
from reconcile import load_goods_receipts, load_invoices, load_purchase_orders

purchase_orders = load_purchase_orders("examples/sample_data/purchase_orders.csv")
receipts = load_goods_receipts("examples/sample_data/goods_receipts.csv")
invoices = load_invoices("examples/sample_data/invoices.csv")
```

Each function returns an immutable tuple of typed domain dataclasses. Dates become
`datetime.date`, line numbers become `int`, and quantities and prices become `Decimal`. Records
remain in source order; deterministic allocation order belongs to Phase C.

### Source validation behavior

- Headers must match the canonical columns and order exactly.
- Empty files, header-only files, invalid UTF-8, malformed CSV, and wrong-width rows fail clearly.
- Every cell rejects leading or trailing whitespace. Required identifiers reject empty values;
  PO descriptions may be empty.
- Positive integers, finite decimals, calendar dates, and currency syntax are validated before
  a dataclass is constructed. Decimal input uses plain unsigned base-10 notation with an optional
  fractional part; exponents, separators, leading plus signs, `.5`, and `1.` forms are rejected.
- Recoverable scalar errors are collected across the file and raised together as
  `CsvValidationError`. Each `CsvValidationIssue` contains its path, CSV row number, column,
  rejected value, and reason.
- Duplicate PO and goods-receipt line identities are invalid. Duplicate invoice-line identities
  are preserved for Phase C review and are never silently deduplicated.
- PO lines must agree on supplier, order date, and currency. Lines in the same logical invoice
  must agree on invoice date and currency. No extra goods-receipt document rules are assumed.

Example error shape:

```text
CSV validation failed with 1 issue:

purchase_orders.csv:17
column: ordered_quantity
value: '-3'
reason: ordered_quantity must be a finite decimal greater than zero
```

## Validation and reconciliation boundary

Source validation and business reconciliation answer different questions:

- **Phase B validation:** can one CSV be parsed into structurally valid domain records? It rejects
  malformed headers and scalar values, invalid source identities, and inconsistent fields within
  one PO or invoice document.
- **Phase C reconciliation:** do valid invoice, PO, and receipt records agree with one another? It
  will classify unknown references, mismatched items, suppliers or currencies, missing receipts,
  excessive quantities, and price differences.

For example, `PO-999` is a valid non-empty PO reference in an invoice and must pass invoice
loading even when no purchase order with that number exists. Loaders must not access another
dataset to decide whether a row is valid.

Phase B alone does not reconcile records; it guarantees that each dataset is structurally
trustworthy enough for the Phase C engine to compare.

## Reconciliation

The reconciliation API consumes the typed records returned by the loaders:

```python
from reconcile import reconcile

results, summary = reconcile(purchase_orders, receipts, invoices)
```

It performs no file access, mutates no inputs, uses no global state, and returns the same ordered
results for any permutation of the same validated records.

### Result contract

Each `ReconciliationResult` preserves the complete invoice-line identity:

```text
(supplier_id, invoice_number, invoice_line_number)
```

It also carries the invoice date, invoice unit price, and matched PO unit price needed for
reporting, alongside the PO/item reference, quantities, findings, status, currency, and potential
disputed amount. `po_unit_price` is `None` for `UNKNOWN_PO` and `UNKNOWN_ITEM` because those rows
have no trusted matched PO item; zero is reserved for a known zero price.

### PO resolution and receipt evidence

Purchase-order lines are indexed by `(po_number, line_number)`. A missing PO produces
`UNKNOWN_PO`; a missing PO line or item mismatch produces `UNKNOWN_ITEM`. Unresolved invoice
lines do not consume capacity.

Receipts aggregate by `(po_number, po_line_number)` only when their item matches the indexed PO
line. Unknown or mismatched receipt rows do not inflate usable receipt capacity and do not create
invoice findings by themselves. When no valid matching receipt remains, the invoice result uses
`received_quantity = None`, adds `MISSING_RECEIPT`, and does not also add
`QUANTITY_EXCEEDS_RECEIPT`.

### Deterministic cumulative allocation

Invoice rows are processed by:

```text
invoice_date, supplier_id, invoice_number, line_number, row content
```

The content tie-break covers PO reference, item, quantity, price, and currency. Completely
identical rows produce identical results, so their relative position has no observable effect.

For a resolved line, the engine tracks prior invoice consumption against both ordered and valid
received quantities:

```text
remaining PO       = max(ordered - previously invoiced, 0)
remaining receipt  = max(received - previously invoiced, 0)
supported quantity = min(current invoice, remaining PO, remaining receipt)
```

Supplier, currency, and price findings do not prevent an otherwise resolved line from consuming
capacity. This conservative rule prevents a later invoice from reusing quantity already claimed
by a line under review.

### Duplicate identities

Duplicate groups use `(supplier_id, invoice_number, line_number)` and are formed before
allocation:

- Every row in a duplicate group receives `DUPLICATE_INVOICE` and `REVIEW_REQUIRED`.
- An exact duplicate group consumes its shared quantity once.
- Conflicting quantities against the same PO line/item consume the maximum quantity once.
- Conflicting PO number, PO line, or item targets make the group ambiguous; it consumes no
  capacity and every row has zero supported quantity.
- Other row differences, such as price, remain visible in their individual results.

Every duplicate row displays its own full invoice amount as potential exposure. The summary
counts the identity once using the maximum row exposure, avoiding both arbitrary canonical rows
and duplicate financial totals.

### Price and issue policy

Price matching uses `Decimal` and the configured relative tolerance:

```text
abs(invoice price - PO price) <= PO price * tolerance
```

Only zero matches a zero PO price. The default tolerance is `0.02`, and callers may supply a
different `ReconciliationConfig`.

Issue tuples use this stable order:

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

A result with no issues is `MATCHED`; any issue makes it `REVIEW_REQUIRED`.

### Potential disputed amount

Unknown PO/item references, duplicate identities, supplier mismatches, and currency mismatches
use the full invoice extended amount. Missing receipt evidence produces zero supported quantity
for exposure calculation while retaining `received_quantity = None` in the result.

Other review lines use one non-double-counting calculation. When the invoice price is within
tolerance, it is the accepted unit-price baseline for supported quantity:

```text
invoice amount   = invoiced quantity * invoice unit price
supported amount = supported quantity * invoice unit price
disputed amount  = max(invoice amount - supported amount, 0)
```

This ensures that a tolerated invoice price is not disputed merely because a quantity issue also
exists. For example, invoicing 120 units at `101.50` against 100 supported units at a PO price of
`100.00` and a 2% tolerance exposes only `20 * 101.50 = 2030.00`.

When the invoice price is outside tolerance and produces `PRICE_MISMATCH`, supported quantity is
valued at the PO price:

```text
supported amount = supported quantity * PO unit price
```

A fully matched line, including a price difference inside tolerance, has no disputed amount.
Missing receipt evidence still provides zero supported quantity, so the full invoice amount is
exposed. Amounts are rounded with `money_decimal_places` and `money_rounding`. Summary amounts are
built from rounded line/group exposure and kept separate by invoice currency.

### Summary semantics

`ReconciliationSummary` counts logical invoices by `(supplier_id, invoice_number)`, input rows,
matched and review rows, and row-level issue occurrences. Disputed currencies are sorted and
zero-total currencies are omitted. Building the PO index and receipt totals is linear; invoice
grouping and ordering is `O(I log I)`.

## Reporting

Phase D exposes four pure rendering functions:

```python
from reconcile import (
    render_csv_results,
    render_csv_summary,
    render_json_report,
    render_terminal_report,
)

terminal_text = render_terminal_report(results, summary)
json_text = render_json_report(results, summary)
result_csv = render_csv_results(results)
summary_csv = render_csv_summary(summary)
```

They accept existing domain results and summaries, return strings, perform no file access, and do
not repeat reconciliation logic. Callers decide whether and where those strings are written.

### Serialization contract

- Dates use ISO `YYYY-MM-DD` strings.
- Every `Decimal` is rendered directly as a base-10 string without float conversion. Quantities
  and unit prices retain their meaningful precision; already-quantized disputed amounts retain
  their money precision.
- Status and issue enums use their stable string values.
- JSON uses `null` for missing optional values and arrays of strings for issues.
- Detailed CSV uses an empty cell for missing optional values and joins multiple issues with `|`.
- Every format preserves the incoming result order. JSON object fields and summary rows use an
  explicitly defined order, and every rendered string ends with `\n`.

The JSON report is one object with authoritative summary data followed by detailed results:

```json
{
  "summary": {
    "invoices_processed": 15,
    "disputed_amounts": {"MAD": "10199.00"}
  },
  "results": [
    {
      "supplier_id": "SUP-ALPHA",
      "invoice_date": "2026-01-10",
      "status": "MATCHED",
      "issues": [],
      "invoice_unit_price": "250.00",
      "po_unit_price": "250.00"
    }
  ]
}
```

The abbreviated example shows value types; the actual result objects contain every documented
`ReconciliationResult` field in model order.

Detailed CSV contains one result per row with this stable header:

```text
supplier_id,invoice_number,invoice_line_number,invoice_date,po_number,po_line_number,item_code,status,issues,ordered_quantity,received_quantity,previously_invoiced_quantity,current_invoiced_quantity,supported_quantity,invoice_unit_price,po_unit_price,potential_disputed_amount,currency
```

Summary CSV is a separate tidy table rather than fake rows appended to detailed results:

```text
category,key,value
metric,invoices_processed,15
issue,UNKNOWN_PO,1
disputed_amount,MAD,10199.00
```

Metrics come first, followed by issues in reconciliation policy order and disputed currencies in
summary order. The terminal report shows counts, issue totals, authoritative disputed totals, and
actionable detail only for review-required lines. It uses plain ASCII with no color, terminal
width detection, or third-party formatting dependency.

### Authoritative totals

Row results explain why individual records need review. `ReconciliationSummary.disputed_amounts`
is the authoritative financial aggregate in every report. Renderers never sum row-level disputed
amounts because duplicate rows intentionally display their own exposure while the summary counts
each duplicate identity group only once.

## Command-line interface

Install the project to create the `reconcile` command:

```bash
python -m pip install -e .
```

The same interface is available through `python -m reconcile`.

### Quick start

The three input paths are required. Terminal reporting is the default and writes to stdout:

```bash
reconcile \
  --purchase-orders examples/sample_data/purchase_orders.csv \
  --receipts examples/sample_data/goods_receipts.csv \
  --invoices examples/sample_data/invoices.csv
```

The command contract is:

```text
usage: reconcile [-h] --purchase-orders PATH --receipts PATH --invoices PATH
                 [--format {terminal,json,csv}] [--output PATH] [--force]
```

Terminal and JSON reports go to stdout unless `--output` names an exact file:

```bash
reconcile \
  --purchase-orders purchase_orders.csv \
  --receipts goods_receipts.csv \
  --invoices invoices.csv \
  --format json

reconcile \
  --purchase-orders purchase_orders.csv \
  --receipts goods_receipts.csv \
  --invoices invoices.csv \
  --format json \
  --output reports/reconciliation.json
```

CSV mode requires an explicit output directory because it preserves the two Phase D tables:

```bash
reconcile \
  --purchase-orders purchase_orders.csv \
  --receipts goods_receipts.csv \
  --invoices invoices.csv \
  --format csv \
  --output reports
```

This creates exactly:

```text
reports/
├── reconciliation-results.csv
└── reconciliation-summary.csv
```

Missing parent directories are created. Existing report files are refused unless `--force` is
present. CSV mode checks both destinations before writing either file, so an existing summary
cannot leave behind a newly written results file. Formats are never inferred from extensions.

Successful stdout mode emits only the report. Successful file mode emits a concise destination
confirmation. Usage, source-validation, and output errors go to stderr.

| Exit code | Meaning |
| ---: | --- |
| `0` | Successful reconciliation and reporting |
| `1` | Unexpected unhandled application failure |
| `2` | CLI usage or argument error |
| `3` | Input CSV or source-validation error |
| `4` | Output path, overwrite, or filesystem error |

The V0.1 CLI deliberately has no stdin input, directory discovery, interactive prompts,
configuration files, environment configuration, or business-policy options. It uses the existing
`ReconciliationConfig` defaults and keeps the Python API available for programmatic use.

## Known V0.1 limits

The line-level invoice CSV has no source-system document occurrence ID. It can reliably expose
repeated line identities, but it cannot prove that an entire invoice was imported twice when
the second copy has changed line data. That stronger check would require an additional stable
source identifier and is not invented in V0.1.

Conflicting duplicate rows can be grouped by identity, but without a source-system occurrence ID
the engine cannot determine which copy is authoritative. V0.1 applies the documented conservative
maximum-quantity and maximum-exposure policies instead of silently selecting one.

Receipt rows with unknown or mismatched PO items are excluded from valid capacity, but there is
no receipt-level findings model. Reports expose only the invoice-line consequences; a separate
source-quality contract would need to be designed deliberately in a later phase.

Returns, credit notes, cancellations, taxes, freight, and as-of-date reconciliation are outside
V0.1. All supplied valid matching receipts are treated as the current evidence snapshot.

## Development setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the foundation checks:

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Tests deliberately do not inject `src` into `sys.path`. The documented editable installation is
required, and a packaging smoke test confirms the installed distribution metadata matches
`pyproject.toml`.

## Roadmap

- **Phase A:** complete — package, schemas, domain models, fixtures, and tooling
- **Phase B:** complete — strict CSV loading and source validation
- **Phase C:** complete — deterministic reconciliation and cumulative allocation
- **Phase C.1:** complete — report-ready results and corrected tolerated-price exposure
- **Phase D:** complete — terminal, JSON, and CSV reporting with authoritative totals
- **Phase E:** complete — installable CLI with safe file-output behavior
- **Phase F:** portfolio documentation and CI polish

The next implementation step is Phase F only: add a focused CI workflow for supported Python
versions, improve the portfolio-facing project overview, and document reproducible demonstration
commands. Phase F should preserve the accepted domain, reporting, and CLI contracts.
