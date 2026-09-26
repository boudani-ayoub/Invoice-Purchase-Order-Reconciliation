# Final product and deployment threat model

## Scope and method

This review covers the deterministic reconciliation engine, authenticated multi-tenant web product,
saved evidence, AP workflow, dashboard, organization governance, append-only inventory ledger,
run-scoped intelligence, and the Phase 9 deployment profile. It synthesizes the component reviews;
it does not certify the software, replace a penetration test, or claim that a public deployment exists.

The security objective is to preserve tenant isolation, evidence integrity, least privilege, and
bounded service behavior while keeping unavoidable operational risks visible. “Mitigated” below never
means eliminated.

## Assets

- Password hashes, session/token hashes, CSRF key, database/SMTP credentials, and TLS private keys.
- Organization membership/role state and invitation/governance history.
- Tenant purchase-order, receipt, invoice, supplier/item, source provenance, and reconciliation results.
- Workflow assignment, comments, resolution evidence, dashboard aggregates, and run audit history.
- Item/location masters, idempotency intent, inventory operations, immutable movements, and balances.
- Selected-run procurement/supplier evidence and current-ledger inventory intelligence.
- Database backups, release artifacts, operator configuration, and sanitized operational/audit logs.

Raw CSV bytes are request-scoped and not retained by the application; validated evidence, safe source
metadata, reports, findings, notes, and events persist and appear in backups.

## Trust boundaries

| Boundary | Trust and constraint |
| --- | --- |
| Browser | Untrusted input/UI environment; receives public frontend assets and `__Host-` cookies but no database/SMTP secrets |
| Nginx | Only public listener; terminates TLS, rejects unknown hosts, overwrites forwarding headers, bounds bodies/rates/connections |
| Next.js | Loopback production UI; owns CSP and browser resource headers; embeds only public API origin/timeout |
| FastAPI/Uvicorn | Loopback application; trusts proxy metadata only from loopback; authenticates, authorizes, validates, logs sanitized events |
| Tenant runtime role | Forced-RLS business access with narrow mutation grants; no identity/governance access, ownership, admin, or schema creation |
| Identity runtime role | Accounts/sessions/invitations/governance access; no procurement, workflow, inventory, or intelligence tables |
| Migration/operator role | High-impact offline boundary used for migrations/security verification, never HTTP startup |
| PostgreSQL | Private persistence and enforcement boundary for RLS, composite FKs, checks, locks, and immutable triggers |
| SMTP provider | External delivery boundary that can expose metadata/token links to provider/mailbox operators |
| Backup operator/storage | Can access broad historical identity/business state despite RLS; requires separate credentials, encryption, custody, and restore control |
| CI/dependency sources | Can influence build/test artifacts; constrained by lockfiles, read-only workflow permissions, package checks, audits, and review |

## Threat analysis

| Threat | Existing mitigation | Residual risk and detection | Owner/boundary |
| --- | --- | --- | --- |
| Credential stuffing and brute force | Argon2id, generic failures, persistent atomic identifier buckets including unknown users, proxy IP limits | Distributed clients/NAT effects, compromised mailbox/password, no MFA; watch throttle and login status trends | Identity owner; Nginx + FastAPI + identity DB |
| Session theft/replay | 256-bit opaque token, hash-only storage, rotation on login/org switch, idle/absolute expiry, server revocation, Secure/HttpOnly/Strict cookies | Endpoint/browser/host compromise can replay until revoked; correlate session lifecycle and request/audit events | Identity/infrastructure owner |
| CSRF | Signed double-submit bound to session, exact origins, Strict cookies, mutation dependencies, token rotation | CSRF-key compromise and same-site hostile content; old sessions survive key rotation | Application/secret owner |
| Email token/invitation abuse | 256-bit single-use hash-only values, expiry, replacement/revocation, fragment links, email binding | Mailbox/provider compromise and browser extensions; inspect lifecycle/governance events without raw token | Identity/SMTP owner |
| IDOR and tenant leakage | Live permissions, active membership checks, cross-tenant `404`, organization switch rotation, composite tenant FKs, forced RLS | Programming/owner-role mistakes or DB compromise; run multi-tenant API/RLS tests and monitor suspicious not-found patterns | Application + database owner |
| RLS bypass and role escalation | Runtime/identity group split, no owner/superuser/BYPASSRLS/CREATE/both-group login, startup verification, column/narrow grants | Migration owner, vulnerable SECURITY DEFINER code, role drift, arbitrary SQL under a group; alert on role/grant/policy drift | Database owner |
| SQL injection | SQLAlchemy bound parameters, strict typed inputs, no user SQL | Dependency/driver defects and future raw SQL; code review and error/query telemetry without parameters | Application owner |
| XSS and hostile stored text | React escaping, plain-text bounds, narrow CSP, no remote browser assets, no HTML rendering contract | Browser/dependency compromise and future unsafe rendering; CSP reports if deployed and browser tests/axe | Frontend owner |
| Malicious CSV/input | Exact UTF-8 schemas, bounded identifiers/decimals/dates, deterministic parser, error control, no formula execution by engine | Parser/resource edge cases and exported spreadsheet behavior; watch validation/size rates and fuzz/regression tests | Reconciliation owner |
| Upload/resource DoS | Early route authentication, 10 MiB/file, 32 MiB proxy total, streamed app writes, request cleanup, timeouts, proxy rate/connection and Uvicorn concurrency bounds | Multipart buffering/temp exhaustion, CPU-heavy valid inputs, distributed sources; monitor temp/CPU/latency/413/429 | Infrastructure + application owner |
| Proxy/Host/header spoofing | Unknown-host rejection, fixed redirect, Nginx header overwrite, Uvicorn loopback and exact trusted proxy | Compromised local host or incorrectly added upstream proxy; acceptance redirect/header tests and config review | Infrastructure owner |
| Secret leakage | Private config, repr/driver parameter hiding, no secrets in frontend, generic errors, narrow secret regression scan | Host/CI/operator screenshots, provider logs, scanner blind spots; provider scanning and credential-access audit still required | Secret/infrastructure owner |
| Log leakage | Structured template-only application log, request target/header/body omission, safe Nginx format, critical proxy error level | Timing/volume metadata and accidental future logger changes; marker regression plus restricted access/retention | Infrastructure/application owner |
| Evidence/report tampering | Atomic save, snapshot/audit triggers, denied evidence updates/deletes, source hashes/row provenance | Migration owner/database compromise and source authenticity beyond uploaded bytes; restore/security drift checks | Database/business owner |
| Workflow/governance manipulation | Explicit roles, optimistic versions, locked last-admin rule, append-only events, body excluded from general audit | Authorized insider misuse and absent approval workflow; review actor/event history and role changes | Organization admin/business owner |
| Inventory manipulation/replay | ORG_ADMIN-only writes, positive decimal input, server signs, stable idempotency key, ordered locks, negative-stock checks, immutable operation/movement triggers | Authorized fraudulent postings, key loss/change, valuation absent; monitor operation mix, reversals, lock waits, balances | Inventory/business + database owner |
| Aggregate intelligence leakage/misinterpretation | Manager/admin permissions, selected-run procurement scope, current-ledger inventory scope, exact currencies/denominators, no rankings/forecasting | Authorized inference, small cohorts, stale/archived evidence, consumers relabeling metrics; audit access and preserve scope labels | Analytics/business owner |
| Dependency/build compromise | Frontend lockfile, bounded Python requirements, `pip check`, `npm audit`, wheel smoke, Dependabot, read-only Actions, no generated dependencies committed | Registry/account/action compromise and unpinned Python transitive resolution; review advisories/artifact provenance before release | Release owner |
| Backup theft or incomplete restore | Separate operator, forced-RLS-aware dump guidance, protected/encrypted storage requirement, repository restore rehearsal through Phase 8 state | No scheduled/encrypted/off-host backup is installed; key loss, stale copy, broad backup visibility, unmeasured RPO/RTO | Backup/data owner |
| Operator or migration-owner compromise | Credentials absent from HTTP, explicit release procedure, recovery point, drift/security verification | Full schema/data/control-plane authority; require independent access control, approval, evidence, and rotation outside repository | Operations/database owner |
| Deployment misconfiguration | Fixed renderer fields, Nginx/systemd templates, production fail-closed config, fifth CI topology test, release smoke | Real DNS/cert/network/provider/system differences and untested local changes; `nginx -t`, staged rollout, monitoring | Infrastructure/release owner |
| Availability failure | Restart policy, liveness/readiness split, pool/connect/statement bounds, graceful reload/restart acceptance | No HA, queue, cancellation, autoscaling, or availability guarantee; monitor and define capacity/recovery objectives | Operations owner |

## Cross-component conclusions

The strongest boundary is defense in depth between live authorization and forced PostgreSQL RLS.
Neither is sufficient alone: a compromised migration owner can defeat both, while a compromised
runtime login can set its tenant context and therefore must still be treated as sensitive. Identity
and tenant roles limit blast radius but share the same database instance in the supplied profile.

Uploads are transient at the application layer, yet proxy buffers, operating-system temporary files,
process memory, logs, database evidence, browser traces, and backups are distinct retention surfaces.
The deployment profile removes request targets and payloads from operational logs but does not install
encrypted disks, backup storage, a retention engine, or secure destruction.

Inventory and intelligence intentionally do not bridge into automatic procurement posting, valuation,
supplier scoring, organization-wide spend, forecasting, or recommendations. Adding such a bridge would
change authorization, integrity, accounting, and model-risk boundaries and requires a new threat review.

## Required operational controls before public/customer use

- Provision reviewed DNS/certificates, private PostgreSQL, secret management, SMTP controls, encrypted
  bounded temporary storage, log storage, and independent operator identities.
- Establish measured capacity/rate/alert thresholds, on-call response, dependency patching, certificate
  renewal, scheduled protected backups, key recovery, and restore-rehearsal cadence.
- Approve retention/deletion/legal-hold and incident-communication policies without inventing them in
  application code.
- Run the exact release procedure, role/RLS/grant/trigger verification, production-like acceptance,
  authenticated smoke, SMTP delivery test, and an environment-specific security review.
- Commission penetration testing and compliance/legal assessment when the actual data, jurisdiction,
  customers, and control environment are known.

Residual risks remain even after these steps: insider/owner compromise, browser/mailbox compromise,
dependency compromise, distributed denial of service, backup/key loss, operator error, and application
defects cannot be eliminated by this repository profile.

Component detail remains in the upload/API review (`SECURITY.md`) and the persistence, auth, workflow,
dashboard, governance, inventory, and intelligence threat documents under `docs/`. Operational response
is defined in [incident response](incident-response.md), [deployment](deployment.md), and
[backup/restore](backup-restore.md).
