# Invoice / Purchase Order Reconciliation

[![CI](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/workflows/ci.yml/badge.svg)](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/workflows/ci.yml)

A deterministic procurement/AP analysis tool for invoice matching, receipt coverage, and
purchase-order fulfillment.

**Status:** Product Phase 3 saves organization-scoped analysis runs, validated source evidence,
immutable reports, and actor-aware audit events. History supports title/note edits and reversible
archive with stale-write protection. Raw uploads remain temporary. The CLI remains account-free
and database-free. AP assignment/resolution, dashboards, admin screens, and inventory are not implemented.

## Choose a workflow

Open `/reconcile` to select a workflow, or bookmark its dedicated page.

| Workflow | Required CSV files | What it checks | Unavailable controls |
| --- | --- | --- | --- |
| Invoice ↔ PO: classic two-way invoice match | Purchase orders, invoices | References, duplicates, supplier, currency, cumulative ordered capacity, price tolerance | Receipt coverage |
| Invoice ↔ Receipt: receipt-coverage invoice check | Goods receipts, invoices | Exact PO/line/item receipt references, duplicates, cumulative received capacity | PO price, ordered quantity, PO supplier/currency, commercial terms |
| PO ↔ Receipt: receiving / fulfillment analysis | Purchase orders, goods receipts | Fully/partially/not/over-received lines, outstanding delivery, unresolved receipts | Invoice/payment exposure, inventory balances |
| Three-way: invoice ↔ PO ↔ receipt | All three files | Existing invoice controls against both order terms and received capacity | Taxes, returns, credit notes, as-of-date controls |

Each browser workflow uses `/api/v1/runs/<mode>` and `/reconcile/<mode>`, where mode is `invoice-po`,
`invoice-receipt`, `po-receipt`, or `three-way`. Each API endpoint declares exactly its required
multipart fields. `/api/v1/reconcile` and the original `/` page remain available for three-way use.
The protected `/api/v1/analyses/<mode>` routes remain available for stateless API clients.
New reports include a `mode` discriminator; receiving reports have their own types and separate
`orphan_receipts`, rather than meaningless invoice fields.

Invoice ↔ PO supports the current quantity up to remaining ordered capacity. Invoice ↔ Receipt
supports it up to remaining exact-key receipt capacity. Its potential unsupported amount is
`(invoice quantity - supported quantity) × invoice unit price`, rounded with the existing Decimal
policy. Duplicate groups retain full invoice exposure, counted once at the maximum group amount;
ambiguous targets consume no capacity. Receipt coverage cannot establish agreed price variance.

Receiving analysis aggregates valid receipts, reports every unresolved receipt separately, and
values outstanding/excess quantities at the PO unit price by currency. Partial delivery is an
open fulfillment state, not automatically an error. These values are not invoice disputes.

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
                                                                       Next.js frontend
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

## Authenticated web API

The optional FastAPI layer exposes the four analysis services over HTTP. The legacy three-way
route retains the Phase D JSON representation. The CLI needs no web dependencies.

Install the optional product dependencies, provision the separate database roles, and apply the
migrations using [the database guide](docs/database-development.md). Configure private environment
variables using [.env.example](.env.example); the server does not load dotenv files automatically.
Then start the server:

```bash
python -m pip install -e ".[dev,web,db,auth]"
python -m uvicorn reconcile.web.app:app --host 127.0.0.1 --port 8000
```

Development can enable `/docs`; production documentation is disabled by default. The API provides:

```text
GET  /health
GET  /api/v1/auth/csrf
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
POST /api/v1/auth/select-organization
POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
POST /api/v1/auth/verify-email
POST /api/v1/auth/resend-verification
POST /api/v1/reconcile
POST /api/v1/analyses/invoice-po
POST /api/v1/analyses/invoice-receipt
POST /api/v1/analyses/po-receipt
POST /api/v1/analyses/three-way
```

All five analysis POST routes require a valid session, current organization membership, and CSRF
proof. Sign in through the browser UI to run them. For an API client, bootstrap `/api/v1/auth/csrf` into a
cookie jar, send its returned `csrf_token` as `X-CSRF-Token` with a trusted `Origin` on registration
and login, and retain the fresh cookies and proof returned by login. A three-way request then uses:

```bash
curl -X POST \
  -b "$COOKIE_JAR" \
  -H "Origin: $FRONTEND_ORIGIN" \
  -H "X-CSRF-Token: $CSRF_PROOF" \
  -F "purchase_orders=@examples/sample_data/purchase_orders.csv" \
  -F "receipts=@examples/sample_data/goods_receipts.csv" \
  -F "invoices=@examples/sample_data/invoices.csv" \
  http://127.0.0.1:8000/api/v1/reconcile
```

Each upload has a 10 MiB application limit. Files are streamed into fixed names inside a unique
request directory, reconciled, and removed before the response completes. Client filenames,
extensions, and MIME types are not trusted; the existing strict CSV loaders remain authoritative.
Persistent routes retain validated records, safe filename metadata, byte counts, SHA-256 hashes,
findings, and the exact report snapshot. Stateless routes retain none of that business data.

Invalid CSV returns `422`, oversized files return `413`, missing/expired sessions return `401`,
and failed membership/CSRF checks return `403`. Explicitly trusted origins receive credentialed
CORS for GET/POST/PATCH and the CSRF header; wildcard origins are rejected. Sensitive responses use
`Cache-Control: no-store`. Authentication does not by itself approve public production deployment.

## Saved runs and history

| Endpoint | Contract |
| --- | --- |
| `POST /api/v1/runs/invoice-po` | `purchase_orders`, `invoices` multipart files |
| `POST /api/v1/runs/invoice-receipt` | `receipts`, `invoices` multipart files |
| `POST /api/v1/runs/po-receipt` | `purchase_orders`, `receipts` multipart files |
| `POST /api/v1/runs/three-way` | All three multipart files |
| `GET /api/v1/runs` | Bounded keyset history; `mode`, `archived`, `limit`, `cursor` |
| `GET /api/v1/runs/{id}` | Run metadata, stored report, provenance, engine/schema versions |
| `PATCH /api/v1/runs/{id}` | `expected_version` plus `title` and/or `note` only |
| `POST /api/v1/runs/{id}/archive` | `expected_version`; hide from active history |
| `POST /api/v1/runs/{id}/restore` | `expected_version`; return to active history |

Create returns `201` with `{ "run": { ... }, "report": { ... } }` only after the source records,
run, findings, snapshot, and audit event commit together. History reads never rerun reconciliation.
An invalid source or failed write leaves no partial saved run. Storage range/encoding failures
return a safe `422` instead of truncating source values. Cross-organization IDs return `404`.

Members can create/view runs; AP managers and organization admins can also edit/archive/restore.
Titles are at most 120 characters, notes 4000; both are optional plain text. Every successful
mutation increments `version` and records its actor. Stale versions return `409`, with a refresh
action rather than overwriting another editor. Archive is not erasure; there is no purge API.

Open `/history` for active/archived filters and pagination, then `/history/{id}` for saved results.
A timeout or lost response can occur after a commit: check History before resubmitting. There is
no automatic create retry, idempotency key, background worker, or fallback to a stateless request.
See the [Phase 3 report](docs/product-phase-3-report.md),
[persistence threat model](docs/threat-model-persistence.md), and
[backup/restore runbook](docs/backup-restore.md).

## Frontend

The frontend is a typed Next.js application under `frontend/`. A four-workflow hub opens dedicated
pages with a shared upload workspace, visible control limitations, mode-specific results,
structured errors, and API-owned Decimal-string totals. Invoice results retain filters and a
responsive horizontally scrollable table.

Use the same browser-facing hostname for both services. After provisioning the database and
private settings, an explicit local-only mail-free setup can use:

```powershell
$env:APP_ENV="development"
$env:FRONTEND_PUBLIC_URL="http://127.0.0.1:3000"
$env:RECONCILE_ALLOWED_ORIGINS="http://127.0.0.1:3000"
$env:AUTH_REQUIRE_VERIFICATION="false"
$env:AUTH_MAIL_MODE="disabled"
python -m uvicorn reconcile.web.app:app --host 127.0.0.1 --port 8000
```

In another terminal, create the local public configuration and start Next.js:

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
npm ci
npm run dev -- --hostname 127.0.0.1
```

Open `http://127.0.0.1:3000/register`, then sign in. Disabled local mail means recovery messages
are not delivered; configure SMTP to exercise delivery, including verification. Production
rejects the verification bypass. Passwords accept 15–128 characters, spaces and Unicode, without
composition rules. `/login`, `/forgot-password`, `/reset-password`, and `/verify-email` provide
the account flows. The authenticated shell shows the user, organization, reconciliation, history, and
sign out; multiple active memberships require a selection.

`NEXT_PUBLIC_API_BASE_URL` is the browser-visible FastAPI origin and
must contain only an HTTP or HTTPS origin. It is public configuration, not a secret. Do not place
tokens or credentials in `NEXT_PUBLIC_*` variables. `NEXT_PUBLIC_RECONCILIATION_TIMEOUT_MS`
controls how long the browser waits for a response and defaults to 120 seconds. A browser timeout
does not cancel reconciliation work already running on the server.

The browser deliberately has no duplicate file-size rule. FastAPI remains authoritative for the
10 MiB per-file limit and returns the file-specific `413` response shown by the UI. See
[`docs/deployment.md`](docs/deployment.md) for the same-origin reverse-proxy profile, TLS, total
request-size, timeout, forwarded-header, process, and logging guidance.

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

## Database and identity boundaries

The `db` extra adds SQLAlchemy 2, Alembic, and psycopg 3; `auth` adds Argon2id and email validation.
PostgreSQL is required for the authenticated web product, never for the CLI. Organizations, users,
memberships, source metadata,
suppliers, items, document headers/lines, analysis runs, findings, and immutable result snapshots
are modeled in an isolated persistence package. Duplicate invoice occurrences and unresolved
source references remain persistable.

See [the data model](docs/data-model-v1.md), [database setup and integration tests](docs/database-development.md),
and [security roadmap](docs/security-roadmap.md). Every tenant business row has organization
ownership, composite foreign keys, and forced PostgreSQL row-level security. This is a database
boundary reached only after server-side session and membership verification. A separate restricted
identity login can access accounts/sessions but not procurement tables. The schema owner is used
only for migrations. Credentials are Argon2id hashes; only hashes of opaque session and email
tokens are stored. See [authentication architecture](docs/authentication-architecture.md),
[the threat model](docs/threat-model-auth.md), and [the Phase 2 report](docs/product-phase-2-report.md).

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
- Next.js, React, TypeScript, Tailwind CSS, and shadcn/ui under `frontend/`
- pytest and Ruff
- Vitest, React Testing Library, ESLint, and the Next.js production build
- Playwright Chromium and axe-core for real-service E2E and accessibility regression checks
- PostgreSQL, SQLAlchemy 2, Alembic, and psycopg 3 in the optional `db` extra
- setuptools with `pyproject.toml`
- GitHub Actions

The core CLI deliberately uses only the Python standard library at runtime. FastAPI, Uvicorn, and
multipart parsing are isolated in the `web` extra; the local CLI does not require them.

## Testing, CI, and packaging

Run the same checks used by CI:

```bash
python -m pip install -e ".[dev,web,db,auth]"
python -m pytest -vv
python -m ruff check .
python -m ruff format --check .
python -m pip check
python -m build
python -m reconcile --help
reconcile --help
cd frontend
npm ci
npm run lint
npm test -- --run
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010 npm run build
npx playwright install chromium
npm run test:e2e
npm audit
```

The workflow in `.github/workflows/ci.yml` performs the complete core and web suite on Python 3.11
and 3.12 after installing all optional product/test extras. It also runs the CLI sample and installs the built wheel
without dependencies in a clean environment, proving core imports and the CLI remain independent
of FastAPI, database, and authentication dependencies. A separate Node 24 job installs the product
API extras and frontend lockfile, lints, runs
Vitest, builds the production Next.js application, installs Chromium, and exercises that build
against a real authenticated Uvicorn process and disposable PostgreSQL database with Playwright
and axe-core. No `PYTHONPATH` shortcut is used. Set `TEST_DATABASE_ADMIN_URL` before database or
browser checks; it must identify an explicitly disposable local/CI PostgreSQL service.
Dependabot checks dependencies and official GitHub Actions weekly.

A separate PostgreSQL 17 job installs `.[dev,web,db,auth]`, tests clean, Phase 1 and Phase 2 upgrades,
and tests auth, constraints, and RLS with distinct non-owner identity/runtime logins. Configure
`TEST_DATABASE_ADMIN_URL` and run `python -m pytest tests/database -vv` to reproduce it locally.
The existing core wheel smoke still installs no optional dependencies.

Official actions are referenced by their stable major versions so compatible maintenance updates
arrive automatically; the workflow grants only read access to repository contents.

## Security

CSV content is data, never shell input or executable code. The optional API adds a network boundary
with authenticated membership checks, CSRF, upload limits, and temporary request storage.
Review [`SECURITY.md`](SECURITY.md) before processing sensitive data or deploying the service.

## Known limits

- No MFA, SSO, member-management UI, AP assignment/resolution, dashboard, or inventory.
- Archive is not deletion; no permanent-purge or retention engine is implemented.
- Production SMTP must be configured and verified; no durable mail queue or auth-state purge job.
- The API is a local/development MVP, not a public production financial service.
- No returns, credit notes, taxes, freight, or as-of-date reconciliation.
- Invoice workflows report invoice findings; the separate fulfillment workflow exposes orphan receipts.
- No proof of a repeated whole document without a source occurrence identifier.
- The CLI has no project-specific row-count or file-size limit; the API enforces 10 MiB per file.
- Detailed CSV favors exact machine-readable values over spreadsheet formula escaping.
- Two forced CSV replacements are staged together but are not one transactional operation.
- This is a focused V0.1 control engine, not production ERP software.

## Next product phase

Product Phase 4 — AP exception workflow, assignment, resolution lifecycle, due dates, comments,
and reminders. This is the next step, not implemented here. The complete sequence through
authenticated deployment is recorded in [the security roadmap](docs/security-roadmap.md).

## Project history

The implementation decisions and verification evidence are preserved in
[`docs/`](docs), from [`Phase A`](docs/phase-a-report.md) through
[`Phase F`](docs/phase-f-report.md), followed by the separate
[`Web Phase 1`](docs/web-phase-1-report.md) and
[`Web Phase 2`](docs/web-phase-2-report.md), then the
[`Web Phase 3`](docs/web-phase-3-report.md) hardening report and
[`Product Phase 1`](docs/product-phase-1-report.md) and
[`Product Phase 2`](docs/product-phase-2-report.md), and
[`Product Phase 3`](docs/product-phase-3-report.md).

## License

Released under the [MIT License](LICENSE).
