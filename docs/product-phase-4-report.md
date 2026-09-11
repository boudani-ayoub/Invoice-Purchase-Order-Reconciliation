# Product Phase 4 — AP exception workflow

## Baseline and scope

Phase 4 starts at `b2a29f0dd853e26fbfad27eb7815e55acf9ecfce` on `main`:
`docs: record product phase 3 CI success`. That small documentation-only commit corrects
stale push/CI statements without rewriting Phase 3's historical local evidence.
The verified remote Phase 3 baseline remains `e5c99f62d45a00868d5139b4344e30e4d15f29aa`,
with all four jobs successful in [Actions run 34535210216](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/34535210216).

This phase adds organization-scoped investigation workflow to existing findings, not a second
financial result model. No deterministic engine, loader, report renderer, authoritative monetary
summary, or previous migration is redesigned. The unrelated untracked root `package-lock.json`
is preserved and excluded. No Phase 4 push is authorized; remote CI has not run this phase.

## Decisions and ambiguities resolved

- Resolution closes an investigation only. It is not payment approval, discrepancy waiver,
  evidence correction, a changed report, or a legal/penalty determination.
- Direct `OPEN → RESOLVED` is supported. `IN_REVIEW → OPEN`, `RESOLVED → IN_REVIEW`, and
  transitions to the current state are rejected. Reopening means `RESOLVED → OPEN`.
- All state edits require a positive strict-integer `expected_version`. An unchanged manager
  patch returns `422` without a new version or event. Comments append independently and do not
  advance the finding version.
- Managers may assign and schedule resolved findings as well as unresolved ones. Resolution
  suppresses derived due flags; reopening retains assignment and schedule, so overdue flags
  can reappear. Assignment, due date and reminder date do not imply one another.
- New assignments require both an active account and active same-organization membership.
  Later inactivity preserves the assigned ID and history. Current detail/list labels mark inactive
  assignments; managers can replace or clear them. No member-management interface is added.
- The queue includes all statuses and archived-run findings by default. Archive is reversible
  History organization, not deletion or investigation closure. Filters apply server-side.
- Date input must be a timezone-aware ISO string. The API normalizes to UTC and rejects values
  outside the supported UTC calendar range. The browser labels schedule inputs explicitly as
  UTC and displays saved dates in the viewer's local timezone. Omission preserves a field;
  explicit null clears it. Unchanged minute-resolution inputs do not truncate saved seconds.
- Comments and resolution notes are retained plain text, trimmed and nonblank, limited to 4000
  Unicode characters. NUL, malformed Unicode, oversized requests and unexpected fields fail.
  The 16 KiB body limit is independent of the character limit, including for multibyte text.
- The timeline uses a separate bounded read endpoint. Current assignment labels are not frozen
  identity snapshots; event actor IDs and previous/new assignment IDs preserve attribution.
- Migration 0004 refuses destructive downgrade. Recovery requires reviewed backup restoration.
  Phase 3 application findings are OPEN; an out-of-band legacy RESOLVED row without resolution
  attribution fails the new validated constraint rather than receiving an invented actor or note.

## Architecture and changed files

```text
Authenticated session + current membership + centralized permission + CSRF/Origin
  → tenant transaction and organization-scoped finding row lock
  → recheck session, organization and live role after lock wait
  → member assignee check + expected_version comparison
  → mutate only permitted workflow columns; advance version
  → append actor/request-aware event(s) in the same transaction
  → commit; browser refreshes current workflow and bounded history

Persisted source evidence → existing Finding identity → immutable ResultSnapshot
                                  │
                                  └→ assignment/status/schedule + finding_events
```

| Area | Files and responsibility |
| --- | --- |
| State and migration | `persistence/models.py`, `workflow_policy.py`, `workflow_events.py`, `migrations/versions/0004_finding_workflow.py`, migration metadata registration |
| Service and API | `persistence/workflow.py` scopes queries, locks and writes; `web/workflow.py` validates explicit contracts; central paths, body limit, permission map and startup role checks extended |
| Browser | `/work`, `/work/[findingId]`; queue, assignee picker, controls, detail and timeline components; typed API contracts and centralized labels/limits |
| Integration | Protected navigation gains Work; History links to findings separately from the stored report; existing resource/auth/transport helpers reused |
| Verification | Four Python workflow test files, two frontend unit files and shared fixtures, four real Chromium scenarios; disposable test-only membership seeder |
| Tooling | ESLint ignores generated coverage and Playwright artifacts, without suppressing source checks |
| Documentation | README, SECURITY, data model, database/deployment guides, roadmap, this report and the workflow threat model |

No new runtime dependency, configurable credential, public seed endpoint, hardcoded tenant/user ID,
production account, or client-side financial calculation is introduced. Fixed identifiers and
canonical amounts in tests are synthetic fixtures/assertions, not application defaults. Migration
constants are frozen schema history; application policy and UI copy/limits are centralized.

## State machine and permissions

| From | To | Event | Required data |
| --- | --- | --- | --- |
| OPEN | IN_REVIEW | STATUS_CHANGED | Expected version |
| OPEN or IN_REVIEW | RESOLVED | RESOLVED | Expected version and nonblank resolution note |
| RESOLVED | OPEN | REOPENED | Expected version |

The server supplies `resolved_at` and `resolved_by_user_id`. Reopen clears current resolution
fields but keeps the historical RESOLVED event, message, actor and server timestamp. No request
can choose organization, actor, request ID, finding identity, resolution timestamp or new version.

| Capability | MEMBER | AP_MANAGER | ORG_ADMIN |
| --- | --- | --- | --- |
| View queue, finding, history and narrow picker | Same organization | Same organization | Same organization |
| Append a comment | Same organization | Same organization | Same organization |
| Start review, resolve, reopen | Currently assigned to self, checked under lock | Any finding in organization | Any finding in organization |
| Assign/reassign/unassign; edit due/reminder | Denied | Any finding in organization | Any finding in organization |
| Edit/delete comments or events | Denied | Denied | Denied |

Frontend hiding is UX only. Direct API calls enforce permissions. Existing analysis/run permissions
are unchanged. Reads use fresh authorization; state writes reauthenticate after lock waits to
catch intervening session, organization or role changes.

## Endpoint contract

All paths below start with `/api/v1`. Errors remain safe, bounded and do not echo private text.

| Method/path | Input | Response / access |
| --- | --- | --- |
| GET `/findings` | `run_id`, `status`, `assignee=me/unassigned/UUID`, `overdue`, `reminder_due`, `limit`, `cursor` | `{items, next_cursor, server_now}`; workflow viewers |
| GET `/findings/{id}` | Finding UUID | `{finding, server_now}` with source context and current resolution |
| GET `/findings/{id}/events` | `limit`, `cursor` | `{items, next_cursor}`; scoped append-only timeline |
| PATCH `/findings/{id}` | `expected_version`, one or more of `assignee_user_id`, `due_at`, `reminder_at` | Updated state; manager/admin only |
| POST `/findings/{id}/transition` | `expected_version`, `target_status`, `resolution_note` only for resolution | Updated state; self-assigned member or manager/admin |
| POST `/findings/{id}/comments` | `text` only | `201` event; workflow commenters |
| GET `/workflow/assignees` | `limit`, UUID `cursor` | `{items, next_cursor}`, each item only `user_id`, `display_name`, `role` |

Queue/history pages default to 25 and cap at 100. Queue orders by `created_at DESC, id DESC`;
event pages use the same ordering within a finding. Cursors reuse bounded Phase 3 timestamp/UUID
encoding. Picker pages order by user UUID and expose only active same-org account memberships.
The explicit UUID assignment filter permits current or historical same-org membership, not a
cross-tenant directory lookup. No estimated totals or monetary aggregates are returned.

Invalid/expired sessions return `401`; denied membership, permission or CSRF returns `403`;
foreign/missing finding, run-filter and assignee targets return indistinguishable `404` after
authorization. Bad cursors return `400`, stale state `409`, oversized bodies `413`, invalid fields,
no-op patches and unsupported transitions `422`. Every POST/PATCH uses trusted Origin and the
existing session-bound CSRF mechanism. Schemas forbid extra fields.

## Database, RLS and event design

Migration `0004`, after `0003`, adds IN_REVIEW to the existing check-backed status and extends
findings with nullable assignee, due/reminder, resolver/time/note fields plus version default 1.
Positive version, complete-or-absent resolution, bounded note, and composite same-organization
assignee/resolver membership constraints are enforced. Existing OPEN findings retain their old
columns unchanged, begin at version 1 and receive null workflow fields and no invented history.

The new `finding_events` table makes 22 application tables. Each event has tenant/finding/actor/
request UUIDs, server timestamps, event type, optional business message and object JSONB metadata
bounded to 2048 bytes of PostgreSQL text representation. Types are COMMENT_ADDED,
ASSIGNEE_CHANGED, DUE_DATE_CHANGED, REMINDER_CHANGED, STATUS_CHANGED, RESOLVED and REOPENED.
Only comments and resolution events have messages. State events retain previous/new values and
versions; a multi-field patch produces one event per changed field, sharing its request, timestamp
and new finding version. Metadata contains no uploaded financial rows or copied comment text.

- `finding_events`: ENABLE/FORCE RLS, verified transaction-local organization policy, runtime
  SELECT/INSERT only. Composite finding/actor FKs prevent tenant mismatches. An UPDATE/DELETE
  trigger also rejects ordinary privileged row edits, following the existing audit pattern.
- `findings`: UPDATE granted only on status, assignee, due/reminder, resolution fields and version.
  Organization, run, issue/category and source identities remain outside the update grant.
- Source tables, snapshots, old audit rows, existing policies and identity grants remain unchanged.
  Runtime still cannot read account/credential/session tables. Identity still cannot read findings,
  reports or events; startup checks now include the new event table.
- The narrow identity query binds the verified organization and projects only necessary fields.
  Current assignee labels are bounded by IDs from the already tenant-scoped result page. No
  email-based assignment, broad user endpoint, runtime-to-identity role switch or grant widening.
- New queue/status/assignee/due, reminder, creation-order and event-history indexes complement
  the existing organization/run/status index.

State changes and events commit together. Real concurrent connections demonstrate one winner
and one `409`; injected event failures roll back assignment/schedule, transition or comment writes.
Source rows and snapshot JSON/text remain unchanged through assignment, comments, resolution,
reopen and archive. The workflow service never reruns the financial engine.

## Dates and browser behavior

`overdue = unresolved AND due_at IS NOT NULL AND due_at < server_now`.
`reminder_due = unresolved AND reminder_at IS NOT NULL AND reminder_at <= server_now`.
Flags are derived, never stored. The timestamp returned with a detail is the exact clock sample
used for its flags. Past dates are valid. Refresh explicitly reevaluates time; nothing is delivered
while the browser/app is closed. There is no worker, queue, email, push notification or cron.

The work queue has operational filters, source references, current assignment/status, schedule
and links back to immutable reports. Detail identifies unresolved source/master links explicitly.
The append-only timeline is independently paginated and retains resolution messages after reopen.
Stored member, run, source, comment and resolution text is rendered as React text, never HTML.

Mutations are never automatically retried. Conflict, lost-response and stale-access paths explain
the problem and require refresh; ambiguous responses instruct checking both finding and timeline
before retrying. Comments have no idempotency key, so deliberate resubmission may duplicate one.
Keyboard controls, focused conflict messages, explicit select labels and narrow-screen layouts
are covered. Overdue text uses the existing high-contrast foreground token.

## Verification

Final source verification completed locally on September 12, 2026, on Windows with real
PostgreSQL 17.11 and Node 24.19.0. The two Python full-suite runs had no skips. Counts include
parameterized cases, not just test functions.

| Check | Result |
| --- | --- |
| Python 3.11.16 | 631 passed, 1 dependency deprecation warning; 131.35 seconds |
| Python 3.12.7 | 631 passed, same warning; 210.62 seconds |
| PostgreSQL 17.11 | 308 database-marked cases included in each full run; no SQLite substitute |
| New Phase 4 Python coverage | 137 tests: 106 database cases and 31 input/model cases |
| Frontend unit | 111 passed across 11 files, including 35 new workflow tests |
| Frontend lint | Passed, including after browser artifact generation |
| Production Next.js build | Passed, including `/work` and `/work/[findingId]` |
| Real Chromium | 32 passed, no retries, 2.7 minutes; 4 new workflow scenarios |
| Axe | 25 scans: zero serious/critical violations in tested states; 7 new workflow scans |
| Dependency install/audit | Fresh `npm ci` passed; final `npm audit`: 0 vulnerabilities |
| Python dependency checks | `pip check` passed in both full environments |
| Ruff | Lint passed; 118 Python files already formatted |
| Package build | Source distribution and wheel built successfully in isolated build environments |
| Core-only wheel | Fresh `--no-deps` install, isolated import, CLI help/sample and `pip check` passed; FastAPI/SQLAlchemy absent |
| Git whitespace | `git diff --check` passed |

Migration verification covers clean database → head, `0001 → head`, `0002 → head` and
`0003 → 0004`, plus Alembic metadata drift checks. The Phase 3 upgrade test fingerprints all old
columns/rows across all 21 prior tables, including real credentials, sessions, run/source links,
finding, snapshot and audit fixtures, and compares them after migration. The existing session
still authenticates; the old finding is OPEN/version 1 with null workflow fields and no events.
No new upgrade operations were detected. The preexisting disposable logical-backup/restore
regression also passes; this is not production backup verification.

The full suite retains all four persisted analysis modes, stateless API compatibility, authentication,
canonical source/report semantics and history/archive regressions. Browser and core tests retain
authoritative canonical disputed totals as strings: EUR `2450.00`, MAD `10199.00`, USD `75.00`.
Workflow API responses do not invent or aggregate financial amounts.

New tests cover active/inactive/foreign assignment, read-only directory scope/pagination, all three
roles and member self-scope, every allowed transition and invalid transitions, version conflict,
real concurrent writers, resolution history after reopen, persistent Unicode/XSS comments,
deterministic due/reminder boundaries and a single clock sample per detail, archive retention,
cross-tenant reads/writes/events, stale account/session/membership/organization, organization
switch and post-lock role change, request-supplied actor rejection, CSRF/Origin/body limits,
composite FKs, RLS missing context, denied grants/event mutation, rollback and private-log checks.

Frontend verification covers queue filters/pages, manager assignment and schedule, member controls
and direct unauthorized API calls, comment/start-review/resolve/reopen, stale-editor refresh,
tenant denial, History navigation, login/reload persistence and stored markup as text. Desktop
queue and full 375px finding-detail screenshots were visually reviewed; narrow-screen overflow
and keyboard activation are also checked in Chromium. Generated screenshots/reports remain
ignored local artifacts, not committed business data.

### Findings corrected during verification

- Explicit labels separate select names from option text for browser/assistive lookup.
- Overdue text no longer uses a color with 4.43:1 contrast on the page background; it uses the
  existing high-contrast foreground token, and the final axe scans pass.
- Detail's due flags and returned `server_now` now use one sample, including across a delayed
  member-label query; a regression test exercises this boundary.
- ESLint now excludes generated coverage/Playwright files. Source lint remains enabled.
- Initial PostgreSQL checks after a stopped local server and a Windows shared-temp ACL failure
  were environment failures. Final runs use the restarted local server and fresh project-local
  pytest temporary directories; neither condition is concealed as a skipped test.

### Known warnings

Both Python versions report the existing Starlette use of deprecated
`anyio.abc.BlockingPortal`. The dependency install reports ESLint 9's support deprecation.
Next.js warns that the unrelated root lockfile affects workspace-root inference; it is intentionally
preserved rather than removed. Playwright reports NO_COLOR/FORCE_COLOR precedence. These warnings
did not fail final verification. They do not establish that public deployment is safe.
The fresh wheel environment also displayed a pip-update availability notice; no dependency change
was made just to suppress it.

## Local commits and handoff

Backend state, its event transaction and API are committed together to avoid an intermediate
unauthorized or unaudited workflow implementation. Tests, browser integration and documentation
remain separately reviewable. The final documentation commit's SHA is reported in the completion
handoff to avoid a self-referential SHA in its contents.
There is no Phase 4 remote CI result because this phase has not been pushed.

| Commit | Purpose |
| --- | --- |
| `b2a29f0dd853e26fbfad27eb7815e55acf9ecfce` | Correct Phase 3 CI documentation; exact Phase 4 baseline |
| `29e4361774d49845e1379753f22976f9ec26c82c` | Organization-scoped finding state, API, migration and atomic event history |
| `8c0f40ec51dd5b88365e4ae3161cd30228b3615e` | Workflow tenant, authorization, concurrency and upgrade tests |
| `53061a81309907b1f06cb8c506a70e9e230ffaba` | AP work queue/detail, controls, browser verification and disposable membership setup |

The concluding commit is `docs: record product phase 4 architecture`. Across Phase 4, the change
covers 46 files: 12 backend/migration, 4 backend-test, 21 frontend/test-tooling, and 9 documentation
files. The final handoff records its exact HEAD and working-tree status; the unrelated root lockfile
remains untracked and outside these commits.

## Security review and residual risks

The pre-commit review inspected IDOR, forced RLS, assignment injection, stale membership and
organization switching, member escalation, mass assignment, CSRF, stored XSS, cursor/SQL input,
concurrent writes, event immutability, rollback, application-log leakage, cross-tenant assignee
enumeration, grants and identity/runtime separation. Tests exercise the negative paths rather
than relying on hidden UI controls. See [the threat matrix](threat-model-workflow.md) for the
control and residual boundary of each threat.

Remaining deployment/governance concerns: in-flight revocation after the last authorization
check; administrators able to alter DDL; a compromised runtime process able to choose its tenant
context; DB/proxy/backups/browser traces retaining private text; no per-tenant mutation quotas,
retention/purge, comment idempotency, outbound reminder delivery or measured large-tenant query
budgets. Backup/restore, TLS, logging and role drift require deployed verification. This is not a
production-readiness claim or a tamper-proof ledger.

Phase 4 is the stopping point. Phase 5 AP Manager Dashboard and measured KPIs are next, not
implemented. No charts, dashboard aggregates, supplier scores, penalties/legal calculations,
member/role administration, inventory/stock, purge/retention engine, MFA/SSO, Redis/Celery/queues,
email/push reminders, payment approvals, accounting integration or ERP integration is included.
