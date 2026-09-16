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
| Authorization | Explicit role maps for runs, workflow, dashboard, administration, inventory, and intelligence; MEMBER has no inventory/insights access, AP_MANAGER has read-only intelligence, and ORG_ADMIN posts/manages stock | Design any future warehouse/procurement roles explicitly; do not widen AP_MANAGER by implication |
| Tenant isolation | Composite FKs; forced RLS including inventory aggregates; session-to-membership FK; verified tenant transition; separate identity role | Repeat deployed-grant checks and negative tests with future business writes |
| CSRF | Signed cookie/session-bound proof plus trusted Origin on POST/PATCH; pre-auth, rotation, archive tests | Preserve checks on future mutations; test proxy topology |
| Rate limiting | Atomic PostgreSQL identifier buckets for login, registration, recovery, and resend; unknown accounts included | Phase 9: network/IP and concurrency budgets; storage retention and alerting |
| File upload | Pre-body authorization on nine routes; streamed size/hash, safe names, temporary cleanup | Phase 9: measured concurrency and proxy total-body/resource limits |
| Input validation | Strict loaders/domain mapper plus inventory positive decimal-string contract, server-owned signs, future-time rejection, and bounded plain text | Measure transaction/memory budgets on large imports and stock-ledger growth |
| Logging and audit | Server request UUID; append-only run/workflow/governance/inventory events; bounded views; sensitive workflow and inventory bodies excluded from generic audit | Phase 9: correlation/alerts, tamper-evident export if required, and DB/proxy log controls |
| Secrets | Validated private auth/DB/SMTP configuration; no secrets in browser storage or public env | Secret manager, operational rotation, deployed log review |
| Database least privilege | Separate roles; forced RLS; source/finding evidence UPDATE denied; workflow/master UPDATE column-limited; inventory ledger UPDATE/DELETE denied and trigger-protected; identity has no inventory access | Deployed role drift checks, network restrictions, TLS, operational backup/restore |
| Inventory integrity | Explicit-only posting; exact Decimal strings; ordered locks prevent oversell/deadlock; atomic transfer/reversal; actor-bound idempotency; no receipt inference | Monitor lock waits and aggregate cost; consider finer locking/read optimization only from measured evidence |
| Intelligence integrity | Procurement/supplier metrics are selected-run only; money stays per currency; inventory uses only the explicit ledger; bounded pages/windows and constant-query tests prevent accidental unbounded aggregation | Monitor deployed query latency/cardinality and preserve the metric contract in future schema versions |
| Security headers | Focused CSP, nosniff, referrer and permissions policy; no remote browser assets | Phase 9: deployment-specific resource CSP with nonces/hashes and tested origins |
| TLS | Reverse proxy guidance; local HTTP is supported | Phase 9: certificates, transport policy, HSTS rollout and trusted forwarded headers |
| Dependency security | Optional DB extra, locked frontend, CI checks and Dependabot | Every phase: patch review; update the Next lint stack when its plugins support maintained ESLint |
| Backup/restore | Financial data now persists; runbook and disposable PostgreSQL restore smoke | Scheduled encrypted off-host backups, key recovery, measured RPO/RTO before public release |
| Retention/deletion | Raw files temporary; reversible archive retains evidence/results/workflow/governance history; no permanent delete API, purge engine, or legal-hold control | Future explicitly approved retention windows, legal holds, and governed purge execution |

## Product sequence

1. **Phase 1 — complete:** four analysis modes and optional PostgreSQL foundation.
2. **Phase 2 — complete:** identity, secure sessions, tenant authorization, protected routes.
3. **Phase 3 — complete:** persistent runs, metadata/archive CRUD, provenance, history, and actor-aware events.
4. **Phase 4 — complete:** AP exception workflow, assignment, resolution lifecycle, due dates, append-only comments/events, and in-app reminders. Pushed at `875ea7792ea59282752b560a842b4aa0ae99f809`; all four jobs passed in GitHub Actions run `34648366678`.
5. **Phase 5 — complete:** manager-only read model, current-state counts, bounded UTC event activity, workload and age; financial summaries remain per run. Pushed at `0b95ecae64b4191e2904d862851dfc34e4bf7bf8`; all four jobs passed in GitHub Actions run `34921520243`. See [metric semantics](dashboard-metrics.md), [verification report](product-phase-5-report.md) and [threat review](threat-model-dashboard.md).
6. **Phase 6 — complete:** explicit admin permissions, membership lifecycle and last-admin invariant, secure invitations/invited registration, organization rename, and bounded organization audit. See [verification report](product-phase-6-report.md) and [threat review](threat-model-governance.md).
7. **Phase 7 — complete:** explicit append-only inventory ledger, exact derived on-hand, ordered locking, atomic transfer/reversal, idempotent posting, and strict procurement separation. See [ledger semantics](inventory-ledger.md), [verification report](product-phase-7-report.md), and [threat review](threat-model-inventory.md).
8. **Phase 8 — complete locally:** selected-run procurement/supplier evidence, current-ledger inventory activity, explicit metric semantics, bounded query plans, and role-aware Insights. See [metric semantics](intelligence-metrics.md), [verification report](product-phase-8-report.md), and [threat review](threat-model-intelligence.md).
9. **Phase 9 — next:** authenticated production deployment and final threat model.

RLS protects configured database transactions; FastAPI now authenticates HTTP requests. A process able to
execute arbitrary SQL using the runtime login can set its own organization context; identity and
authorization checks remain indispensable. See [the data model](data-model-v1.md) and the
[PostgreSQL policy reference](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).
