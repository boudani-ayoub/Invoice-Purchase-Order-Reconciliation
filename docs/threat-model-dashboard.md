# Manager dashboard threat review

The protected assets are organization-level counts and activity, assignment labels, and retained
per-run summaries. Aggregates can leak tenant information even without exposing row details.
This review supplements the [workflow threat model](threat-model-workflow.md); it is not an ASVS
certification, tamper-proof ledger claim, or public-production approval.

| Threat | Control and evidence | Remaining boundary |
| --- | --- | --- |
| Count/activity/label IDOR | Fresh VIEW_MANAGER_DASHBOARD authorization; explicit tenant predicates; forced RLS; populated two-tenant, org-switch and missing/wrong-context tests | A compromised runtime process can set its tenant context; application authorization remains essential |
| Old session retains manager role | Existing live user/org/membership/role checks reused; tests change each after login, plus expiry/revocation | Revocation after the last check cannot retract an already in-flight response |
| MEMBER discovers dashboard via URL | Backend 403 on all four endpoints; frontend hides link and denies page, real-browser tests | History stays available to MEMBER by its pre-existing permission, not dashboard permission |
| Identity privilege expansion | One bounded label lookup through separate identity engine, organization + scoped page IDs; runtime receives no new grant | Identity service remains a trusted cross-tenant component; labels may change after aggregate read |
| SQL/filter injection or arbitrary scan | Enum windows, UUID cursor, limit 1–100, extra query keys forbidden, parameterized tenant/date filters, no query-language endpoint | Current backlog/median requires work proportional to tenant size; resource budgets remain unimplemented |
| N+1 queries / event-history loading | SQL COUNT/GROUP BY/percentile; one workload aggregate plus at most one bounded label read; query-count regression and 20,000-event plan comparison | High concurrency and very large tenants are not benchmarked |
| Stored markup | React text nodes for titles, names and codes; no HTML injection path; literal markup unit tests and shared browser workflow regression | Browser traces/screenshots can contain authorized business information; protect test/deployment artifacts |
| Private text or credentials in responses/logs | Aggregate projections exclude bodies and credentials; shared redacted error/no-store middleware; tenant-row preservation and payload exclusion tests | DB/proxy logs, backups and operational access need separate review |
| Repeated-run financial inflation | Money only from each run's existing immutable summary; UI warning and repeated-run exact-string tests; no cross-run financial total | New deduplication/business identity would need explicit approval before any such aggregate |
| Misleading historical claims | Current status separate from event actions; half-open UTC buckets; repeated resolution and boundary tests; age null/clock-skew rules | Separate endpoints have independent snapshots; historical events are only those actually retained |
| Dashboard writes or widened persistence | GET-only product endpoints; complete tenant-row read-preservation checks; index-only migration with full row/schema/grant/policy comparison | Routine auth session-touch writes remain; migration owner/DB administrators are privileged |
| Migration availability | 0005 adds/removes one nonunique index only; clean/0004 upgrade, drift and downgrade/re-upgrade tested | Standard index build may block writes; deploy with maintenance, backups and explicit timeout policies |

Existing credentialed CORS allowlisting, no-referrer, no-store, mutation CSRF and restrictive
identity/runtime startup checks remain unchanged. No new public env secret, outbound call, new
dependency, persistent aggregate, payment approval, notification worker, or governance UI is added.
See the [metric contract](dashboard-metrics.md) and [deployment profile](deployment.md).
