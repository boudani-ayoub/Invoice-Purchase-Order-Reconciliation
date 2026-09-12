# Product Phase 5 — AP manager dashboard

## Outcome and scope

Adds a manager-only `/dashboard` and four tenant-scoped read endpoints over saved Finding state
and immutable FindingEvent activity. The UI shows four headline counts, period activity with a
daily chart/table, current issue mix, paginated assignee workload, unresolved age, and five recent
History summaries. Each recent run retains its own monetary values. Nothing adds money across runs.

The existing reconciliation engine, Decimal policy, source evidence, snapshots, workflow state
machine, event writes, session design, RLS policies and database role grants are unchanged.
The only database change is migration `0005`, adding one event activity index. No dashboard tables,
new dependencies, background jobs, new accounts, hosting changes or public environment secrets.

## Starting point and reasoning

- Original verified remote Phase 4 HEAD: `875ea7792ea59282752b560a842b4aa0ae99f809`.
- Phase 4 CI: [push run 34648366678](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/34648366678),
  all four jobs successful on that SHA: Python 3.11, Python 3.12, PostgreSQL/auth, frontend/browser.
- Documentation correction: `95ac891e83ef6dc0bb48f191170f2cc68d4fa346`
  (`docs: record product phase 4 CI success`). Historical local Phase 4 results were preserved.
- Exact Phase 5 implementation baseline: `95ac891e83ef6dc0bb48f191170f2cc68d4fa346`.
- Existing unrelated root `package-lock.json` remains unchanged and untracked. SHA256:
  `DAA0308A5EB8C96651E80918807B4EC840C32FA960BC4308AC915136161868AE`.

The prompt's open choices were resolved before implementation:

1. Use N UTC calendar days including today's partial day, not rolling N×24 hours. Only 7/30/90,
   default 30; half-open `[midnight(today) − (N−1) days, server_now)`.
2. Current counts include archived-run findings and are not filtered by the activity window.
   Activity comes from Finding.created_at and event timestamps, never current resolved_at.
3. Count resolution/reopen actions, including repeats. Do not invent unique-success percentages,
   first-resolution duration, or money recovered.
4. Keep one aggregate SQL statement per endpoint; make the independent-request snapshot caveat
   visible. Capture one metric clock sample per response, including workload's delayed label read.
5. Reuse History with limit 5 rather than adding another run endpoint. Current synchronous saves
   set created_at and completed_at identically; show that saved completion timestamp, not duration.
6. Keep inactive assignments, a separate Unassigned object on every page, and bounded identity
   labels through the existing identity engine. Share the Phase 4 helper without changing its
   existing response projection or runtime privileges.
7. Measure event queries before introducing an index. Add only the demonstrated type/time index;
   retain all existing queue/timeline indexes. Standard index-build locking is a deployment concern.

## Implementation map

| Area | Changes |
| --- | --- |
| Authorization/API | Central VIEW_MANAGER_DASHBOARD; typed bounded query models; four GET routes; existing safe errors, session rechecks and no-store middleware |
| Persistence | SQL aggregates, UTC window policy, shared bounded member labels; no business writes |
| Database | 0005 adds ix_finding_events_activity on organization_id/event_type/created_at; metadata matches |
| UI | Manager navigation and protected page; current counters, readable chart plus keyboard table, issue/workload tables, age empty states and exact per-run summaries |
| Regression tests | Four Python test files plus dashboard API/component/browser tests and History limit regression |
| Documentation | This report, metric contract and dashboard threat review; README, SECURITY, data model, roadmap, DB development, deployment and workflow threat links updated |

Endpoint and role matrices, the complete KPI table (source/calculation, cohort/window, null and
denominator semantics), financial exclusions and performance evidence are in
[dashboard-metrics.md](dashboard-metrics.md). All dashboard endpoints require AP_MANAGER or
ORG_ADMIN; MEMBER receives 403. Existing History permission stays unchanged.

## Verification

Final checks use real PostgreSQL 17.11, Python 3.11.16/3.12.7, Node 24.19.0 and a Next 16.3.4
production build. Tests own randomly named disposable databases and restricted owner/runtime/identity
logins. No SQLite, production dataset or deployed customer account is substituted.

| Check | Result |
| --- | --- |
| Python 3.11 complete suite | 689 passed in 231.44s; no skips; one existing AnyIO/Starlette deprecation warning |
| Python 3.12 complete suite | 689 passed in 154.19s; no skips; same existing deprecation warning |
| PostgreSQL cases within each complete suite | 357 database tests; clean/0004→head upgrades, rollback/re-upgrade, metadata parity, row/grant/policy preservation and backup/restore |
| New Python coverage | 58 tests: 49 database and 9 UTC policy cases |
| Frontend unit suite | 129 tests across 13 files |
| ESLint | Passed |
| Next production build | Passed, including /dashboard |
| Chromium complete suite | 35 passed, no retries (3 new dashboard scenarios) |
| axe checks | 30 scans across tested states, zero serious/critical violations (5 new dashboard scans) |
| npm audit --audit-level=moderate | 0 vulnerabilities |
| Ruff lint / format check | Passed |
| pip check, Python 3.11 and 3.12 | No broken requirements |

Backend coverage includes all roles, revoked/expired sessions and post-login user/org/membership/role
changes, two populated tenants and switching, exact due/reminder boundaries, half-open activity
boundaries, repeated resolution/reopen actions, archived findings, inactive users/memberships,
odd/even/null ages and clock skew, no runs, matched runs without findings, empty/unassigned workload,
cursor pagination and narrow query validation. RLS checks exercise missing/wrong context; an actual
query-count test verifies one workload aggregate and one label lookup. Read checks compare all tenant
rows before/after and prohibit reanalysis or private text/monetary payload additions.

Migration verification seeds real saved source/report rows plus comments and resolution, then compares
every model table, columns, policies and grants across 0004→head. It checks the index, role separation,
Alembic drift, downgrade to 0004 and re-upgrade without changing rows. Earlier 0001/0002/0003 upgrades,
immutable evidence/event boundaries, canonical financial strings and account-free CLI checks remain
in the full regression suite.

The actual overview/trend query plans were compared on 20,000 synthetic events under the runtime
group with tenant RLS. New index use reduced observed buffer work from 448 to 14 (overview) and
430 to 4 (trends). See the metric contract for measured timings and limitations. This is not a
high-concurrency or large-enterprise load test; workload grouping and exact median remain
proportional to tenant size. No performance SLA is claimed.

Browser checks exercise real saved runs, assignment/dates, repeated resolution/reopen, archive plus
retained backlog, exact currency strings on repeated runs without a total, manager/member API and UI
access, organization switching, logout, three UTC windows, keyboard details/table access and 375px
overflow checks. Desktop and full mobile screenshots were visually reviewed. Screenshots, traces,
test databases and generated reports are local ignored artifacts, not committed business data.

### Corrections during review

- The two-user isolation fixture now clears the incoming cookie before the second login; login
  correctly revokes an incoming session, so reusing it was a test error, not dashboard leakage.
- The table unit test selects the exact disclosure label, not both that label and the chart's
  accessible description.
- Chart date/count labels use a readable narrow-screen size; desktop chart width is restrained.
- Small positive age is displayed as `< 0.1 days`, not an apparent exact zero. Negative clock skew
  remains explicit rather than silently clamped.

## Security review, warnings and limits

Reviewed count/label IDOR, stale authorization, scope changes, enum/UUID/filter injection, read
projections, stored markup, financial double-counting, grouped query bounds, identity/runtime
separation and index-only migration impact. Details and evidence are in
[threat-model-dashboard.md](threat-model-dashboard.md).

Existing warnings remain: Starlette references the deprecated AnyIO BlockingPortal alias; Next
infers workspace root from the unrelated root lockfile; Playwright warns about NO_COLOR/FORCE_COLOR
precedence. None failed the final checks. The lockfile was not removed or staged to silence Next.

Residual risks: independently read dashboard panels/labels are not a global snapshot; a role change
after the final check cannot retract an in-flight response; a compromised runtime process can choose
its SQL tenant context; deployed logs/backups/traces need protection; tenant quotas/concurrency and
large-data median costs remain unmeasured; standard index creation can block writes. Public release
still requires operational TLS, grants, backup recovery, logging and resource-budget verification.

## Local handoff

Commits are split into backend/index, database tests, interface/browser tests and documentation,
following the initial Phase 4 CI correction. The concluding documentation commit's SHA is reported
in the completion message rather than embedded self-referentially in its own contents.

| Commit | Purpose |
| --- | --- |
| `95ac891e83ef6dc0bb48f191170f2cc68d4fa346` | Phase 4 CI correction; exact Phase 5 implementation baseline |
| `4a36758702eb1f95f1eed4b5504d032119b8e440` | Tenant-scoped metrics, shared labels and index-only migration |
| `47b028d4123cd5f8359b05887e44b65e34587791` | Metrics, authorization, RLS, query and upgrade regressions |
| `e813a969e8a761828e051d3e48e1c08cdaf59a1e` | Dashboard interface, History reuse and frontend/browser checks |

The concluding commit is `docs: record product phase 5 architecture`. Phase 5 changes 41 files
relative to its implementation baseline: 10 backend/migration, 4 Python tests, 17 frontend and
10 documentation files. The working tree is handed off with no tracked changes and only the
pre-existing untracked root lockfile. Phase 5 has local verification, not a newly pushed CI run.

No push was performed. Phase 5 is the stopping point. No Phase 6+ administration, inventory,
supplier intelligence, payment approval, purge/retention engine, legal/penalty calculations,
MFA/SSO, Redis/Celery/queue, outbound reminder, ERP/accounting integration, forecast, AI insight,
organization-wide financial total or recovery/ROI metric was implemented.
