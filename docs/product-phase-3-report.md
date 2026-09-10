# Product Phase 3 — persistent runs and history

## Baseline and scope

Started on `main` at `bde0726e84a578cc8946f9d8440ead57bbf3e355`. Tracked files were clean;
the unrelated root `package-lock.json` was untracked and is deliberately preserved/excluded.
The first commit, `1da777d`, corrects the Phase 2 report to record the successful
[GitHub Actions run 34159230108](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/34159230108)
for that starting HEAD: Python 3.11, Python 3.12, PostgreSQL/auth, and frontend/browser jobs passed.

Accepted Phase 2 baseline: 385 Python tests (109 PostgreSQL), 47 frontend tests, and 24 browser
tests. The Python and frontend baselines were rerun before implementation. Phase 3 adds saved
results and useful run metadata CRUD; it does not add AP workflow, dashboards, administration,
inventory, or permanent deletion. The subsequent authorized push published Phase 3 at
`e5c99f62d45a00868d5139b4344e30e4d15f29aa`; its remote CI completed successfully.

## Decisions and ambiguities resolved

- The browser saves every successful analysis, including the legacy three-way workspace. Existing
  stateless HTTP routes remain protected and compatible for callers that explicitly choose them.
- Completed runs only: no PENDING/FAILED placeholder is left when validation, analysis, source
  persistence or audit insertion fails. A lost response can follow a successful commit; History
  is the recovery check, not an automatic retry or silent stateless fallback.
- Archive means reversible hiding from the default list. It is not erasure. Retention/purge is a
  separate governance decision; no delete endpoint or automatic retention policy is introduced.
- Master codes are resolved only when matching active records exist in the same organization.
  Import does not invent supplier/item records, silently update masters, or reject unknown references.
- Re-imports are independent. Hashes describe received bytes but are not deduplication keys.
  Duplicate invoice occurrences and ambiguous/unresolved references remain distinct source evidence.
- Source storage preserves existing Decimal values and physical row occurrences. PostgreSQL
  range/encoding failures return a safe `422` and roll back; no truncation or financial-rule change.
- Financial decisions come from existing analysis outputs. Findings index issued discrepancies;
  the stored snapshot is authoritative. Partial/unreceived PO states are not invoice exceptions.
- Audit and business writes are inseparable transactions, so their implementation is committed
  together rather than briefly exposing unaudited persistence between artificial commit boundaries.

## Persistence architecture

```text
Session + fresh authorization + CSRF/Origin (before multipart body)
  → streamed temporary uploads + SHA-256 / original byte count
  → existing strict loaders (once per source)
  → existing mode-specific engine and report renderer
  → reauthorize and enter one tenant transaction
       source files / validated document headers and line occurrences
       completed run / actual authenticated creator / source links
       indexed findings / immutable exact report snapshot
       immutable completion audit event / server request UUID
  → commit
  → 201 {run, report}; temporary files closed and removed
```

`web/provenance.py` handles safe metadata and physical CSV end-line positions; `persistence/imports.py`
maps already validated domain records without financial decisions. `persistence/findings.py` indexes
the report's issue codes and subjects. `persistence/runs.py` owns scoped create/list/detail/mutation
transactions; `persistence/audit.py` inserts bounded actor evidence without committing independently.

PO, receipt and invoice headers are grouped by the existing loader-consistency rules. Source row
numbers distinguish duplicate occurrences, including multiline CSV records. Nullable master links
and exact PO/line/item links resolve only when source evidence permits it. An invoice occurrence
queue maps each original report row to its persisted line even when duplicate keys repeat.
Failure injection checks that every source/header/line/run/link/finding/snapshot/event rolls back.

Historical detail reads the stored JSONB report, never calls loaders or the engine, and never
recalculates totals in JavaScript. It includes snapshot schema version `1` and the installed
distribution's version (currently `0.1.0`). Financial JSON values remain fixed-point strings.

## API and CRUD contract

| Method/path | Input | Success |
| --- | --- | --- |
| `POST /api/v1/runs/invoice-po` | Multipart `purchase_orders`, `invoices` | `201 {run, report}` |
| `POST /api/v1/runs/invoice-receipt` | Multipart `receipts`, `invoices` | `201 {run, report}` |
| `POST /api/v1/runs/po-receipt` | Multipart `purchase_orders`, `receipts` | `201 {run, report}` |
| `POST /api/v1/runs/three-way` | Multipart all three sources | `201 {run, report}` |
| `GET /api/v1/runs` | Optional `mode`, `archived`, `limit`, `cursor` | `{items, next_cursor}` |
| `GET /api/v1/runs/{run_id}` | Opaque UUID | `{run, report, sources, schema_version, engine_version}` |
| `PATCH /api/v1/runs/{run_id}` | `expected_version`, plus `title` and/or `note` | Updated run metadata |
| `POST /api/v1/runs/{run_id}/archive` | `expected_version` | Updated run metadata |
| `POST /api/v1/runs/{run_id}/restore` | `expected_version` | Updated run metadata |

All nine multipart routes, including `/api/v1/reconcile` and four `/api/v1/analyses/<mode>` routes,
are authenticated before body consumption. Multipart creates reject extra/duplicate fields.
Missing/expired credentials return `401`; denied membership/permission/CSRF returns `403`.
Other-tenant and missing resource IDs both return `404` after authorization. Source validation
and storage data errors return `422`; file limits return `413`; unexpected faults return safe `500`.

Metadata accepts only optional title/note plus required positive strict-integer expected version.
Limits are 120 and 4000 Unicode characters, checked by request models and DB constraints.
Surrounding whitespace is trimmed; empty text becomes null; invalid Unicode/NUL is rejected.
Content is plain text, never HTML. Omitted metadata fields stay unchanged. Metadata updates cannot
change organization, actor, mode, status, evidence, findings, report, or timestamps.

Every successful mutation increments the run version and appends an audit event. The transaction
locks the run row before comparing `expected_version`; a stale editor gets `409` with no change.
Archive/restore uses the same rule. A repeated requested state with a current version is a new
successful audited mutation, not an idempotency contract. No physical rows are deleted.

History defaults to active runs, 25/page; maximum 100. It filters mode and active/archived status
server-side and sorts `created_at DESC, id DESC`. A maximum 256-character base64 cursor contains
an aware timestamp and UUID, strictly decoded and used only as a bound value, never tenant authority.
List items include ID, mode/status, optional title, timestamps, version, creator UUID and authoritative
summary. They omit notes, result rows and provenance; the SQL projects only the snapshot summary.
Detail provides full snapshot and source metadata. Every API response is `Cache-Control: no-store`.

## Provenance and retention

Stored: normalized source records, original source codes and line occurrences, nullable resolved
links, source type, safe display basename (maximum 255 characters), exact original byte count,
streamed SHA-256, timestamps, run creator, report/engine versions, findings, metadata and audit.

Not stored: raw CSV bytes, upload handles, temporary filesystem paths, client-chosen actor/tenant,
session/CSRF tokens in runs, or raw request/report/note bodies in audit metadata. Filenames strip
both path separator styles and control characters; they never choose server paths. Raw input
cleanup is tested on success and failure. Source hashes establish byte identity, not supplier
authenticity. Archive leaves all validated evidence, results and audit intact, including backups.

## Database changes

Migration `0003_persistent_runs_and_audit.py` follows unchanged `0001`/`0002`:

- `analysis_runs`: nullable title, note, archive timestamp, version default 1; title/note length,
  positive-version and archive-after-creation checks.
- Two history indexes: organization/archive/created/id and organization/mode/archive/created/id.
- `audit_events`: 21st table, UUID identity, organization/actor/event/resource/request fields,
  UTC-aware timestamps and JSONB metadata (object, at most 2048 bytes). Event/resource checks,
  composite actor-membership/resource-run foreign keys, resource-history index.
- Audit ENABLE/FORCE RLS with tenant-only policy; runtime SELECT/INSERT, no UPDATE/DELETE/TRUNCATE;
  trigger rejects UPDATE/DELETE, including ordinary privileged row mutation.
- Runtime run UPDATE narrowed to title/note/archive/version. Source evidence, analysis links and
  findings deny runtime UPDATE. Existing snapshot trigger and no-business-DELETE policy remain.
- Identity receives no business/audit grants. Migration owner stays off the HTTP path. No new
  role-management/schema-CREATE permission, SECURITY DEFINER function, or RLS bypass is added.

Clean migration and metadata drift checks pass. A separate Phase 2 → 3 upgrade retains an existing
account, password hash and session and still authenticates after migration. Historical Phase 1
upgrade tests remain active. Downgrade is destructive to new metadata/audit and is not an app action.

## Authorization, audit and request boundaries

| Role | RUN_ANALYSIS | VIEW_RUN_HISTORY | UPDATE_RUN_METADATA | ARCHIVE_RUN (includes restore) |
| --- | --- | --- | --- | --- |
| MEMBER | Yes | Yes | No | No |
| AP_MANAGER | Yes | Yes | Yes | Yes |
| ORG_ADMIN | Yes | Yes | Yes | Yes |

The central permission map, current session/user/organization/membership and live database role
govern each request. The tenant transaction rechecks membership and organization. UI visibility
is convenience only. Organization changes rotate the session and remount history/workspace state.

Audit events: `ANALYSIS_COMPLETED`, `RUN_METADATA_UPDATED`, `RUN_ARCHIVED`, `RUN_RESTORED`.
Actor and organization come from the authenticated principal. Every request gets a server-generated
UUID returned as `X-Request-ID`; browser-supplied IDs cannot choose audit correlation. Completion
metadata contains mode/version; other events contain changed field names and previous/new version,
not source values or note text. Business change plus audit succeeds or fails as one transaction.
Owner/superuser schema control remains trusted; this is not a cryptographically signed ledger.

The pre-body investigation found endpoint dependencies too late for FastAPI multipart parsing.
The new header-only gate rejects all nine protected POST paths before invoking downstream receive.
45 tests cover anonymous, invalid session, expired session, revoked membership and invalid CSRF
against every upload path, asserting zero body reads. Authorized uploads still need proxy total-body,
time and concurrency limits. Run JSON mutations share the existing 16 KiB JSON bound.
Credentialed CORS stays explicit and adds PATCH plus response exposure of X-Request-ID, no wildcard.

## Frontend

The browser uses persistent create only, shows “Saved to history” after successful creation, and
links to the saved run. `/history` offers active/archived and mode filters, loading/empty/error
states, bounded cursor navigation and authoritative summaries. `/history/[runId]` reuses existing
mode-specific report components and displays source filenames, sizes and expandable full hashes.

Managers/admins can edit plain-text metadata, confirm archive, and restore. Conflicts focus an
alert and offer refresh instead of resubmission. The native modal focuses Cancel, supports Escape,
and returns focus to Archive run; real-browser testing found and fixed an initial focus-return bug.
Titles, notes, filenames and report text are escaped by React. Existing money/quantity formatting
is reused, with no client financial recomputation. URLs/types/limits are centralized; no new
frontend runtime dependency or business-specific hardcoded ID, total, file path or credentials.

## Verification evidence

| Check | Result |
| --- | --- |
| Python 3.11.16 | 494 passed, no skips, with PostgreSQL |
| Python 3.12.7 | 494 passed, no skips, with PostgreSQL |
| PostgreSQL 17.11 subset | 202 integration tests included in each full run |
| Added Phase 3 coverage | 109 tests: 93 PostgreSQL, 16 unit primitives |
| Existing auth coverage | 73 database auth tests, 31 auth primitive tests; upgrade regression retained |
| Ruff lint / format | Passed |
| `pip check` | Passed in both full environments and fresh core-only wheel environment |
| Frontend unit tests | 76 passed across 9 files |
| Frontend lint / strict production build | Passed; history routes emitted |
| Locked `npm ci` / `npm audit` | Passed; zero reported vulnerabilities |
| Real-stack Chromium | 28 passed; final rerun exited successfully with test-server cleanup |
| axe accessibility | 18 scans, zero serious/critical violations in passing scenarios |
| Source/wheel build | Passed with isolated setuptools build environment |
| Core-only wheel | Installed with `--no-deps`; no FastAPI/SQLAlchemy installed; import and sample CLI passed |
| Disposable logical backup/restore | Passed: exact snapshot, actor and tenant/identity protections restored |

Database tests cover IDOR, cross-tenant reads/edits/archive/restore, mass assignment, stale user and
membership/organization, role policy, CSRF, concurrent writes, rollback injection, duplicate source
occurrences, unresolved links, repeat imports, audit actor/FKs/tampering, snapshot tampering,
source immutability, original-byte provenance, storage limits and both upgrade paths. Frontend and
E2E cover stored XSS, all four persistent create modes, historic snapshot parity, metadata conflicts,
archive/restore, refresh/login persistence, narrow layouts and keyboard interaction.

Canonical sample, both newly created and reopened from History in real-stack E2E:
15 invoices, 17 lines, 6 matched, 11 review required; disputed amounts EUR `2450.00`,
MAD `10199.00`, USD `75.00`. The fresh dependency-free CLI wheel gives the same canonical totals.

A no-isolation build initially lacked setuptools; the declared isolated build succeeded instead.
Local sandbox restrictions required explicit permission for npm cache access, wheel reads and
PostgreSQL startup. The unrelated root lockfile causes a Next workspace-root warning and is not
deleted to silence it. Starlette emits an upstream AnyIO deprecation warning; npm warns about
the existing ESLint 9 support lifecycle. No new dependency was introduced to hide those warnings.

## Manual browser review

Completed a separate interactive review using browser controls against a disposable
PostgreSQL database and production Next build: synthetic registration/sign-in, three sample uploads,
successful saved result, History listing, browser refresh, reopened original report, title/note edit,
two-tab stale-version rejection and refresh, keyboard archive confirmation, archived-history filter,
restore, sign-out/sign-in, and reopening the restored run. Canonical counts and all three currency
amounts remained correct in both new and historical results. Screenshots were inspected at desktop
and 375-pixel width for history, metadata, conflict and archive UI. Escape returned focus to Archive
run; Enter/Tab completed confirmation; the checked detail had no page-level horizontal overflow.

The second editor and review tab were closed and the temporary viewport override reset.
No real customer data or external mail was used.

## Git handoff

Implementation commits on `main`:

| Commit | Change |
| --- | --- |
| `1da777d` | Record successful Phase 2 remote CI |
| `07b330e` | Persistent authenticated runs, provenance, metadata and atomic audit |
| `24f203b` | PostgreSQL, migration, backup and security regression coverage |
| `d589d63` | Persistent history frontend and browser/unit regressions |

The final documentation commit contains this report, the threat model, recovery runbook and
updated project guides. Code verification corresponds to `d589d63`; the exact ending documentation
commit is recorded in the task handoff. No core engine/loader/CLI or previous migration was changed.
The unrelated root `package-lock.json` remains untracked. Local test servers are no longer running;
interrupted disposable runs may leave ignored test databases for a later scoped administrator review.

## CI and remaining boundaries

The existing CI test discovery covers new database, migration, unit and browser files without
changing its four jobs. Python matrix jobs without a PostgreSQL URL explicitly skip database tests;
the PostgreSQL job supplies it. Optional backup smoke needs compatible client tools and reports
a skip if absent. The authorized Phase 3 push published remote `main` at
`e5c99f62d45a00868d5139b4344e30e4d15f29aa`.
[GitHub Actions run 34535210216](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/34535210216)
(`push`) concluded **success**. All four jobs passed: Python 3.11, Python 3.12,
PostgreSQL and authentication integration, and Frontend and authenticated browser verification.
This remote result supplements the unchanged local verification evidence above.

No issue assignment/resolution lifecycle, due-date/reminder system, AP manager KPI dashboard,
member-management admin UI, inventory, permanent purge/retention engine, MFA/SSO, or production
deployment approval. No cancellation, idempotency key, worker queue or automatic create retry.
Operational encrypted off-host backups, measured recovery objectives, retention decisions,
load testing, proxy limits and incident procedures remain deployment responsibilities.
See [persistent-data threats](threat-model-persistence.md), [backup/restore](backup-restore.md),
and [security roadmap](security-roadmap.md).

Next: **Product Phase 4 — AP exception workflow, assignment, resolution lifecycle, due dates,
comments, and reminders.** Not implemented in this phase.
