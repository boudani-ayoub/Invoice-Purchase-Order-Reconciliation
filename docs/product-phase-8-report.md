# Product Phase 8 — Procurement, supplier, and inventory intelligence

## Outcome and scope

Phase 8 adds a manager-only, read-only intelligence surface. Procurement and supplier views describe
one explicitly selected completed saved run; inventory describes the active organization's current
append-only ledger plus bounded 7/30/90-day activity. AP_MANAGER and ORG_ADMIN may view Insights;
MEMBER may not.

The read model does not create a canonical cross-import business document. It has no all-runs
procurement total, supplier score, payment/spend/savings KPI, on-time-delivery claim, currency
conversion, inventory valuation, unlike-item quantity rollup, forecast, stockout/reorder claim,
recommendation, background analytics system, or AI-generated insight.

## Baseline and repository discipline

- Exact verified starting SHA: `ed66abc629853807e8e0c4189dab721d53eaf961`.
- Final Phase 7 GitHub Actions run: `35061742453`, all four jobs successful.
- The unrelated root `package-lock.json` remains untracked and unchanged. Its SHA-256 is
  `DAA0308A5EB8C96651E80918807B4EC840C32FA960BC4308AC915136161868AE`.
- At the time these local verification results were recorded, Phase 8 had not been pushed. The
  subsequent remote closure is recorded below.

## Architecture

`VIEW_INTELLIGENCE` is an explicit permission assigned only to AP_MANAGER and ORG_ADMIN. Every GET
rechecks the live active membership, enters the transaction-local tenant context, and remains under
forced RLS. Cross-tenant or non-completed run IDs return `404`; completed archived runs remain
analyzable.

The API adds:

- `GET /api/v1/intelligence/runs/{run_id}/procurement`;
- `GET /api/v1/intelligence/runs/{run_id}/suppliers` with bounded keyset pagination;
- `GET /api/v1/intelligence/inventory?window=7d|30d|90d` with bounded position pagination.

There are no intelligence mutation routes. Reads do not invoke reconciliation or change run,
snapshot, finding, workflow, master, ledger, or audit state. `no-store` remains the authenticated API
cache policy.

Selected-run procurement uses the exact source IDs in `analysis_sources`. Immutable snapshot
summary/result facts remain authoritative for reconciliation outcomes; selected source rows support
only document/line counts, exact source values, dates, and attribution. Supplier rows retain exact
source codes and nullable master labels, so unresolved identities are visible without fabricated
records.

Inventory uses only `inventory_operations` and `stock_movements`. Current on-hand includes all
committed movements; period counts and net delta use UTC `occurred_at` in `[start,end)`. Imported
goods receipts do not post inventory and are never treated as ledger provenance.

## Metrics and frontend

The exact definition, source, population, denominator, currency, time, archive, and null behavior
of every field is recorded in [the intelligence metric contract](intelligence-metrics.md). The
[threat review](threat-model-intelligence.md) records tenant, semantic, performance, and browser
risks.

`/insights` provides Procurement, Suppliers, and Inventory sections. Procurement/Suppliers require
an active or archived saved-run selection and state that the metrics describe only that analysis.
Inventory states that imported receipts do not post stock and offers 7/30/90-day windows. Tables use
per-currency rows, exact decimal strings, explicit unavailable states, source supplier identities,
eligible timing denominators, and current item/location quantities. React renders untrusted labels
as text. The navigation and page guard are usability controls; FastAPI authorization is decisive.

## Schema and query evidence

No analytics table, cache, materialized view, task queue, or write grant was added. Migration `0008`
adds only `ix_inventory_operations_intelligence_window` on
`inventory_operations (organization_id, occurred_at, operation_type)`. Clean migration and
`0007 → 0008 → 0007 → 0008` preservation coverage retain Phase 7 data exactly.

The measured operation-count plan used 20,000 synthetic operations under the restricted runtime
role and forced RLS. Execution measured 2.624 ms without the new index and 0.657 ms with it; the
indexed plan named the index and produced the same result rows. This is local comparative evidence,
not a production capacity claim.

Supplier query count is constant between page limits 1 and 10 and capped by test at 12 SELECTs.
Procurement is capped at 12 SELECTs and inventory at 10. Grouped SQL and one bounded supplier-label
lookup avoid per-supplier/item queries and loading entire ledgers.

## Verification

Verification used PostgreSQL 17.11, Python 3.11.16 and 3.12.7, Next.js 16.3.4, and Chromium against
the real FastAPI/Next production/PostgreSQL stack. Data and databases were synthetic and
disposable.

| Check | Result |
| --- | --- |
| Python 3.11 complete suite without PostgreSQL | 340 passed, 410 database-gated tests skipped, one existing Starlette/AnyIO deprecation warning |
| Python 3.12 complete suite without PostgreSQL | 340 passed, 410 database-gated tests skipped, same warning |
| PostgreSQL 17.11 integration suite | 414 passed, one optional restore-smoke test skipped, same warning |
| Ruff | lint passed; 157 files passed format check |
| Dependency and CLI smoke | `pip check` passed on both Python versions; module CLI help passed |
| Source/wheel build | source distribution and wheel built; isolated no-dependency wheel import, CLI, and sample passed |
| Frontend unit/component suite | 170 passed across 19 files |
| ESLint | passed |
| npm audit | 0 vulnerabilities |
| Next production build | passed; 23 routes generated, including `/insights` |
| Chromium real-stack suite | all 41 tests reported `ok`; Windows Playwright parent required interruption after child ports closed |
| axe | 39 tested-state scans; zero serious or critical violations |
| Canonical three-way regression | 15 invoices, 17 lines, 6 matched, 11 review required; EUR 2450.00, MAD 10199.00, USD 75.00 |

Backend verification covers explicit/live permission checks, duplicate-run independence, archive
and cross-tenant behavior, mode nullability, unresolved suppliers, issue/fulfillment/timing
attribution, exact currency strings, ledger-only inventory, half-open occurred-time windows, read
immutability, cursor/window bounds, page-constant query counts, the restricted-role query plan, and
migration preservation. The complete Phase 1–7 regression remains green.

The principal real-stack browser acceptance uses Next, FastAPI, PostgreSQL 17, and Chromium. It
selects active and archived runs, keeps duplicate runs separate, proves procurement/ledger
separation, switches inventory windows, exercises AP_MANAGER/MEMBER authorization, renders stored
markup as text, checks keyboard/mobile behavior, and runs axe.

The first complete Python collection exposed a same-basename collision between the new unit and
database intelligence test modules. Renaming the unit module fixed collection without changing test
or product behavior. A normal Windows `dist` build encountered an existing ignored archive lock;
building to a fresh ignored output directory succeeded, and its wheel passed isolated smoke tests.
After all 41 browser cases reported `ok`, Playwright's Windows parent remained blocked during owned
server teardown. Ports 3010/8010 were closed before the parent alone was interrupted; PostgreSQL
remained reachable. These environment observations are recorded rather than misreported as product
failures or a clean Playwright process exit.

## Local commits

| Commit | Purpose |
| --- | --- |
| `8cac02e` | explicit permission, selected-run procurement/supplier reads, ledger-only inventory read, and backend coverage |
| `26c0480` | typed `/insights` interface, role-aware navigation, frontend tests, and real-stack browser acceptance |
| `f971625` | measured inventory occurred-time index, bounded query helpers, plan/query-count and migration coverage |
| `8698223` | rename the unit metric test to prevent a pytest import-name collision with database coverage |
| `55dee8e` | strengthen organization-switch, timing-boundary, ledger-separation, and operation-type regressions |

## Residual limitations

- The same real business document may appear in multiple imports; this is why no cross-run
  procurement truth exists.
- Receipt timing is observed from source dates in one selected source set. There is no promised date
  or contractual SLA, so it is not OTD or lateness.
- Three-way PO fulfillment is grouped from that run's persisted resolved source links to avoid
  multiplying PO lines by invoice result occurrences; Phase 8 does not rerun matching.
- Current inventory is not guaranteed historical as-of state. Backdated appends can change prior
  occurred-time activity windows.
- Current on-hand and period aggregates still grow with ledger history. The measured index supports
  the operation count path, but deployed workloads require monitoring.
- Archived master labels and source identifiers remain visible to authorized users as historical
  business evidence. Archive is not deletion.
- This phase does not claim production readiness.

## Scope confirmation

- No automatic `GoodsReceipt` → stock posting exists.
- No inventory valuation or unlike-item quantity total exists.
- Procurement and supplier intelligence remains selected-run only. There is no organization-wide
  procurement spend or cross-run supplier aggregation, and repeated runs are not summed.
- No supplier score, rating, ranking, recommendation, OTD claim, spend, savings, or cross-run KPI
  exists.
- No AI, anomaly detection, forecasting, reordering, auto-purchasing, ERP integration, Redis,
  Celery, or background analytics worker was added.
- No Phase 9 functionality was implemented.

## Remote closure

The locally verified Phase 8 architecture was pushed at
`26bc8538a735de3f897df220c04b24f476bc92e4`. GitHub Actions run `35146236072` tested that exact
head and completed successfully. All four jobs were green:

- Python 3.11;
- Python 3.12;
- PostgreSQL and authentication integration;
- frontend and authenticated browser verification.

Phase 8 is complete and remotely verified. Phase 9 was not started by this closure update.
