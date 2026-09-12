# Dashboard metric contract

Product Phase 5 is a read model of saved finding state and append-only workflow activity.
It is not an accounting ledger, a payment decision, or a cross-run exposure report.

## Scope and time

Every dashboard query uses the current authenticated organization's UUID, checked through
`VIEW_MANAGER_DASHBOARD`, explicit SQL predicates, and forced tenant RLS. Browser filters cannot
select another tenant. All findings in that organization are included, including findings from
archived runs. Repeated analyses create separate findings; these are case counts, not distinct
invoices or distinct underlying business discrepancies.

`window` accepts only `7d`, `30d`, or `90d`, default `30d`. These mean N UTC calendar days including
the current partial day, not N rolling 24-hour intervals:

```text
period.end   = server_now
period.start = midnight_UTC(server_now) - (N - 1) calendar days
activity    = timestamps >= period.start AND timestamps < period.end
```

Each endpoint samples the server clock once for its metric calculations after authorization.
Every due/reminder comparison, age, period, and returned `server_now` in that response uses that
sample. Authentication keeps its existing clock checks. Current-state counts have no creation-time
filter: they represent the database statement's current state, not reconstructed historical state.
Concurrent commits just after the clock sample can therefore be reflected in current counts.

Each endpoint uses one aggregate SQL statement. Overview's state/activity share that statement's
snapshot; workload's Unassigned and assigned page do too. Separate endpoint calls are not one
global transaction. Labels are a subsequent bounded identity read and can change concurrently.
The UI exposes check times and the independent-read caveat. Refresh requests fresh data; no metric
cache, polling worker, or materialized table exists.

Daily trend buckets start at UTC midnight. There are exactly N ascending rows, zero-filled after
SQL grouping; the final bucket ends at `server_now`, not tomorrow. At exact midnight the final
bucket is empty. At noon UTC on 2026-09-12, `7d` starts 2026-09-06T00:00:00Z and ends
2026-09-12T12:00:00Z. Browser-local timestamp formatting does not change UTC chart/table dates.

## KPI semantics

All counts are integers. `U` below means `status IN ('OPEN', 'IN_REVIEW')`. All rows are scoped to
the verified organization, including archived-run findings. No percentages are implemented;
denominator is **not applicable** for every metric below. Empty counts return `0`, never a rate.

| Metric / API field | Source and calculation (numerator) | Time scope | Empty/null behavior and interpretation |
| --- | --- | --- | --- |
| Open / `backlog.open` | COUNT Finding where status = OPEN | Current, no window filter | 0; not all unresolved |
| In review / `backlog.in_review` | COUNT Finding where status = IN_REVIEW | Current | 0; unresolved subset |
| Unresolved / `backlog.unresolved` | COUNT Finding where U | Current | 0; OPEN + IN_REVIEW |
| Currently resolved / `backlog.resolved` | COUNT Finding where status = RESOLVED | Current | 0; not historical resolution actions |
| Unassigned / `backlog.unassigned_unresolved` | COUNT Finding where U and assignee_user_id IS NULL | Current | 0; inactive assignments are not unassigned |
| Overdue / `backlog.overdue` | COUNT Finding where U and due_at < server_now | Current | Null due_at excluded; equality not overdue |
| Reminder due / `backlog.reminder_due` | COUNT Finding where U and reminder_at <= server_now | Current | Null reminder_at excluded; equality included; in-app only |
| New findings / `activity.new_findings` | COUNT Finding with created_at in the period | Half-open activity window | 0; counts finding creation, irrespective of current status |
| Resolution actions / `activity.resolution_events` | COUNT FindingEvent of type RESOLVED, created_at in period | Half-open activity window | 0; repeated resolutions count again; never derived from resolved_at |
| Reopen actions / `activity.reopen_events` | COUNT FindingEvent of type REOPENED, created_at in period | Half-open activity window | 0; does not imply the finding remains open |
| Median age / `age.median_unresolved_age_seconds` | PostgreSQL percentile_cont(0.5) over epoch(server_now − Finding.created_at), filtered by U | Current unresolved cohort | null when none; even-sized median interpolates the two middle ages |
| Oldest age / `age.oldest_unresolved_age_seconds` | MAX epoch(server_now − Finding.created_at), filtered by U | Current unresolved cohort | null when none; elapsed age since creation, including time spent resolved |
| Daily new findings / `trends.items[].new_findings` | Same creation count grouped by UTC date | Daily intersected with period | Missing bucket = 0; no browser rebucketing |
| Daily resolution actions / `trends.items[].resolution_events` | Same RESOLVED event count grouped by UTC date | Daily intersected with period | Missing bucket = 0; actions, not unique cases |
| Daily reopen actions / `trends.items[].reopen_events` | Same REOPENED event count grouped by UTC date | Daily intersected with period | Missing bucket = 0 |
| Issue mix / `issues.items[].count` | COUNT Finding where U, GROUP BY code, category | Current | Empty array if none; descending count then code/category; not an error rate |
| Workload open / `open` | COUNT U findings for the assignee with status OPEN | Current | 0 within a returned row |
| Workload in review / `in_review` | COUNT U findings for the assignee with status IN_REVIEW | Current | 0 within a returned row |
| Workload unresolved / `unresolved` | COUNT U findings grouped by assignee_user_id | Current | Only nonempty assigned groups; Unassigned always returned, including zero |
| Workload overdue / `overdue` | COUNT U findings for that assignee with due_at < server_now | Current | Null/equal due time excluded; resolved findings excluded |

Age values are seconds in the API, not financial values. PostgreSQL computes them; the browser
only formats days to one decimal and displays positive ages below 0.1 days as `< 0.1 days`.
Negative ages from clock skew are retained rather than silently clamped; the UI says
“Clock discrepancy.” Empty age is “No unresolved findings.” Reopening never resets creation age.
First-resolution time, cycle time, success rates, overdue percentages, and supplier scores are absent.

Current resolution and period actions intentionally differ. A finding resolved, reopened, then
resolved again in one period contributes two resolution actions and one reopen action, but just
one currently resolved finding. Older resolutions need not have events predating Phase 4; the
dashboard reports only retained events and does not fabricate history.

## API and authorization

| GET endpoint | Accepted query | Response bounds |
| --- | --- | --- |
| `/api/v1/dashboard/overview` | `window` | One object: server_now, period, backlog, activity, age |
| `/api/v1/dashboard/trends` | `window` | server_now, period, exactly 7/30/90 daily items |
| `/api/v1/dashboard/issues` | None | server_now, nonempty groups from finite domain code/category enums |
| `/api/v1/dashboard/workload` | `limit` (default 25, 1–100), optional UUID `cursor` | server_now, unassigned object, up to limit assigned items, next_cursor or null |
| `/api/v1/runs?archived=false&limit=5` (existing History API) | Existing History query contract | Five or fewer independently summarized runs |

Workload orders assigned UUIDs ascending, requests limit + 1 grouped rows, and returns the last
visible UUID as the cursor if more exist. The cursor is a position, not a membership lookup; unknown
UUIDs simply position the current tenant's page. Unassigned is outside pagination and repeated on
every page; do not add it repeatedly when processing pages. Concurrent reassignment can change page
contents. Historical inactive assignments remain with display_name/role and active=false; active
requires both an active user and active membership. Missing labels use nulls and a UUID fallback.
No emails, credential/session data, comment/resolution bodies, or internal run notes are returned.

| Role | Dashboard API / `/dashboard` navigation | Existing History API |
| --- | --- | --- |
| MEMBER | 403 / hidden; direct page explains required access | Allowed, unchanged |
| AP_MANAGER | Allowed | Allowed |
| ORG_ADMIN | Allowed | Allowed |

Anonymous, revoked, expired or inactive-user sessions return 401. Inactive organization/membership
or insufficient role returns 403. Valid scalar query parameters cannot add organization/run IDs:
unknown query keys and unsupported windows return 422. Existing query parsing uses the last value
for repeated scalar keys; this cannot widen the enum/range/tenant constraints. Only GET is added.
Reads do not require mutation CSRF. Credentialed explicit-origin CORS, no-store, no-referrer,
request correlation and redacted errors are inherited. Normal authentication session activity may
be refreshed; dashboard reads never mutate business rows.

## Recent analyses and money

The frontend reuses the History list, sorted by created_at/id descending, for five non-archived
completed runs. Its saved timestamp is also completion time under the current synchronous
`Runs.create` contract (`created_at == completed_at`). This is not an independently measured
processing duration. A future asynchronous/imported-run design would need an explicit completion
field in History. Recent runs are independent of the activity window.

Each row uses only its own stored `ResultSnapshot.report.summary`. Invoice/PO and three-way runs
show potential disputed amounts; invoice/receipt shows potential unsupported invoice amounts;
PO/receipt shows outstanding ordered and over-received reference values. These meanings are not
interchangeable. Exact decimal strings are formatted without converting money to JavaScript Number.
The canonical three-way summary remains EUR `2450.00`, MAD `10199.00`, USD `75.00` **per run**.

No finding monetary fields, resolved/unresolved monetary split, sum across runs, exchange-rate
conversion, money saved/recovered, ROI, forecast, or organization-wide business-exposure total is
computed. Runs may repeat or overlap source documents; a valid cross-run financial total would
require a separately approved business-identity/deduplication design.

## Query design and cost

- Overview: one statement joins two one-row SQL aggregates; current Finding counts/ages and
  filtered FindingEvent activity cannot multiply one another.
- Trends: two date-grouped aggregates UNION ALL, followed by grouped sums; Python fills at most
  90 dates, never loads event histories or finding bodies.
- Issues: one grouped SQL statement over current unresolved findings.
- Workload: one statement combines Unassigned and a keyset page of assigned groups, then at most
  one identity SELECT for that page's IDs, constrained again by verified organization. The existing
  workflow label helper is shared; its old public projection is unchanged.

Existing indexes cover Finding organization/status/assignee/due, reminders, chronology and run/status.
The Phase 4 event-history index is organization/finding/created/id: it supports one finding's timeline,
but not organization-wide event-type/time filtering. Migration `0005` adds only
`ix_finding_events_activity (organization_id, event_type, created_at)`. No columns, tables, policies,
triggers, or grants change. Its reverse migration removes only this index; never downgrade beyond
0004 to erase history. Standard CREATE INDEX can block writes while building; schedule maintenance
and use deployment-specific lock/statement timeouts with the migration owner, not an HTTP role.

On PostgreSQL 17.11, a disposable 20,000-event fixture (19,900 comments and 100 reopens across 365
dates) gave these warm/local observations for actual SQL under the restricted runtime group and RLS:

| Query | Without new index: ms / buffers hit | With index: ms / buffers hit / read |
| --- | --- | --- |
| Overview | 2.147 / 448 | 0.171 / 12 / 2 |
| Trends | 2.701 / 430 | 0.132 / 4 / 0 |

Both plans returned identical aggregate row counts (1 overview, 30 trend dates). The indexed event
branch used an index-only scan, with heap visibility checks still possible. This is a query-shape
check, not a latency SLA or concurrency benchmark. The test rolls back synthetic inserts and its
index comparison. Exact plans/times depend on tenant distribution, visibility maps, statistics and
cache state; no production response-time promise follows.

Current-state aggregates still scale with tenant finding count; exact median may sort a large
unresolved cohort, and workload GROUP BY is not bounded in total database work just because its
output is paginated. Global snapshots, per-tenant quotas, rate/concurrency budgets, query timeouts,
and large-tenant load tests remain deployment work. No cache, queue, or analytics infrastructure is
introduced to hide these limits.
