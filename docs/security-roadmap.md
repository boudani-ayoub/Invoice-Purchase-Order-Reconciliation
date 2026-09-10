# Security roadmap

This roadmap uses [OWASP ASVS 5.0.0](https://github.com/OWASP/ASVS/releases/tag/v5.0.0) as a
review checklist. It is not certification, a claim of compliance, or a production-readiness label.
Requirements must be selected and verified against the actual authenticated deployment's threat
model. Browser analyses now persist validated evidence, reports, metadata and audit events. Public deployment still
needs operational approval. Phase 1 history remains in its report and data-model document.

| Control area | Current evidence / boundary | Planned work |
| --- | --- | --- |
| Authentication | Argon2id 64 MiB/t3/p4; 15–128-character policy; registration, verification, generic login failures, dummy verification | Evaluate MFA, breached-password screening, SSO, and stronger abuse detection later |
| Session management | 256-bit opaque tokens; hash-only storage; secure production cookies; idle/absolute expiry; rotation and revocation | Deployed session-retention jobs, incident response, optional user session inventory |
| Password recovery | Hashed single-use expiring tokens; transactional reset revokes all sessions; SMTP TLS boundary | Production delivery checks, monitoring, durable mail retry if needed |
| Authorization | Current principals and permissions on create/history/mutations; cross-tenant `404`; role/revocation tests | Phase 4: workflow-resource permissions; Phase 6: member management |
| Tenant isolation | Composite FKs; forced RLS; session-to-membership FK; verified tenant transition; separate identity role | Repeat deployed-grant checks and negative tests with future business writes |
| CSRF | Signed cookie/session-bound proof plus trusted Origin on POST/PATCH; pre-auth, rotation, archive tests | Preserve checks on future mutations; test proxy topology |
| Rate limiting | Atomic PostgreSQL identifier buckets for login, registration, recovery, and resend; unknown accounts included | Phase 9: network/IP and concurrency budgets; storage retention and alerting |
| File upload | Pre-body authorization on nine routes; streamed size/hash, safe names, temporary cleanup | Phase 9: measured concurrency and proxy total-body/resource limits |
| Input validation | Existing strict loaders and domain mapper; duplicate/unresolved preservation; atomic rollback; storage capacity errors | Measure transaction/memory budgets on large imports |
| Logging and audit | Server request UUID; actor-aware same-transaction events; immutable audit rows; no notes/credentials in event metadata | Phase 6: audit administration; Phase 9: correlation/alerts and DB/proxy log controls |
| Secrets | Validated private auth/DB/SMTP configuration; no secrets in browser storage or public env | Secret manager, operational rotation, deployed log review |
| Database least privilege | Separate roles; forced RLS; runtime source/findings UPDATE denied, run UPDATE column-limited; identity cannot read business history | Deployed role drift checks, network restrictions, TLS, operational backup/restore |
| Security headers | Focused CSP, nosniff, referrer and permissions policy; no remote browser assets | Phase 9: deployment-specific resource CSP with nonces/hashes and tested origins |
| TLS | Reverse proxy guidance; local HTTP is supported | Phase 9: certificates, transport policy, HSTS rollout and trusted forwarded headers |
| Dependency security | Optional DB extra, locked frontend, CI checks and Dependabot | Every phase: patch review; update the Next lint stack when its plugins support maintained ESLint |
| Backup/restore | Financial data now persists; runbook and disposable PostgreSQL restore smoke | Scheduled encrypted off-host backups, key recovery, measured RPO/RTO before public release |
| Retention/deletion | Raw files temporary; reversible archive retains evidence/results/audit; no permanent delete API | Phase 6: approved retention windows, legal holds, governed purge policy |

## Product sequence

1. **Phase 1 — complete:** four analysis modes and optional PostgreSQL foundation.
2. **Phase 2 — complete:** identity, secure sessions, tenant authorization, protected routes.
3. **Phase 3 — current implementation:** persistent runs, metadata/archive CRUD, provenance, history, and actor-aware events.
4. **Phase 4 — next:** AP exception workflow, assignment, resolution lifecycle, due dates, comments, and reminders.
5. **Phase 5:** AP manager dashboard and measured KPIs.
6. **Phase 6:** organization administration, roles, audit, and governance.
7. **Phase 7:** inventory foundation and explicit stock movements.
8. **Phase 8:** supplier, procurement, and inventory intelligence.
9. **Phase 9:** authenticated production deployment and final threat model.

RLS protects configured database transactions; FastAPI now authenticates HTTP requests. A process able to
execute arbitrary SQL using the runtime login can set its own organization context; identity and
authorization checks remain indispensable. See [the data model](data-model-v1.md) and the
[PostgreSQL policy reference](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).
