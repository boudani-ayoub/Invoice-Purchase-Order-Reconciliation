# Invoice / Purchase Order Reconciliation

A local-first Python application for three-way matching between purchase orders,
goods receipts, and supplier invoices. The project models the controls an accounts-payable
team applies before approving an invoice for payment.

> **Current status:** Phase A (project foundation) is complete. CSV loading, validation,
> reconciliation, reporting, and the CLI are intentionally reserved for later phases.

## Why this project exists

An invoice should only be paid when its supplier, currency, items, quantities, and prices
agree with both the purchase order and the available receipt evidence. Real procurement data
also contains partial deliveries, several receipts, several invoices, and duplicate records.
This project is designed to handle those cases deterministically without hiding accounting
decisions inside data-manipulation code.

## Architecture

```text
src/reconcile/
├── config.py       # Business policy configuration
├── models.py       # Immutable domain and result objects
└── schemas.py      # Canonical CSV contracts

examples/sample_data/  # Purpose-built demonstration data
tests/                 # Foundation and fixture-contract tests
```

The domain package does not depend on CSV parsing, a CLI framework, or report formatting.
This keeps the future reconciliation engine independently testable. Phase A uses only the
Python standard library at runtime: dataclasses make the data contracts explicit, and
`Decimal` prevents binary floating-point arithmetic from entering financial calculations.

## Input contracts

All files are UTF-8 CSV documents with one header row. Column names and order are exact.
Identifiers are non-empty text, dates use `YYYY-MM-DD`, line numbers are positive integers,
quantities are positive decimal strings, prices are non-negative decimal strings, and
currencies are uppercase three-letter codes. Phase B will enforce these constraints and report
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
item more than once. Keeping both the line reference and item code also lets validation catch
an invoice or receipt that points to a PO line but names the wrong item.

## V0.1 reconciliation assumptions

- Quantities may be fractional and use `Decimal`; zero and negative source quantities are
  invalid rather than business events.
- Unit prices are non-negative financial decimals. The default tolerance is a relative 2%
  difference from the PO price; the exact comparison boundary belongs to Phase C tests.
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
- Reconciliation is a current snapshot: all supplied receipts count even when their receipt
  date is later than the invoice date. An as-of-date mode is outside V0.1.
- Missing receipt evidence means `MISSING_RECEIPT`; it is not represented as a confirmed zero
  delivery.
- Price tolerance is inclusive and relative to the PO price:
  `abs(invoice price - PO price) <= PO price * tolerance`. When the PO price is zero, only a
  zero invoice price matches.
- Disputed amounts will be rounded using `ROUND_HALF_UP` and reported separately by currency.
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

## Known ambiguity and V0.1 limit

The line-level invoice CSV has no source-system document occurrence ID. It can reliably expose
repeated line identities, but it cannot prove that an entire invoice was imported twice when
the second copy has changed line data. That stronger check would require an additional stable
source identifier and is not invented in V0.1.

The brief also does not define a single disputed-amount formula for lines with several issues
(for example, both excess quantity and excess price). Phase C must define and test a
non-double-counting policy before reporting totals; the result model intentionally reserves one
line-level amount rather than separate amounts that could be summed incorrectly.

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

## Roadmap

- **Phase B:** strict CSV loading and row-level validation with clear errors
- **Phase C:** deterministic reconciliation and cumulative allocation rules
- **Phase D:** terminal, JSON, and CSV reporting with per-currency totals
- **Phase E:** command-line interface
- **Phase F:** portfolio documentation and CI polish

The next implementation step is Phase B only: convert each CSV row into its domain model,
validate structural and business constraints, and fail with source filename and row number.
