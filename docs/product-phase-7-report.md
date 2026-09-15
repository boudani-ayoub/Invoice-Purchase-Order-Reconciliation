# Product Phase 7 — Inventory foundation and explicit stock movements

## Outcome and scope

Phase 7 adds a quantity-only operational inventory ledger. Organization administrators configure
item base units and flat locations, then explicitly post opening balances, stock receipts, stock
issues, adjustments, transfers, and reversals. Current on-hand is derived from immutable movement
deltas. AP managers can inspect inventory, while members have no inventory access.

The most important boundary is preserved: an item is not stock, and an imported goods receipt is
not current stock. Saving or repeating any reconciliation run creates zero inventory movements.
The four reconciliation modes, their report snapshots, and the CLI remain unchanged.

This phase does not add valuation, costing, reservations, available-to-promise, multiple-unit
conversion, warehouse hierarchy, lots/serials, reorder logic, procurement intelligence, or other
Phase 8 work. It does not claim production readiness.

## Baseline and repository discipline

- Exact verified starting SHA: `b3687d9da6e9cf71b36d915797725eb8f814df76`.
- Phase 6 GitHub Actions baseline: run `35004204196`, with all four jobs successful.
- Phase 7 implementation head before documentation: `74c514ab0a72b554bb74682684f536575fae33c7`.
- The unrelated root `package-lock.json` remains untracked and unchanged. SHA-256:
  `DAA0308A5EB8C96651E80918807B4EC840C32FA960BC4308AC915136161868AE`.
- Phase 7 was not pushed. Remote verification is therefore outside this report.

## Schema and database boundary

Migration `0007_inventory_ledger` evolves `items` and creates three tables.

`items` gains:

- nullable normalized `base_uom`, with no default invented for existing rows;
- positive optimistic `version`, defaulting existing rows to 1;
- database protection for immutable `item_code`, post-first-movement base unit, and nonzero-stock
  archive.

New tables:

- `inventory_locations`: organization-owned immutable code, mutable name, ACTIVE/ARCHIVED state,
  version, and timestamps;
- `inventory_operations`: operation type, same-organization actor membership, occurred/recorded
  times, request ID, idempotency key/fingerprint, optional reference/note, and reversal link;
- `stock_movements`: same-organization operation/item/location links and exact `NUMERIC` delta.

Tenant-leading unique constraints and indexes cover location code, item/location and location/item
balance scans, operation lookup, chronology, and type/chronology. Composite foreign keys prevent
cross-organization actor, item, location, operation, and reversal links. All new tenant tables have
ENABLE/FORCE RLS and fail closed without a valid transaction-local organization context.

Runtime can SELECT/INSERT ledger rows and update only the documented item/location master columns.
It has no ledger UPDATE, DELETE, or TRUNCATE grant. Triggers reject operation/movement UPDATE or
DELETE, enforce immutable codes/UOM/archive rules, validate movement signs and negative stock, and
defer validation of exact transfer/reversal line shapes until commit. `reconcile_identity` receives
no inventory access, and startup role verification checks that boundary.

Clean-head and `0006`→`0007` migrations preserve all earlier identity, governance, procurement,
run, snapshot, workflow, dashboard, and audit data. Existing items become version 1 with a null
base unit, and no inventory row is fabricated. Downgrade refuses to erase any used inventory state
or item inventory metadata.

## Inventory semantics

- Base UOM is one opaque normalized token per item. It may change before the first movement and is
  immutable afterward. There is no conversion.
- Clients submit positive plain decimal strings. The server derives every movement sign.
- `OPENING_BALANCE`, `STOCK_RECEIPT`, and `ADJUSTMENT_IN` add stock.
- `STOCK_ISSUE` and `ADJUSTMENT_OUT` subtract stock.
- `TRANSFER` creates an equal negative source and positive destination line in one transaction.
- `REVERSAL` creates exact inverse lines and links the original. One direct reversal is permitted.
- On-hand is `SUM(stock_movements.quantity_delta)` by organization, item, and location.
- An outbound operation, including a reversal, cannot make on-hand negative.
- Opening balance is allowed only before any history for the item/location.
- `occurred_at` accepts timezone-aware backdating but not the future. `created_at` is server-owned.
  Current on-hand includes every posted movement; this is not an as-of reporting system.
- Item/location archive is reversible but requires zero derived stock. Archived masters remain in
  history and reject new movements.

Every writer takes the organization/idempotency advisory lock, locks the item, then locks affected
locations in deterministic UUID order. This closes the first-movement/base-UOM race, prevents
concurrent overselling, and avoids opposing-transfer deadlocks. It deliberately serializes writes
at location level.

The idempotency key is a client UUID unique within the organization. The first request returns
`201`; the same actor and canonical intent returns the same operation with `200`; another actor or
intent returns `409`. Concurrent same-key requests create one operation. The browser retains the
key after an ambiguous response and offers an explicit same-key retry.

## Authorization and endpoints

| Capability | MEMBER | AP_MANAGER | ORG_ADMIN |
| --- | :---: | :---: | :---: |
| View item/location masters | No | Yes | Yes |
| View current on-hand and operation history | No | Yes | Yes |
| Create/update/archive/restore masters | No | No | Yes |
| Post movement, transfer, or reversal | No | No | Yes |

| Routes | Permission |
| --- | --- |
| `GET /api/v1/inventory/items[/{id}]` | `VIEW_INVENTORY` |
| `GET /api/v1/inventory/locations[/{id}]` | `VIEW_INVENTORY` |
| `GET /api/v1/inventory/balances` | `VIEW_INVENTORY` |
| `GET /api/v1/inventory/operations[/{id}]` | `VIEW_INVENTORY` |
| `POST/PATCH /api/v1/inventory/items...` | `MANAGE_INVENTORY_MASTER` |
| `POST/PATCH /api/v1/inventory/locations...` | `MANAGE_INVENTORY_MASTER` |
| `POST /api/v1/inventory/movements` | `POST_INVENTORY` |
| `POST /api/v1/inventory/transfers` | `POST_INVENTORY` |
| `POST /api/v1/inventory/operations/{id}/reverse` | `POST_INVENTORY` |

Master writes use expected versions and locked rows. All write models forbid extra fields and never
accept organization or actor. Foreign identifiers return `404` after authorization. Reads use
bounded keyset pages, default 25 and maximum 100.

Inventory history already carries its authenticated actor, request ID, type, occurred time, and
recording time. The Phase 6 general governance audit was reviewed, but Phase 7 does not widen the
identity role or copy inventory notes/references/movement detail into that view. The inventory
operation history remains the authoritative posting audit.

## Frontend

`/inventory` emphasizes current on-hand and movement history. AP managers receive the read-only
view; organization administrators receive master and posting controls; members receive no nav item
and a server-backed denial. The page supports exact decimal rendering, atomic transfer, reversal,
zero-stock archive, focused conflict errors, stable-key ambiguous retry, keyboard-operable scroll
regions, and a 375 px layout. Untrusted master/reference values render as React text.

The UI states prominently that procurement receipts never post stock. It does not show valuation,
availability, charts, reorder advice, or inferred procurement provenance.

## Verification

Verification used PostgreSQL 17.11, Python 3.11.16 and 3.12.7, Next.js 16.3.4, and Chromium against
the real FastAPI/Next production/PostgreSQL stack. Data and databases were synthetic and disposable.

| Check | Result |
| --- | --- |
| Python 3.11 suite without PostgreSQL | 339 passed, 395 database-gated tests skipped, one existing Starlette/AnyIO deprecation warning |
| Python 3.12 suite without PostgreSQL | 339 passed, 395 database-gated tests skipped, same warning |
| PostgreSQL 17.11 integration suite | 400 passed, same warning |
| Focused inventory database suite | 24 passed |
| Migration/schema focus | 38 passed across inventory upgrade and database schema tests |
| Ruff | format check passed; lint passed |
| Frontend unit/component suite | 161 passed across 17 files |
| ESLint | passed |
| npm audit (`high`) | 0 vulnerabilities |
| Next production build | passed; 22 routes generated, including `/inventory` |
| Chromium real-stack suite | 39 passed in 2.0 minutes |
| axe | 36 tested-state scans; zero serious or critical violations |
| Canonical three-way regression | 15 invoices, 17 lines, 6 matched, 11 review required; EUR 2450.00, MAD 10199.00, USD 75.00 |

Database coverage includes live role downgrade/member archive, organization switching, tenant
aggregate isolation, master versions/immutability/archive, exact decimal rejection, opening and all
movement signs, atomic transfer failure, ordered opposing transfers, concurrent issues from 10
(one 7 succeeds, one fails, final 3), transfer and outbound reversals, negative inbound reversal,
same-key concurrency, changed-intent/actor idempotency conflicts, immutable ledger triggers,
missing RLS context, grants, clean/upgrade/downgrade safety, and repeated procurement imports
creating no stock.

The browser acceptance flow creates an item and two locations, posts opening/receipt/issue/both
adjustments/transfer/reversal, rejects insufficient stock with focused feedback, archives a
zero-stock location, preserves exact quantities across refresh, saves the same procurement inputs
twice without a balance change, renders markup as text, and verifies AP_MANAGER/MEMBER policy.

## Review findings and residual risks

- An early local browser run used a production build compiled for API port 8000 while the E2E API
  used 8010. The network trace identified the mismatch; the documented build-time public origin
  fixed it. This was not a ledger defect.
- Playwright selector review removed ambiguous status/alert/region matches. Axe initially observed
  disabled-button opacity during a refresh; the test now waits for the settled post-archive state
  and reports the real steady-state accessibility result.
- The full database run identified an older Phase 5 upgrade assertion that assumed the broad item
  UPDATE grant would never change. It now preserves every earlier grant except the deliberate item
  narrowing, which `0007` tests independently at column level.
- Windows Playwright-owned server teardown can hang. The final complete run reused explicitly
  started servers and exited normally; the exact disposable database and roles were removed after
  the run.
- Next warns about workspace-root inference because of the pre-existing root lockfile. That file
  was not edited, removed, or staged. Playwright also prints the existing `NO_COLOR`/`FORCE_COLOR`
  warning.
- Location-level locking is conservative and can limit throughput at busy locations. Balance SUM
  cost and ledger storage grow with history. No mutable cache was added without measurement.
- Backdated operations affect current on-hand but Phase 7 does not offer guaranteed historical
  reconstruction. Optional references are unverified plain text, not procurement provenance.
- A compromised organization administrator can intentionally post incorrect stock and then append
  corrections. A database owner can alter grants, triggers, RLS, or history. The ledger is not
  cryptographic non-repudiation.
- Proxy limits, database lock/query monitoring, operational backups, recovery, retention, load
  testing, and deployment threat review remain required before production use.

## Local commits

| Commit | Purpose |
| --- | --- |
| `a6e4962` | append-only inventory schema, constraints, grants, RLS, triggers, and migration tests |
| `cbe7dff` | tenant-scoped service/API, permissions, locking, idempotency, and database behavior tests |
| `74c514a` | role-sensitive inventory UI, exact typed client, unit tests, and real-stack browser flow |

The final documentation commit is reported in the completion message rather than embedded
self-referentially here.

Phase 7 is complete locally. No automatic GoodsReceipt posting exists, no inventory valuation was
added, no Phase 8 feature was implemented, and no push was performed.
