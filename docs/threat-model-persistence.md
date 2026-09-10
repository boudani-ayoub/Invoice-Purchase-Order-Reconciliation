# Persistent-data threat model

## Scope and trust boundaries

Phase 3 covers authenticated multipart creates, organization-scoped history, metadata updates,
soft archive/restore, PostgreSQL source evidence, snapshots, and audit events. It extends the
[identity threat model](threat-model-auth.md); it does not approve a production deployment.

Assets include financial source identifiers and quantities, invoice/PO/receipt records, original
file hashes and names, immutable results, internal notes, actor attribution, accounts, and sessions.
Entry points are the nine protected upload routes, run list/detail, three metadata mutations,
browser rendering, database administration, logs, and backups.

```text
Untrusted browser/files
  → session + current membership + permission + CSRF/Origin gate
  → temporary upload + existing strict loaders + existing analysis engine
  → tenant transaction: evidence + run + findings + snapshot + audit
  → scoped history API → escaped text / existing report components
```

HTTP authenticates the organization; RLS constrains the resulting transaction. A caller who can
execute arbitrary SQL as the runtime can set tenant context themselves, so RLS does not replace
application authorization. Owners/superusers remain a separate administrative trust boundary.
See PostgreSQL's [row-security model](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).

## Threats and evidence

| Threat | Mitigation and test evidence | Residual risk / operational requirement |
| --- | --- | --- |
| Cross-tenant run ID guessing | Fresh principal, explicit organization predicates, forced RLS; foreign and missing IDs both `404`; DB/API/browser negative tests | Same-tenant members can read the organization's history by design |
| Forged actor/organization fields | Create accepts only exact required file fields; metadata forbids extra fields; actor comes from session; composite actor/resource FKs tested | Compromised authorized account can create its own attributed actions |
| Revoked/stale access | Recheck session, user, organization, membership, role on every request and again before persist; revocation and organization-switch tests | Authorization at a request boundary is not cancellation of all already-running work |
| Role escalation | Central permissions; MEMBER cannot edit/archive; manager/admin allowed; direct API tests independent of UI visibility | No member-management UI yet; administrative role changes need controlled procedures |
| CSRF mutation | Trusted Origin plus session-bound signed proof for upload/PATCH/archive/restore; negative and CORS tests | Deployment origin/proxy mistakes remain dangerous; HTTPS required |
| Unauthorized upload resource exhaustion | Header-only ASGI gate; 45 tests assert zero body reads across nine paths and five denial cases | Authorized uploads and proxy buffering still consume resources; enforce total body/time/concurrency limits |
| Malformed/oversize source | Existing strict loaders; 10 MiB per file; controlled temp names; size/validation/cleanup tests | No row budget or job queue; valid small files may contain many rows |
| Filename path traversal / hidden payload | Basename normalization for both separators, control removal, bounded fallback; filename tests | Names remain untrusted display data; original names are not proof of source authenticity |
| Evidence substitution / silent deduplication | Streamed SHA-256 and byte count; physical row occurrence storage; no hash uniqueness; duplicate/re-import/unresolved tests | Hash proves received-byte identity only, not document origin or business truth |
| Partial write or missing audit | One transaction for create; one for each mutation and event; injected failures roll back sources, run, snapshot, findings, audit | Lost response after commit is possible; check History before retry, no idempotency contract |
| Lost updates or archive races | `FOR UPDATE` plus expected version; `409` conflict, refresh UI; simultaneous writer and stale archive tests | Clients must refresh and decide whether to resubmit; no merge UI |
| Historical result/evidence tampering | Snapshot trigger, runtime evidence/findings UPDATE revoked, column-scoped run UPDATE; DB tests | Owner/superuser can alter triggers/schema; no signed or external tamper-evident ledger |
| Audit mutation or forged metadata | Runtime SELECT/INSERT only, immutable row trigger, same-tenant FKs, server UUID, 2048-byte JSON bound; DB tests | Runtime compromise can insert permitted events; database administration must be audited separately |
| Stored XSS | React text rendering for titles, notes, filenames and report fields; unit and real-browser payload tests | Focused CSP is not a complete deployment-specific script policy |
| SQL/cursor injection or unbounded listing | ORM-bound values, allow-listed filters, strict bounded cursor, max 100/page; malformed cursor tests; list selects summary only | Broad runtime SQL capability is not a supported interface; archive-filter index selectivity should be measured at scale |
| Secrets or financial data in caches/logs | API `no-store`; no browser persistent storage; safe errors log exception class/request ID, audit records field names/versions only | Proxy/DB/APM logs and backups need independent redaction, access control and retention |
| Backup disclosure / restore privilege drift | Separate administrative restore path, encrypted restricted backup policy; disposable restore verifies reports, actor, RLS and role separation | Local smoke is not scheduled encrypted backups, PITR, disaster recovery, or a measured recovery objective |
| Archive mistaken for deletion | Explicit confirmation/copy; soft timestamp preserves evidence; no DELETE endpoint | Data and notes remain in backups too; retention/legal-hold/purge policy is not implemented |
| Storage capacity / encoding loss | PostgreSQL data errors become safe `422`, complete rollback; BIGINT overflow and NUL tests | Persistence supports DB capacity, not arbitrary mathematical limits; loaders/stateless APIs are unchanged |

Primary executable evidence: `tests/database/test_runs.py`, `test_run_security.py`,
`test_run_upgrade.py`, `test_run_backup.py`, `tests/test_run_primitives.py`, frontend history/API
unit tests, and `frontend/e2e/history.spec.ts`. Existing auth/RLS/snapshot tests remain active.

## Before public deployment

Choose and test capacity budgets, TLS/proxy settings, database network access, encryption and
restricted log/backup retention. Exercise recovery with approved operators, measure recovery time
and acceptable data loss, and approve an explicit retention/purge policy. Review privilege drift
and restore behavior after every migration. There is no compliance, non-repudiation, complete
OWASP coverage, or production-readiness claim. See [security roadmap](security-roadmap.md).
