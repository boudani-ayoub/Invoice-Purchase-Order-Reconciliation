# Product Phase 1 — Analysis modes and persistence foundation

Completed locally on 2026-09-07. Four stateless procurement workflows are implemented, with an
optional PostgreSQL schema for future authenticated persistence. Product Phase 2 is not implemented.

## Repository

- Branch: `main`.
- Starting HEAD: `ae8ba95f5b05d0fbf9bdf06e4bcc87b01c6063bd` — `feat: harden stateless web workflow`.
- Starting tree: tracked files clean; unrelated root `package-lock.json` already untracked.
- Baseline: 195 Python tests, 20 frontend tests, 10 browser/accessibility tests.
- Ending implementation HEAD: `1361d965b88dd9cfe60a60e6ee6c160923e006de`.
- Ending tracked tree: clean after the documentation commit; only the pre-existing unrelated root
  `package-lock.json` remains untracked.
- Push status: **not pushed**, as instructed. Remote GitHub Actions has not run for this phase.
- Local runtime installations, test databases, reports, and build artifacts are excluded from Git.
  The unrelated root lockfile is preserved and is not part of this phase.

| Commit | Scope |
| --- | --- |
| `4f2a0ccd4d84ff355a3de11c4c93612efa875a17` | `feat: add explicit procurement analysis modes` |
| `63e6461fdf12591dc09eea359dab83796a989041` | `feat: add multi-mode reconciliation interface` |
| `1361d965b88dd9cfe60a60e6ee6c160923e006de` | `feat: establish PostgreSQL persistence foundation` |
| This report's creation commit | `docs: record product phase 1 architecture` |

The ending phase HEAD is the closing documentation commit that creates this report. Retrieve its
exact hash without embedding a self-referential commit hash in its own contents:

```bash
git log --diff-filter=A -1 --format="%H" -- docs/product-phase-1-report.md
```

## Analysis workflows

| Mode | Question answered | Required multipart CSV fields | Result types | POST endpoint | Frontend page |
| --- | --- | --- | --- | --- | --- |
| Invoice ↔ PO | Does the invoice agree with the order? | `purchase_orders`, `invoices` | `InvoicePoResult`, `InvoicePoSummary` | `/api/v1/analyses/invoice-po` | `/reconcile/invoice-po` |
| Invoice ↔ Receipt | Are billed quantities supported by receipts? | `receipts`, `invoices` | `InvoiceReceiptResult`, `InvoiceReceiptSummary` | `/api/v1/analyses/invoice-receipt` | `/reconcile/invoice-receipt` |
| PO ↔ Receipt | What was ordered versus received? | `purchase_orders`, `receipts` | `PoReceiptResult`, `PoReceiptSummary`, `OrphanReceipt` | `/api/v1/analyses/po-receipt` | `/reconcile/po-receipt` |
| Three-way | Does the invoice agree with both order terms and receipt coverage? | `purchase_orders`, `receipts`, `invoices` | Existing `ReconciliationResult`, `ReconciliationSummary` | `/api/v1/analyses/three-way` | `/reconcile/three-way` |

### Invoice ↔ PO

Classic two-way invoice matching checks unknown PO/item references, duplicate invoice occurrences,
supplier, currency, cumulative ordered capacity, and the existing price-tolerance policy. No
receipt rules run. A match therefore does not establish delivery.

For a resolved, unambiguous target:

```text
remaining ordered capacity = max(ordered quantity - previously consumed quantity, 0)
supported quantity = min(current invoice quantity, remaining ordered capacity)
```

The accepted Decimal exposure helper handles unsupported quantity, price differences, and
conservative full-exposure cases. The cumulative 70 + 50 against an order of 100 case is tested.

### Invoice ↔ Receipt

Coverage uses the exact validated `(po_number, po_line_number, item_code)` key. Multiple receipts
aggregate. Missing exact coverage produces `MISSING_RECEIPT`; a different receipt item at the same
PO/line also produces `RECEIPT_ITEM_MISMATCH`. Known coverage exceeded cumulatively produces
`QUANTITY_EXCEEDS_RECEIPT`. Duplicate invoice behavior remains conservative.

There is no PO file, so this workflow cannot verify agreed price, ordered quantity, PO supplier,
PO currency, or commercial terms. It never emits `PRICE_MISMATCH`.

```text
supported quantity = min(invoice quantity, max(received quantity - previously consumed quantity, 0))
potential unsupported amount = (invoice quantity - supported quantity) × invoice unit price
```

Amounts use the existing Decimal rounding policy. Duplicate occurrences carry full invoice
exposure, with the maximum group amount included once in summary totals; this is potential
unsupported exposure, not an agreed-price variance.

### PO ↔ Receipt

This is receiving/fulfillment analysis, not invoice reconciliation. It reports `FULLY_RECEIVED`,
`PARTIALLY_RECEIVED`, `NOT_RECEIVED`, and `OVER_RECEIVED`. Partial or absent delivery can mean an
open order and is not automatically an error.

```text
outstanding quantity = max(ordered quantity - aggregated valid receipts, 0)
over-received quantity = max(aggregated valid receipts - ordered quantity, 0)
reference value = corresponding quantity × PO unit price
```

Outstanding ordered values and over-received reference values are rounded per line and summarized
by currency. They are not invoice disputed amounts. Every unresolved receipt is retained in a
separate report section: unknown PO, unknown PO line (`UNKNOWN_ITEM`), or receipt item mismatch.
These receipts do not increase a valid line's received total. No invoice, payment, or inventory
balance claims are made.

### Three-way

The accepted engine remains authoritative. Shared pure helpers were extracted, not replaced by a
mode-switching algorithm. The CLI, original `/` UI, and `POST /api/v1/reconcile` remain supported.
The new three-way route adds a `mode` discriminator around the same results and summary.

### Decisions resolving ambiguity

- Receipt records contain PO-line/item references but no supplier, currency, or price. Matching
  uses those actual fields, not an invented receipt/invoice identifier.
- An exact item match can provide receipt coverage even if other receipt items exist at that
  reference. The fulfillment workflow exposes those other receipts against supplied PO data.
- Logical duplicate identity remains `(supplier_id, invoice_number, line_number)`. An unambiguous
  group consumes its maximum quantity once. Conflicting targets receive zero supported allocation
  and consume no capacity; each occurrence stays visible.
- Receipt dates remain on persisted receipt lines because current validation does not require
  one receipt document date. PO and invoice headers retain their validated header invariants.
- Unconstrained PostgreSQL `NUMERIC` was chosen because existing Decimal inputs have no fixed
  scale ceiling. A newly imposed fixed scale would silently change accepted source values.

## Three-way regression evidence

The accepted sample remains:

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

EUR=2450.00
MAD=10199.00
USD=75.00
```

All 195 pre-existing Python tests remain unchanged and pass. The legacy API still uses its original
JSON renderer. Existing tests compare its bytes with that renderer; new tests compare the three-way
payload, excluding `mode`, with the legacy JSON. Additional tiny-Decimal cases guard against
scientific-notation serialization changing the fixed-point contract. The dependency-free wheel's
CLI reproduces the same sample summary.

## Implemented structure

```text
src/reconcile/
  analysis/
    models.py                 mode/source registry and typed results
    invoice_po.py             commercial order matching
    invoice_receipt.py        received-capacity coverage
    po_receipt.py             fulfillment and orphan receipts
  invoice_helpers.py          shared deterministic grouping/allocation/money helpers
  reconciliation.py           accepted three-way service
  web/
    app.py                    explicit routes and shared secure upload processing
    reports.py                discriminated, typed HTTP reports
  persistence/
    base.py                   UUID/timestamp mapping and tenant composite FKs
    models.py                 relational persistence representations
    session.py                private config and transaction-local tenant context
migrations/
  env.py
  versions/0001_establish_tenant_owned_procurement_.py
frontend/src/
  app/reconcile/               hub, shared layout, and bookmarkable mode pages
  constants/analysis-modes.ts  labels, requirements, controls, limitations, paths
  types/analysis.ts            discriminated TypeScript reports
  lib/api/analyses.ts          mode-aware client and runtime response guards
  hooks/use-reconciliation.ts  shared request/reset/error lifecycle
  components/reconciliation/  shared upload workspace and mode-specific results
```

The API owns calculations and returns Decimal strings. The frontend does not recalculate financial
totals. No new frontend runtime dependency or state-management framework was added. Each mode
shows exactly its required file inputs and identifies the data, controls, and limitations.

New browser accessibility tests exposed a keyboard-scrolling problem with wide result tables.
The shared scroll region now has an accessible name, keyboard focus, and a visible focus ring.
Tests exercise horizontal keyboard scrolling and mobile page-width containment with Unicode data.

## PostgreSQL foundation

| Component | Locally verified version |
| --- | --- |
| PostgreSQL | 17.11 |
| SQLAlchemy | 2.0.52 |
| Alembic | 1.19.2 |
| psycopg / psycopg-binary | 3.3.5 |
| Python | 3.11.16 and 3.12.7 |
| Node.js | 24.19.0 |

The three database packages are isolated in the optional `db` extra. The core wheel installs and
runs without SQLAlchemy, Alembic, psycopg, or FastAPI. Alembic assets are included in the source
distribution; deployments managing the schema use that source tree or the checkout.

The [data model](data-model-v1.md#entities-and-relationships) contains the full Mermaid ER diagram,
entity definitions, ownership rules, and migration/deletion decisions. Its 16 tables are:

- Organizations, users, organization memberships.
- Suppliers, items, source files.
- Purchase orders and lines; goods receipts and lines; invoices and line occurrences.
- Analysis runs, analysis sources, findings, result snapshots.

Every tenant-owned row carries an organization. Tenant relationships use composite foreign keys,
not only application filters. Source references remain separate from nullable resolved links.
Unknown references and mismatches therefore survive storage. Duplicate invoice occurrences have
separate UUIDs/source positions; logical duplicate line numbers are indexed, not unique.

Runs record constrained mode/status, aware timestamps, and an optional creator tied to the same
organization's membership. Source associations and typed finding subjects preserve relational
provenance. An additional JSONB result snapshot records explicit schema and engine versions and
is immutable after insertion. It is historical evidence, not a replacement for relational tables.

### Real integrity constraints

- Required columns, server-generated UUID primary keys, and timezone-aware timestamps.
- Unique normalized organization slug and normalized user email; constrained statuses and roles.
- Unique organization membership, tenant-local supplier/item codes, imported document identities,
  and PO/receipt line identities; distinct invoice source row positions.
- Organization-safe composite foreign keys for headers, source imports, resolved references,
  run sources, findings, snapshots, and creator membership.
- Finite positive quantities; finite nonnegative unit prices, including rejection of NaN/infinity.
- Valid currency shape, positive line/source positions, nonnegative source size, SHA-256 shape,
  and original filename metadata that cannot contain a filesystem path separator.
- Run timestamp ordering, completed timestamp requirement, and a finding subject requirement.
- One versioned snapshot per run; a trigger requires a completed run with the same mode and
  rejects subsequent update/delete. The runtime role has no snapshot mutation grants.
- RESTRICT on business relationships; no automatic cascading history deletion.

Agreement between documents is deliberately **not** constrained. Excess invoice/receipt quantity,
price differences, supplier/currency differences, and unresolved source references are evidence
for analysis, not database-invalid data. Future import services must still run strict loaders.
PostgreSQL NUMERIC/BIGINT capacity errors must be reported, never silently truncated.

## Tenant isolation evidence

All tenant tables ENABLE and FORCE RLS. Policies apply both `USING` and `WITH CHECK` to the
transaction-local `app.current_organization_id`; organizations use their own ID. Missing/reset
context exposes no rows and rejects inserts. Global users also FORCE RLS, with no runtime policy
or grants.

`tenant_session` owns a transaction and binds `set_config(..., true)` using a UUID. It commits on
success and rolls back on failure. It does not authenticate membership: that verification belongs
to the future service boundary. Runtime credentials permit setting context, so RLS is defense in
depth and cannot substitute for identity/authorization.

The administrator provisions database roles. Migrations run as a separate schema owner. The
`reconcile_runtime` NOLOGIN group grants business SELECT/INSERT/UPDATE, snapshot SELECT/INSERT,
and organization/membership SELECT only. Runtime owns no tables, is not superuser/BYPASSRLS, and
has no users access, DELETE/TRUNCATE, or schema CREATE privileges.

The real PostgreSQL suite verifies these cases explicitly:

| Test | Verified behavior |
| --- | --- |
| `test_rls_a_cannot_read_b` | A can read its supplier, organization, and invoices, but not B's supplier |
| `test_rls_a_cannot_update_b` | A can update its supplier; B's update affects zero rows and B stays unchanged |
| `test_rls_a_cannot_insert_b_owned_row` | A's attempted B-owned item insert is rejected |
| `test_rls_prevents_reassigning_ownership` | A cannot change its supplier ownership to B |
| `test_missing_tenant_context_fails_closed` | No-context SELECT/UPDATE sees no rows; INSERT is rejected |
| `test_context_cannot_leak_on_reused_connection` | Both commit and rollback clear A's context; the same backend PID then sees only B under B context |
| `test_composite_fk_blocks_cross_tenant_resolved_link_even_for_admin` | A cannot reference B's PO line even through an RLS-bypassing administrator |
| `test_composite_fk_blocks_cross_tenant_header` | A cannot attach an invoice occurrence to B's header |
| `test_every_table_has_forced_rls` | Every mapped table has ENABLE/FORCE RLS |
| `test_runtime_is_not_owner_superuser_or_bypassrls` | Tests use a genuine restricted runtime role |
| `test_runtime_has_no_identity_or_destructive_privileges` | Identity reads, destructive grants, and schema CREATE are absent |

Each database suite creates a uniquely named clean database and separate roles, runs `alembic
upgrade head` as its owner, and tests metadata parity with `alembic check`. Cases seed fresh
organizations. Fixture cleanup drops only its generated database/roles; no existing project data
is reset. Local verification used a disposable loopback PostgreSQL cluster, not SQLite.

## Persistence exposure and security

**No authenticated persistent HTTP API exists yet. No company-data CRUD routes were exposed
without identity/security.** Current HTTP uploads are still temporary and are not saved to the DB.
No HTTP handler imports persistence. No login, passwords, sessions, invitations, audit UI, history,
dashboard, or inventory quantities were implemented.

All five upload endpoints share the existing security path: server-controlled filenames, unique
request directories, streamed writes, 10 MiB per-file application limit, strict UTF-8 CSV validation,
cleanup, generic unexpected errors, and the established origin policy. Filenames/MIME types are
not trusted. `DATABASE_URL` stays private, configuration errors omit its value, and SQLAlchemy
hides bound parameters. Production credentials are not committed.

The [security roadmap](security-roadmap.md) maps authentication, sessions, authorization, tenant
isolation, CSRF, rate limits, uploads, validation, logging/audit, secrets, least privilege, headers,
TLS, recovery, dependencies, backup/restore, and retention to later phases. It references OWASP
ASVS 5.0 without claiming certification or production security.

## Verification

| Check | Result |
| --- | --- |
| Python 3.11.16, full suite with real PostgreSQL | **280 passed** |
| Python 3.12.7, full suite with real PostgreSQL | **280 passed** |
| New domain/API mode tests | **50 passed**, included in each full suite |
| Database suite | **35 passed**, included in each full suite; 31 use PostgreSQL and 4 validate configuration |
| Frontend Vitest | **32 passed** across 5 files |
| Playwright production frontend + real Uvicorn | **15 passed**; all 10 legacy cases plus hub and four mode cases |
| Accessibility | Axe checks on the hub, all four new workflows, and legacy states; no serious/critical violations |
| Frontend install | Clean `npm ci` with Node 24; zero audit vulnerabilities reported |
| Frontend lint and production build | Passed; strict TypeScript and all dedicated routes build |
| Ruff lint / formatting | Passed |
| Python dependency consistency | `pip check` passed |
| Packaging | Source and wheel builds passed; isolated no-dependency wheel import and CLI sample passed |
| CLI entry points | Both `python -m reconcile --help` and installed `reconcile --help` passed |
| Git whitespace review | Unstaged and staged `diff --check` passed before commits |

Commands reproduce the requested checks: `pytest`, `ruff check .`, `ruff format --check .`,
`pip check`, `build`, both CLI entry points, frontend install/lint/test/build/E2E, and real database
migrations/integration tests. On this Windows host, the supported Node executable was selected
explicitly because the system default is Node 23. Playwright now starts Next using its own
`process.execPath`, preserving the selected runtime.

Observed non-failing warnings: the existing Starlette test client uses a deprecated AnyIO alias;
the current Next lint stack uses ESLint 9; Next notices the unrelated untracked root lockfile.
No dependency upgrade outside this phase or deletion of the user's lockfile was performed.

## CI and remaining limitations

The existing Python 3.11/3.12, frontend, E2E, and accessibility jobs remain. A PostgreSQL 17 service
job installs `.[dev,db]` and runs the real database suite with isolated migration/runtime roles.
Core wheel smoke still installs no optional dependencies. **These CI changes are local; remote CI
has not run because this phase has not been pushed.** Local green checks are not a remote CI result.

Remaining limitations are intentional and real:

- No authenticated HTTP tenant authorization, persistence import/save service, CRUD, or run history.
- RLS context must eventually be derived from verified identity and active membership. Internal
  session helpers alone are not an authorization system.
- Snapshot envelopes are structurally constrained; complete typed report validation and atomic
  import/run persistence belong to the future save service. Source immutability/retention and
  actor-aware audit operations require that service and its authorization model.
- The CLI remains three-way only; new modes are available as pure Python services and HTTP/UI flows.
- No taxes, returns, credit notes, as-of-date controls, inventory balances, or payment approval.
- Current uploads are in-memory analysis with temporary disk files, not durable processing jobs;
  public deployment still needs the documented resource, TLS, authentication, and operational work.
- PostgreSQL 17.11 was tested locally; CI selects supported major 17. No production deployment,
  backup/restore exercise, or ASVS certification is claimed.

## Next step

**Product Phase 2 — Identity, secure sessions, organization membership, tenant authorization, and
protected routes.** Persistent runs and useful CRUD follow in Phase 3, then AP workflow (4), manager
KPIs (5), organization governance (6), inventory movements (7), intelligence (8), and authenticated
production deployment/threat modeling (9). The full sequence is in the security roadmap.

Implementation stops at the Phase 1 boundary.
