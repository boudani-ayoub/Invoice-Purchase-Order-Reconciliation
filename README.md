# Invoice / Purchase Order Reconciliation

[![CI](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/workflows/ci.yml/badge.svg)](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/workflows/ci.yml)

A deterministic three-way matching tool that validates supplier invoices against purchase
orders and goods receipts before payment.

**Status:** The V0.1 core CLI is complete. Web Phase 1 adds an optional stateless FastAPI adapter
without changing the accepted reconciliation or reporting contracts.

## Why this exists

- A purchase order says what was ordered and at what price.
- A goods receipt says what actually arrived.
- An invoice says what the supplier wants to be paid.

Accounts payable needs all three views to agree. This tool flags unknown references, duplicate
invoices, supplier or currency conflicts, missing receipts, unsupported quantities, and price
mismatches. It also calculates potential disputed exposure per currency.

The important case is cumulative exposure:

```text
PO ordered: 100             Received: 100
Invoice A: 70               Invoice B: 50

Independent checks: 70 <= 100 and 50 <= 100
Cumulative invoice quantity: 120
Result: review required
```

## Architecture

```text
CSV inputs → strict validation → typed models → reconciliation → authoritative results
                                                        │
                              ┌─────────────────────────┴─────────────────────────┐
                              ↓                                                   ↓
                    CLI + file outputs                              FastAPI JSON adapter
                                                                                ↑
                                                                         future frontend
```

Validation, reconciliation, rendering, and filesystem orchestration remain separate. The core
engine can therefore be reused without importing the CLI or changing its business rules.

## Quick start

```bash
git clone https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation.git
cd Invoice-Purchase-Order-Reconciliation
python -m venv .venv
```

Activate the environment with `source .venv/bin/activate` on Linux/macOS,
`.venv\Scripts\Activate.ps1` in PowerShell, or `.venv\Scripts\activate.bat` in Command Prompt.
Then install and run:

```bash
python -m pip install -e ".[dev]"
reconcile \
  --purchase-orders examples/sample_data/purchase_orders.csv \
  --receipts examples/sample_data/goods_receipts.csv \
  --invoices examples/sample_data/invoices.csv
```

The sample files are deterministic synthetic fixtures, not real supplier or customer data.

## Sample outcome

The included scenario exercises the main matching and review paths:

```text
15 invoices
17 invoice lines
6 matched
11 review required

UNKNOWN_PO=1
UNKNOWN_ITEM=1
DUPLICATE_INVOICE=2
SUPPLIER_MISMATCH=1
CURRENCY_MISMATCH=1
MISSING_RECEIPT=1
QUANTITY_EXCEEDS_PO=2
QUANTITY_EXCEEDS_RECEIPT=2
PRICE_MISMATCH=1

Potential disputed amount:
EUR=2450.00
MAD=10199.00
USD=75.00
```

Summary disputed totals are authoritative. Detailed duplicate rows remain visible for review but
are not double-counted in those totals.

## CLI usage

Both installed entry points expose the same contract:

```text
reconcile
python -m reconcile

--purchase-orders PATH
--receipts PATH
--invoices PATH
--format {terminal,json,csv}
--output PATH
--force
```

Terminal output is the default:

```bash
reconcile \
  --purchase-orders examples/sample_data/purchase_orders.csv \
  --receipts examples/sample_data/goods_receipts.csv \
  --invoices examples/sample_data/invoices.csv
```

Render JSON to stdout:

```bash
reconcile \
  --purchase-orders examples/sample_data/purchase_orders.csv \
  --receipts examples/sample_data/goods_receipts.csv \
  --invoices examples/sample_data/invoices.csv \
  --format json
```

Write JSON to a file:

```bash
reconcile \
  --purchase-orders examples/sample_data/purchase_orders.csv \
  --receipts examples/sample_data/goods_receipts.csv \
  --invoices examples/sample_data/invoices.csv \
  --format json \
  --output reports/report.json
```

Write the two CSV reports:

```bash
reconcile \
  --purchase-orders examples/sample_data/purchase_orders.csv \
  --receipts examples/sample_data/goods_receipts.csv \
  --invoices examples/sample_data/invoices.csv \
  --format csv \
  --output reports/run-001
```

CSV mode creates `reconciliation-results.csv` and `reconciliation-summary.csv` in the output
directory. Existing reports are refused by default; `--force` explicitly permits replacement.

| Exit code | Meaning |
| ---: | --- |
| `0` | Success |
| `2` | Invalid CLI usage |
| `3` | Input or CSV validation error |
| `4` | Expected output/filesystem error |

## Web API — MVP

The optional FastAPI layer exposes the same engine and Phase D JSON representation over HTTP. The
CLI remains available without installing any web dependencies.

Install the web and test extras, then start the development server:

```bash
python -m pip install -e ".[dev,web]"
python -m uvicorn reconcile.web.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI interface. The MVP provides:

```text
GET  /health
POST /api/v1/reconcile
```

Submit the three required multipart fields:

```bash
curl -X POST \
  -F "purchase_orders=@examples/sample_data/purchase_orders.csv" \
  -F "receipts=@examples/sample_data/goods_receipts.csv" \
  -F "invoices=@examples/sample_data/invoices.csv" \
  http://127.0.0.1:8000/api/v1/reconcile
```

Each upload has a 10 MiB application limit. Files are streamed into fixed names inside a unique
request directory, reconciled, and removed before the response completes. Client filenames,
extensions, and MIME types are not trusted; the existing strict CSV loaders remain authoritative.
The service stores no uploads or results.

Invalid CSV returns a structured `422` response, oversized files return `413`, and missing
multipart fields use FastAPI's `422` request validation. This MVP has no authentication,
persistence, or CORS configuration and must not be exposed anonymously to the public internet with
sensitive financial data.

## Input contract

All inputs are UTF-8 CSV files with an exact header and at least one data row:

```text
purchase_orders.csv
po_number,line_number,supplier_id,order_date,currency,item_code,description,ordered_quantity,unit_price

goods_receipts.csv
receipt_id,line_number,po_number,po_line_number,receipt_date,item_code,received_quantity

invoices.csv
invoice_number,line_number,supplier_id,invoice_date,po_number,po_line_number,currency,item_code,invoiced_quantity,unit_price
```

Dates use `YYYY-MM-DD`; currencies use three uppercase letters; quantities are positive decimals;
prices are non-negative decimals. Leading/trailing whitespace, malformed numbers, invalid UTF-8,
wrong-width rows, and inconsistent document fields are rejected rather than silently cleaned.

## Engineering decisions

- `Decimal` keeps binary floating-point error out of money and quantity calculations.
- Strict parsing makes source-quality failures visible before matching begins.
- Validation and reconciliation are separate responsibilities.
- Stable sorting makes allocation and output independent of CSV row order.
- Cumulative allocation catches several individually valid invoices that exceed one PO or receipt.
- Duplicate groups have an explicit conservative capacity and exposure policy.
- Summary totals are computed by the engine, not reconstructed by report consumers.
- JSON and CSV schemas serialize financial values as fixed-point strings.
- Output paths do not overwrite silently; forced writes use staged replacement.
- Business logic has no dependency on argument parsing or filesystem output.

## Technology

- Python 3.11+
- `dataclasses`, `Decimal`, `csv`, `json`, `pathlib`, and `argparse`
- FastAPI and Uvicorn as optional web dependencies
- pytest and Ruff
- setuptools with `pyproject.toml`
- GitHub Actions

The core CLI deliberately uses only the Python standard library at runtime. FastAPI, Uvicorn, and
multipart parsing are isolated in the `web` extra; the local CLI does not require them.

## Testing, CI, and packaging

Run the same checks used by CI:

```bash
python -m pip install -e ".[dev,web]"
python -m pytest -vv
python -m ruff check .
python -m ruff format --check .
python -m pip check
python -m build
python -m reconcile --help
reconcile --help
```

The workflow in `.github/workflows/ci.yml` performs the complete core and web suite on Python 3.11
and 3.12 after installing both extras. It also runs the CLI sample and installs the built wheel
without dependencies in a clean environment, proving core imports and the CLI remain independent
of FastAPI. No `PYTHONPATH` shortcut is used. Dependabot checks dependencies and official GitHub
Actions weekly.

Official actions are referenced by their stable major versions so compatible maintenance updates
arrive automatically; the workflow grants only read access to repository contents.

## Security

CSV content is data, never shell input or executable code. The optional API adds a network boundary
with upload limits and temporary request storage, but intentionally has no authentication yet.
Review [`SECURITY.md`](SECURITY.md) before processing sensitive data or deploying the service.

## Known limits

- No web UI, database, authentication, authorization, or saved run history.
- The API is a local/development MVP, not a public production financial service.
- No returns, credit notes, taxes, freight, or as-of-date reconciliation.
- No receipt-level findings model.
- No proof of a repeated whole document without a source occurrence identifier.
- No project-specific row-count or file-size limit; inputs are processed in memory.
- Detailed CSV favors exact machine-readable values over spreadsheet formula escaping.
- Two forced CSV replacements are staged together but are not one transactional operation.
- This is a focused V0.1 control engine, not production ERP software.

## Next web phase

Web Phase 2 can add a frontend while continuing to reuse the same backend and core package:

```text
React / Next.js frontend
          ↓
existing FastAPI adapter
          ↓
existing reconciliation package
          ↓
PostgreSQL for saved runs, users, and history
```

The next phase should focus on upload UX, validation feedback, and result presentation. Public
deployment, authentication, authorization, and persistence remain separate later concerns.

## Project history

The implementation decisions and verification evidence are preserved in
[`docs/`](docs), from [`Phase A`](docs/phase-a-report.md) through
[`Phase F`](docs/phase-f-report.md), followed by the separate
[`Web Phase 1`](docs/web-phase-1-report.md).

## License

Released under the [MIT License](LICENSE).
