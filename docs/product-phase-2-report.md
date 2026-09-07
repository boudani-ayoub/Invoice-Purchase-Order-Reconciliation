# Product Phase 2 — identity, sessions, and tenant authorization

## Outcome and repository baseline

The web product now requires first-party authentication and current organization membership for
all analysis routes. The deterministic engine and successful report contracts are unchanged.
Financial uploads remain temporary; no business runs, history, CRUD, or AP workflow were added.

- Branch: `main`.
- Starting HEAD: `cecae36dce196a828c1e9aea083709342903db27`.
- Starting tracked tree: clean. An unrelated untracked root `package-lock.json` was preserved.
- Starting evidence: 280 Python tests, including 35 PostgreSQL tests; 32 frontend unit tests;
  15 browser tests. Baseline Python and frontend tests were rerun before implementation.
- Implementation commits: `b59c60b` identity/persistence, `30565fc` protected API, `d178113`
  authenticated frontend, and `2a795a5` security regression/CI. The documentation commit containing
  this report is the ending revision of this phase; its hash is recorded in the completion message.
- Final remote evidence: pushed to `main` at `bde0726e84a578cc8946f9d8440ead57bbf3e355`.
  [GitHub Actions run 34159230108](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/34159230108)
  completed successfully. No history was rewritten and no force push was used.

## Reasoning and scope decisions

The supplied prompt was reviewed against the actual Phase 1 models, RLS policies, HTTP adapter,
Next application, tests, and CI. It left several deliberate choices open rather than prescribing
a single implementation. The decisions are recorded in
[authentication architecture](authentication-architecture.md): opaque sessions, Strict cookies,
explicit multi-organization selection, generic registration/recovery acknowledgements, temporary
fixed-window identifier limits, SMTP behind a small interface, and role-specific RLS policies.

The existing `users` model and accepted `0001` migration were retained. `0002` adds only the auth
schema and nullable verification timestamp. Existing users are not silently assigned credentials
or verified status. No external identity store, JWT system, OAuth provider, MFA placeholder, or
admin dashboard was introduced. Configuration values, routes, password limits, role permissions,
and token helpers are centralized; account/organization/token values are generated at runtime.

## Authentication architecture

| Control | Implemented behavior |
| --- | --- |
| Password storage | argon2-cffi Argon2id, 64 MiB memory, three iterations, four lanes, library-generated salts, rehash on successful login |
| Password policy | 15–128 Unicode code points; spaces allowed; no trimming, normalization, or composition rules; bounded login input and 16 KiB auth JSON |
| Session token | 32 cryptographically random bytes / 256 bits, URL-safe opaque value with no identity claims |
| Session database | SHA-256 token hash only; user, active organization, last-seen, idle/absolute deadlines, revocation timestamps |
| Expiry | 30-minute sliding idle deadline capped at a 12-hour absolute lifetime; injectable clock for tests |
| Rotation/revocation | Fresh token on login and organization switch; switch preserves absolute deadline; logout revokes; reset revokes every session |
| Production cookies | __Host-reconcile-session and __Host-reconcile-csrf; Secure, HttpOnly, SameSite=Strict, Path=/, no Domain |
| Development cookies | Separately named reconcile-dev-session/reconcile-dev-csrf; non-Secure only in explicit development mode |
| Email tokens | 256-bit randomness, hash-only storage, single-use and purpose-bound; verification 24 hours, reset 30 minutes; reissue invalidates prior tokens |
| Throttles | Atomic PostgreSQL identifier buckets, HMAC fingerprints; five login attempts per 15 minutes, three registration/recovery/resend attempts per hour, including unknown accounts |

The selected hashing parameters exceed the published
[OWASP Argon2id minimum](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
checked during implementation. This is not a compliance or production-readiness claim.

Registration atomically creates User, Credential, Organization, and ORG_ADMIN membership. Email
validation uses email-validator and the accepted lowercase uniqueness contract. Duplicates and
recovery requests return the same generic 202 acknowledgement. Unknown login performs dummy
password work; wrong, unknown, unverified, archived, or throttled login fails generically. Timing
is not claimed to be constant, especially around synchronous mail delivery.

## Routes and authorization

Auth route suffixes below use the `/api/v1/auth` prefix. `/health` and the listed analysis paths
are absolute paths, outside that prefix.

| Access | Routes |
| --- | --- |
| Public read | `GET /health`, `GET /csrf` bootstrap; development/configurable API docs |
| Public account actions, CSRF required | `POST /register`, `/login`, `/forgot-password`, `/reset-password`, `/verify-email`, `/resend-verification` |
| Authenticated identity | `GET /me` |
| Authenticated context change, CSRF required | `POST /select-organization` |
| Idempotent sign-out, CSRF required | `POST /logout`; an already missing/revoked session is safe to sign out again |
| Protected analyses, CSRF and RUN_ANALYSIS required | `POST /api/v1/reconcile`; `POST /api/v1/analyses/invoice-po`, `/invoice-receipt`, `/po-receipt`, `/three-way` |

The server checks a session hash and deadlines, active user, current active memberships and
organizations, and the centralized permission map. MEMBER, AP_MANAGER, and ORG_ADMIN all have
RUN_ANALYSIS in this phase. One active membership is selected automatically; several require an
explicit selector; none cannot enter tenant workflows. A selector never establishes permission.

Only the verified organization reaches `tenant_session()`, where current membership and
organization are checked again under tenant RLS. Roles are not copied into browser tokens.
Membership/user/org changes take effect on the next authorization check. An already authorized
in-flight analysis is not retroactively canceled. Missing/expired sessions use 401; forbidden
membership/context/CSRF uses 403. Invalid email links use a generic 400; field validation uses 422.

## Database security

- `reconcile_identity` is a NOLOGIN privilege group for a dedicated restricted login. It can
  SELECT/INSERT/UPDATE auth records, SELECT/INSERT users, and update only `users.email_verified_at`.
  It can SELECT/INSERT organizations and memberships for registration, but cannot update their
  roles/statuses. It cannot read or modify procurement tables.
- `reconcile_runtime` remains the separate tenant request role. It cannot read users, credentials,
  sessions, recovery tokens, or throttle records. Existing tenant grants and policies remain.
- The migration owner handles DDL only. Both HTTP roles are checked at startup for owner/admin
  privileges, inappropriate group memberships, schema creation, and forbidden table grants.
- All 20 tables keep ENABLE/FORCE RLS. The session's `(active_organization_id, user_id)` composite
  FK references a real membership; active status is still enforced in the application.
- Clean upgrade, metadata parity (`alembic check`), and Phase 1 → head with pre-existing identity
  and supplier records are tested against real PostgreSQL. The original 35 database cases remain.
- SQLAlchemy hides bound parameters; ASGI failures log only exception class. Database/proxy/SMTP
  logs require separate operational controls because driver error DETAIL may include row values.

## CSRF, CORS, and browser state

The CSRF bootstrap creates a random HttpOnly context cookie and returns a random nonce with an
HMAC-SHA256 signature bound to that cookie and the current session token. The signing key is
required private configuration. The browser stores only the returned proof in memory and sends
it as `X-CSRF-Token`. Every POST also requires an exact trusted Origin. The same design covers
pre-auth account actions, login, logout, organization switching, and analyses. Login/logout/switch
rotate context; old proofs fail. See the [OWASP signed double-submit guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

Credentialed CORS uses the explicit `RECONCILE_ALLOWED_ORIGINS` allow-list, GET/POST, Content-Type,
and X-CSRF-Token. Wildcards and credential-bearing origins are rejected; production requires HTTPS.
Same-origin HTTPS is preferred. Local examples consistently use 127.0.0.1 on both browser-facing
ports. All API responses carry no-store; auth/report data is not publicly cached.

The frontend adds `/login`, `/register`, `/forgot-password`, `/reset-password`, and `/verify-email`.
A small AuthProvider loads `/auth/me`; ProtectedApp provides navigation UX and an organization,
user, reconciliation, and logout shell. The backend remains the actual security boundary.
Multiple memberships expose a selector. Organization changes remount the workspace. The shared
transport sends cookies, owns in-memory CSRF, clears expired auth on 401, and never silently
replays POSTs. No credential is placed in localStorage, sessionStorage, IndexedDB, or public env.

## Mail and recovery

The mailer interface has SMTP TLS and explicit development-disabled implementations; integration
tests inject an in-memory mailbox. Production requires verification and SMTP configuration.
Mail failures return a generic acknowledgement and log a sanitized operational failure; users can
request another link. This is not a durable queue and startup does not prove provider delivery.

Mail links carry tokens in fragments, never request query strings. Forms remove the fragment on
mount and require explicit confirmation; scanners do not auto-consume links. Invalid verification
links offer a direct resend shortcut. Password reset locks user/token, hashes the replacement,
invalidates outstanding reset tokens, and revokes all sessions in one transaction.

## Verification performed

Local verification used Python 3.12.7 and 3.11.16, PostgreSQL 17.11, Node 24.19.0, Next 16.3.4,
argon2-cffi 25.1.0, and email-validator 2.3.0. PostgreSQL was real, not SQLite; each test run
provisioned a unique disposable database and separate role logins.

| Suite | Result |
| --- | --- |
| Python 3.12 | 385 passed |
| Python 3.11 | 385 passed |
| Auth integration, included above | 73 passed |
| Other PostgreSQL integration, included above | 36 passed: 35 original cases plus upgrade-preservation regression |
| Auth primitives/configuration, included above | 31 passed |
| Frontend Vitest | 47 passed |
| Chromium real-service E2E | 24 passed |
| Axe checks, included in E2E | 14 scans, no serious/critical violations |

Executed: optional-extra installs; full pytest; Ruff lint/format checks; pip check on both Python
environments; npm ci; frontend lint/unit/build; npm audit (zero vulnerabilities); source/wheel
build; both CLI help entry points; sample reconciliation from a clean wheel environment with no
FastAPI/SQLAlchemy/Argon2/psycopg installed; Git whitespace checks and staged-diff review.

Security regressions cover session fixation/rotation/expiry/revocation, all five analysis routes
rejecting missing/invalid/expired/membership/CSRF failures before loaders run, dummy verification,
enumeration responses, persistent concurrent throttles, two-way cross-org rejection, current
roles/membership/user/org status, identity-role isolation, registration rollback/races,
reset/verification replay/reissue/expiry, concurrent reset, production cookies, secret-safe
errors, and recovery session revocation. Existing business/upload unit tests isolate auth with a
test-only dependency override; auth integration and browser tests use the real security path.

Checks caught and corrected missing UI primitives, incorrect test matchers, a build using the
local development API port instead of the E2E port, and ambiguous Next route-announcer selectors.
The final suite uses the test API build configuration and verifies meaningful page readiness
before accessibility scans. No failing check was removed to obtain a passing result.

Known tooling warnings: Starlette's test client uses a deprecated AnyIO alias; the locked ESLint 9
version is deprecated pending compatible lint-stack migration; Next notices the pre-existing
untracked root lockfile. These warnings did not fail verification. No dependency force-fix was run.

## Interactive browser review

Using the computer-use workflow on the local production frontend, with synthetic data:

- A protected page redirected to login; registration completed with the generic acknowledgement.
- Wrong-password feedback was visible and focused; correct login showed the actual organization
  and user; refresh retained the session; logout returned to login.
- Three synthetic source exports produced the expected sample report: 15 invoices, 17 lines,
  six matched, 11 requiring review; disputed totals EUR 2,450.00, MAD 10,199.00, USD 75.00.
- Recovery displayed its generic acknowledgement. An invalid verification fragment was removed
  from the URL and produced readable feedback. The new resend shortcut opened the email form.
- A missing reset token showed guidance and disabled completion. The 375 × 812 login/verification
  layouts were inspected visually; Tab moved to a visibly focused email field.

Actual SMTP delivery, manual multi-minute expiration, production TLS, and manual multi-membership
administration were not exercised. Token lifetimes, concurrent replay, and organization switching
were covered by automated integration/browser/unit tests. No third-party mail or real user records
were used for testing.

## CI and remaining limits

CI retains Python 3.11/3.12, PostgreSQL integration, and Node 24 frontend checks. Database and
browser jobs install the required auth extras. The browser job has PostgreSQL and launches real
authenticated services through deterministic readiness checks. The no-dependency CLI wheel smoke
remains. Remote run `34159230108` completed successfully for
`bde0726e84a578cc8946f9d8440ead57bbf3e355`. All four jobs passed:
Python 3.11, Python 3.12, PostgreSQL and authentication integration, and Frontend and authenticated
browser verification. This final evidence was verified after the Phase 2 push.

This is not a public production deployment approval. Remaining work includes MFA/SSO evaluation,
network/IP and concurrency limits, bounded auth-state retention, tested backups/restore, real SMTP
delivery and monitoring, full deployment CSP/incident response, and future actor-aware auditing.
There is no persistent business history, business CRUD, admin/member-management UI, or AP workflow.
Full application/identity-role compromise remains a major trust boundary; see the
[threat model](threat-model-auth.md) for per-threat residual risks.

## Next step

Product Phase 3 — persistent reconciliation runs, provenance, meaningful CRUD, history, and
actor-aware audit events. Phase 3 is not implemented here.
