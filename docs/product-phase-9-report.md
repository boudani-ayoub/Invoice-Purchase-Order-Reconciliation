# Product Phase 9 report

## Status and baseline

Phase 9 is complete and verified locally as deployment readiness, not a public deployment or
production certification. Remote verification has not been performed and no push is authorized.

Starting commit: `9ef306dc0012650141af9ea84f8303e397270e28` (`docs: record product phase 8 CI success`).
The previously verified Phase 8 baseline passed GitHub Actions run `35146786677`. Those results do
not certify the Phase 9 changes.

## Implementation

- Production settings reject enabled API docs, disabled verification/mail, unsafe origins, weak
  CSRF keys, identical identity/runtime connections, missing connection hosts, host/service query
  overrides, and remote PostgreSQL transport without `sslmode=verify-full`. Startup still rejects
  owner/admin/BYPASSRLS or incorrectly separated application roles.
- Both restricted database engines have bounded connection/pool waits. `/health` remains liveness;
  `/health/ready` probes both engines concurrently, has a bounded response deadline, and returns
  only generic ready/not-ready state without mutating tenant data or sending mail.
- Request events contain server request UUID, method, normalized route, status, elapsed time, and
  response size. `deploy/logging.json` enables that logger and disables raw Uvicorn access logging.
  Nginx access logs omit targets, query strings, headers, and bodies.
- A fixed-field renderer supplies a concrete same-origin Nginx profile: canonical host forwarding,
  overwrite/clear client forwarding metadata, unknown-host rejection, TLS 1.2/1.3, bounded bodies,
  timeouts, IP rate/connection controls, and generic non-cacheable proxy errors. HSTS is staged,
  disabled by default; certificates/private keys belong outside Git.
- Reviewed systemd examples use unprivileged `reconcile` processes on loopback, restart policies,
  TERM shutdown, private temporary storage, and file/task/memory bounds. Migration credentials never
  belong to those units. The Next build root is derived from its configuration directory, not an
  unrelated parent lockfile.
- Restore verification now exercises Phase 8 auth/governance/source/report/workflow/inventory/
  intelligence state, revision `0008`, indexes, RLS, grants, immutable triggers, authentication,
  selected-run metrics, and an exact stock balance after isolated restoration.
- The fifth CI job retains the existing four jobs and adds Nginx + production Next + production
  Uvicorn + PostgreSQL 17 with ephemeral HTTPS and synthetic accounts/data. Its acceptance harness
  also rehearses rejecting an unbuilt release and restoring the known-good frontend artifact,
  without changing or downgrading the database.
  The disposable database owner stays in the launcher/control plane; the HTTP child receives only
  restricted database logins and a small runtime environment, not owner/admin/provider credentials.
- Added the final synthesized threat model and incident runbook; updated release, rollback,
  monitoring, secret handling, retention, recovery, and synthetic operator-smoke documentation.
  Deployment examples and the shell harness are included in the source distribution.

The intended deployment topology is browser HTTPS -> Nginx -> loopback Next `3000` and Uvicorn
`8000` -> private PostgreSQL with distinct runtime/identity logins. The disposable acceptance
profile binds the proxy itself to loopback `8080/8443`; it is not a public service.

Sample limits are 10 MiB/file, 32 MiB total multipart, 32 KiB pre-auth bodies, 256 KiB other API
bodies, upload 10/minute/IP with burst 3 and four concurrent/IP, auth 5/minute/IP with burst 5,
20 total connections/IP, and 16 Uvicorn requests per worker. These are protective examples, not a
capacity guarantee. Large-input load and real infrastructure still require operator measurement.
The API unit's sample 3 GiB ceiling allows headroom beyond 32 concurrent 64 MiB Argon2 checks;
operators must size memory and concurrency together. The acceptance launcher uses one API worker
and does not exercise systemd resource enforcement.

## Local verification evidence

| Check | Result |
| --- | --- |
| Python 3.11.16, full normal CI suite | 373 passed, 411 database tests skipped because no database URL was set; 1 dependency deprecation warning |
| Python 3.12.7 with PostgreSQL 17.11 | 784 passed, no skips; 1 dependency deprecation warning |
| PostgreSQL integration | All 411 database tests executed in the Python 3.12 run, including strengthened dump/restore, clean migration/head checks, `0008` preservation, grants/RLS, inventory locking/replay/immutability, auth and tenant boundaries |
| Ruff lint / format | Passed |
| `pip check`, both Python environments | No broken requirements |
| Source/wheel build | Passed; setuptools 84.0.0 |
| Fresh wheel import, CLI help and synthetic sample | Passed; no extra runtime dependencies required for the CLI |
| Frontend lint, Node 24.15.0 | Passed |
| Frontend unit tests, Vitest 4.1.11 | 19 files / 170 tests passed |
| `npm audit` | 0 vulnerabilities reported |
| Next 16.3.4 production build | Passed; 23 generated pages, TypeScript clean |
| Existing Chromium E2E / axe | 41 tests passed; included accessibility assertions passed |
| New HTTPS deployment profile / axe | 1 Chromium security-boundary test passed, including both axe scans with zero violations; Nginx syntax/TLS 1.2/1.3, private socket checks, restart/failed-release rollback, log redaction, and temporary-file checks passed |
| Secret regression / repository hygiene | Passed; the narrow tracked-file scanner and repository hygiene tests are not comprehensive secret or security certification |

The canonical CLI sample still produces 15 invoices, 17 lines, 6 matched, 11 review-required, and
disputed amounts EUR `2450.00`, MAD `10199.00`, USD `75.00`.

An earlier in-progress full run had one renderer-test failure while its template was being edited;
the finalized rerun above passed all 784 tests. The first added forwarding unit fixture also needed
its test-client lifespan setup corrected; both trusted/untrusted policy cases pass in the rerun.
Neither was a change to reconciliation or inventory semantics.
The first real HTTPS browser run caught absent API `nosniff` headers after proxy duplicates were
removed. The response boundary now supplies API `nosniff` and `no-referrer` once, with a regression
assertion; the deployment test was retained unchanged.

The local HTTPS run used Windows Chromium against the private Ubuntu 22.04 WSL stack with Nginx
1.28.2, PostgreSQL 17.11, Python 3.12.14, Node 24.15.0, and the production Next build. Windows/WSL
browser-process interop was unavailable, so the documented external-runner hook coordinated the
same browser test; CI runs Playwright directly on Linux. The Linux build itself passed compilation,
TypeScript, and all 23 generated pages. No public-CA trust or real SMTP delivery was claimed.

After the synthetic sample and rollback, the measured readiness response was `0.017266s` / `200`;
API resident memory was `85756 KiB` and frontend resident memory `126148 KiB`. These are single-run,
post-request observations, not peak-load or sustained-capacity benchmarks. The failed candidate
returned a generic frontend `503`, API readiness remained `200`, and the known-good artifact
recovered without a schema downgrade. The harness stopped its services/database and removed the
ephemeral certificate, private key, and request buffers after verification.

## Security and operational conclusions

The adversarial review retains live authorization plus forced RLS/composite keys, separated identity
and tenant logins, generic auth/error responses, hash-only single-use tokens, session rotation and
revocation, cookie/session-bound CSRF plus Origin checks, append-only evidence/events/ledger,
optimistic versions, ordered stock locking, bounded analytics, and plain-text rendering. No business
authorization was broadened. Focused CSP is not a strict nonce-based script policy.

Migration/release order is recovery point -> maintenance/compatibility decision -> owner-controlled
upgrade/check -> grants/RLS/triggers -> reviewed artifacts -> readiness -> authenticated synthetic
smoke -> observation. Application rollback never automatically downgrades schema. The backup smoke
is an isolated technical rehearsal, not installed encrypted/off-host backup or a promised RPO/RTO.
Restoration can revive old sessions/tokens and requires a separate revocation/cutover decision.

Residual risks include owner/operator or authorized-insider compromise, runtime SQL compromise,
mailbox/browser compromise, registry/action compromise, distributed abuse, CPU/temp exhaustion,
backup/key loss, human error, and undiscovered defects. Rate zones are instance-local, Python
dependencies have bounded ranges rather than a fully locked transitive resolution, and regex secret
checking is not a comprehensive scanner. SMTP delivery, genuine certificate trust/renewal,
firewall/private network, systemd sandbox behavior on a target host, capacity, scheduled protected
backups, monitoring/on-call, retention/legal policy, and environment-specific security assessment
remain operator requirements. No compliance, availability, penetration-test, or production
certification is claimed.

See [deployment](deployment.md), [backup/restore](backup-restore.md),
[incident response](incident-response.md), and [final threat model](threat-model-final.md).

## Scope and Git

No public/cloud deployment, domain, customer database, real SMTP credential, real financial input,
new business feature, payment, supplier ranking, forecasting, AI/OCR, or data purge was introduced.
Procurement/supplier intelligence remains selected-run only; repeated runs are not summed. Imported
GoodsReceipt evidence still does not post inventory, and there is no valuation or unlike-item
quantity rollup.

Local implementation commits, in order:

- `120f4701ecb974c82587e74ef376e48f84fa6b81` — `feat: harden production runtime boundary`
- `05ed4e01da33186834cf4f08bc11741a4b48b578` — `ops: add same-origin deployment profile`
- `dc29fa290fdb1932165d9a6414d0962e4975055c` — `test: verify production proxy and recovery boundary`
- `23a3aeed3fd3aece1a47b2a328a9d7e9f717304a` — `fix: close production profile verification gaps`

The final local HEAD is the `docs: record product phase 9 readiness` commit containing this report;
resolve its exact identifier with `git rev-parse HEAD`. Documentation is the only change after the
tested implementation HEAD `23a3aeed3fd3aece1a47b2a328a9d7e9f717304a`.

The intended final working-tree status is only the preserved, unrelated untracked root
`package-lock.json`; no generated artifacts or unrelated files are staged. Its SHA-256 remains
`DAA0308A5EB8C96651E80918807B4EC840C32FA960BC4308AC915136161868AE`.
Remote main was independently checked on 2026-09-26 and remains the starting SHA
`9ef306dc0012650141af9ea84f8303e397270e28`. No Phase 9 GitHub Actions run exists because no push was
performed. Phase 9 is complete and verified locally; remote verification remains pending.
No phase after Phase 9 has begun.
