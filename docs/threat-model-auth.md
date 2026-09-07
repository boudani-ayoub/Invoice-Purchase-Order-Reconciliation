# Authentication threat model

Scope: Product Phase 2, first-party email/password accounts, organization memberships, opaque
sessions, four stateless analyses and the legacy analysis route. No payment execution or saved
business workflow exists. This is a design review with regression evidence, not certification.

## Assets and trust boundaries

Assets are account credentials, email identity, active sessions, tenant membership, temporary
financial uploads/reports, private service credentials, and availability. The browser is untrusted.
FastAPI validates every protected request; Next route guards only guide navigation. PostgreSQL
has distinct migration-owner, identity, and tenant logins. SMTP and the reverse proxy are external
operational boundaries. Administrators and full application compromise remain highly privileged.

`tests/database/test_auth.py` exercises the actual FastAPI service and restricted PostgreSQL roles.
`tests/database/test_database.py` retains the original tenant isolation/constraint tests.
`tests/test_auth_primitives.py` checks crypto/configuration; `frontend/e2e/auth.spec.ts` uses real
registration/login and browser cookies, not an authentication mock.

## Threat review

| Threat | Asset / entry point | Implemented mitigation | Remaining risk | Test / evidence |
| --- | --- | --- | --- | --- |
| Credential stuffing | Account access; login POST | Argon2 verification; persistent identifier limits; generic failure; no permanent lockout | Reused passwords can still work; distributed identifiers evade per-account limits; no MFA | Route throttling, unknown dummy verification, concurrent throttle test |
| Password database compromise | Credential hashes; DB/backup theft | Argon2id, random salts, 64 MiB/t3/p4, rehash on successful login; no plaintext | Offline guesses remain possible; backups need protection; no pepper/key-management dependency | Real hash verification, preserved spaces/Unicode, rehash test |
| Account enumeration | Email identity; login/register/recovery | Normalized generic responses; dummy Argon2 for absent login; same buckets for unknown accounts | Response timing is not constant-time; synchronous SMTP can distinguish eligible recovery timing; mailbox owner receives mail | Duplicate normalization/concurrency, generic failures and recovery tests |
| Session theft | Browser credential; XSS, endpoint/device compromise | HttpOnly Secure production cookies, strict same-site policy, hash-only DB storage, no persistent JS storage | HttpOnly cannot stop malicious same-origin code issuing requests; compromised devices can copy cookies | Production Set-Cookie tests; browser storage inspection |
| Session fixation | Account session; incoming arbitrary cookie | Successful login always creates a fresh server-generated 256-bit token and revokes an incoming valid session | An already compromised browser is outside this defense | Arbitrary-token fixation regression |
| Session replay | Account access; copied opaque token | Idle/absolute expiry, server revocation, logout, org-switch rotation, reset revokes all sessions | A stolen unexpired token works until revocation; already authorized in-flight analysis is not canceled | Copied-token logout, expired/unknown/revoked tests; browser revocation test |
| CSRF, including login CSRF | Account/workflow actions; cross-origin forms/fetch | HMAC proof bound to random HttpOnly context cookie and current session; explicit trusted Origin on every POST; Strict cookies | XSS in a trusted origin can get valid proofs; allow-list compromise is significant | All eight auth mutations, all five analysis routes, stale proof, origin/key/cookie/session binding tests |
| XSS / token theft | Account and temporary report; browser rendering | React text rendering, no injected HTML, no remote scripts/analytics, HttpOnly sessions, fragment cleanup, focused CSP | Current CSP is not a full script/style policy; malicious extensions and same-origin script compromise remain | Existing rendering tests, auth transport tests, narrow/axe browser checks; static source review |
| Cross-tenant IDOR | Tenant records; API selectors | Server principal → fresh membership → centralized permission → verified UUID → tenant RLS; no business CRUD routes yet | Future resource routes must repeat authorization; process-level arbitrary SQL can choose tenant context | Two real accounts reject each other's org; original A/B RLS read/write tests |
| Organization-ID tampering | Active tenant; select-organization body/header | UUID is only a selector; active membership required; session composite FK; token rotation preserves absolute deadline | Authorized membership in several orgs still needs careful UX; no admin changes implemented | Foreign-key rejection, valid switch and cross-org negative tests |
| Stale membership | Tenant access; an existing session | Recheck user, organization, membership and role every protected request; tenant transaction rechecks membership | A concurrent revocation can race a request already authorized; no retroactive cancellation | User/org/membership archive tests; live role-change test |
| Privilege escalation | Tenant permissions; browser role or stored stale role | Only RUN_ANALYSIS exists; centralized immutable role map; current DB role, never role claims from browser | Full identity/tenant credential compromise exceeds this boundary; future privileges need new tests | All existing roles allowed; live role and no-membership tests; dependency review |
| CORS misconfiguration | Credentialed responses; hostile website | Explicit credentialed GET/POST allow-list; no wildcard/userinfo/path origins; production HTTPS validation | Same-site sibling compromise matters; proxy configuration may drift; CORS alone is not authorization | Trusted/untrusted preflight tests, wildcard/config rejection, Origin rejection |
| DB-role compromise | Identity or procurement state; leaked service URL | Separate roles, startup checks, no owner/super/BYPASSRLS, no role/schema creation; identity denied procurement; tenant denied credentials | Identity login can take over accounts and insert memberships by design; arbitrary tenant SQL can set context; DB admin controls DDL | Role flag/grant tests and direct denied SELECT/UPDATE; every table forced RLS |
| Email reset-token theft | Account recovery; mailbox/link/endpoint | 256-bit opaque tokens, short reset TTL, hash-only DB storage, fragments avoid request URLs, no-referrer API policy, no third-party browser code | Email compromise still allows takeover; links can be forwarded or captured on-device; browser memory is not secret from XSS | Hash-only token, random-token denial, fragment removal, no-secret logging tests |
| Reset / verification replay | Password/email identity; consume POST | Lock user then token, single-use/expiry checks, transaction invalidates outstanding same-purpose tokens; reset revokes sessions atomically | Delayed SMTP messages can contain replaced links; resend may be needed | Valid/reused/replaced/expired token cases; concurrent reset only succeeds once |
| SMTP secret leakage | Mail service/account links; configuration/provider failure | Hidden repr, TLS with certificate validation, no raw message or exception logging, generic public response | Provider logging and operational secret stores are outside app tests; durable queue not implemented | Both SMTP transports mocked for TLS assertions; secret-bearing delivery failure test |
| Brute force / DoS | Availability; auth and multipart endpoints | 16 KiB auth JSON bound; 128-code-point password ceiling; persistent bounded account attempts; streamed file ceiling | Many unique emails grow buckets/accounts; expensive valid passwords consume memory; multipart may spool before auth; no IP/global limit | Oversized JSON/password checks, concurrency throttle, upload-limit regressions; deployment resource checklist |

## Operational requirements and exclusions

- No public production approval is implied. Require HTTPS, same-origin proxy routing where possible,
  SMTP delivery testing, network/IP/concurrency budgets, restricted temporary storage, and alerts.
- Application logs omit request bodies, credentials and exception details. PostgreSQL error DETAIL,
  proxy traces, SMTP logs, browser failure traces, and backups can still contain sensitive values;
  operators must configure and protect these separately.
- Expired auth state needs a privileged retention policy. The HTTP roles intentionally cannot
  DELETE. No purge job or durable mail retry queue is included in this phase.
- Session revocation takes effect at authorization checks; it does not undo a completed request.
  Full account administration, MFA, SSO, breached-password checks, actor-aware business auditing,
  persistent reports, recovery objectives and a complete deployment CSP remain future work.
- Browser tests and manual review use synthetic data in disposable databases. Real SMTP delivery,
  production TLS/proxy behavior, adversarial load testing, and formal penetration testing are not
  claimed as executed.

The implementation follows the password-storage and CSRF references linked in
[authentication architecture](authentication-architecture.md). Reassess this model when Phase 3
introduces saved data and resource identifiers rather than assuming current tests cover new routes.
