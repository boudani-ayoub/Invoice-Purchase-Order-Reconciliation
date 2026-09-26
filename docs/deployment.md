# Production deployment profile

## Boundary and topology

This repository supplies a hardened, production-like deployment profile. It does not prove that a
public service exists, certify the application, or provide an availability, RPO, RTO, legal-retention,
or compliance guarantee. A deployment owner must still provision a real hostname, certificate,
private network, secret manager, SMTP service, backups, monitoring, and incident ownership.

The supported browser topology is one public HTTPS origin:

```text
Browser
   | HTTPS
Nginx
   |-- /api/*, /health, /health/ready -> Uvicorn/FastAPI 127.0.0.1:8000
   `-- /*                              -> Next.js        127.0.0.1:3000

FastAPI -> separate identity and tenant-runtime roles -> private PostgreSQL
FastAPI -> TLS SMTP provider
```

PostgreSQL, Uvicorn, and Next.js must not be reachable from the public network. Same-origin service
preserves the `SameSite=Strict` cookie policy and avoids broad CORS. A split-origin deployment is
supported only when both exact HTTPS origins are explicitly configured and remain same-site; do not
weaken cookie attributes to support an unrelated site.

The concrete files are:

- `deploy/nginx/reconcile.conf.example`: public proxy, TLS, body, timeout, rate, connection, and
  safe-access-log controls.
- `deploy/systemd/reconcile-api.service.example`: loopback-only Uvicorn with two workers and bounded
  per-worker concurrency.
- `deploy/systemd/reconcile-web.service.example`: loopback-only Next production process.
- `deploy/reconcile.env.example`: private runtime configuration shape, never working credentials.
- `deploy/logging.json`: explicitly enabled safe request events and disabled raw Uvicorn access logs.
- `scripts/render_nginx_config.py`: fixed-field renderer that rejects Nginx-fragment injection.

Render into a protected staging path and validate before installation:

```text
python -m scripts.render_nginx_config \
  --template deploy/nginx/reconcile.conf.example \
  --output <staged-nginx-conf> \
  --host <lowercase-production-host> \
  --certificate <absolute-fullchain-path> \
  --private-key <absolute-private-key-path> \
  --client-body-temp <absolute-restricted-temp-path> \
  --access-log <absolute-access-log-path> \
  --error-log <absolute-error-log-path>

nginx -t
```

Do not copy the example hostname, database hosts, senders, or paths without review.

## Production configuration and secrets

The API reads process environment; it does not load `.env.example` automatically. Install the real
environment file outside the checkout with root ownership, service-group read access, and no
world access, or inject equivalent values from a secret manager. The frontend build receives only
`NEXT_PUBLIC_API_BASE_URL` and the optional public request timeout. Never put credentials, token
keys, SMTP settings, or database URLs in a `NEXT_PUBLIC_*` variable.

Production startup fails closed when:

- browser origins are missing, wildcarded, credential-bearing, or not HTTPS;
- email verification is disabled, mail is disabled, or API documentation is enabled;
- the CSRF key is not at least 32 sufficiently varied random bytes;
- identity and tenant connection strings are identical;
- a non-loopback database URL omits `sslmode=verify-full`;
- authentication lifetimes/limits are non-positive, or database connect/readiness timeouts exceed
  30 seconds (readiness must also be finite);
- a connection host is missing or libpq query options attempt to override the explicit host;
- either HTTP database login is administrative, owns tables, has `BYPASSRLS`, can create schema
  objects, belongs to both application groups, or crosses the identity/tenant table boundary.

Generate `AUTH_CSRF_SECRET` privately with a cryptographic random generator. All API workers must
share it. Rotating it invalidates CSRF proofs, not sessions; follow the
[incident runbook](incident-response.md) if sessions must also be revoked. Keep migration-owner,
runtime, identity, backup-operator, and SMTP credentials independent. For remote PostgreSQL, keep
the server on a private network and use a reviewed CA plus hostname verification. A protected
libpq passfile or secret injection avoids an inline password in the environment example.

The repository secret check rejects tracked private-key containers, environment files, private-key
markers, inline private setting values, credentialed database URLs, and common token prefixes. It
is a regression guard, not entropy analysis, provider-side revocation, or a replacement for an
organization secret-scanning service.

## TLS and proxy controls

Nginx rejects unknown cleartext hosts, rejects unknown TLS handshakes, and redirects the configured
HTTP host to its fixed HTTPS hostname. The template permits TLS 1.2 and 1.3 only; certificates and
private keys remain outside Git. Restrict private-key readability to the Nginx master and approved
certificate automation.

HSTS is intentionally commented. First prove the final hostname, certificate renewal, HTTP redirect,
subdomain ownership, and recovery path. Then start with a short `max-age` under change control.
Increase it only after observation; add `includeSubDomains` only when every subdomain is permanently
HTTPS. Do not preload an example or unproven domain.

The checked-in limits are conservative samples, not universal capacity claims:

| Boundary | Sample control |
| --- | --- |
| All clients | 20 concurrent proxy connections per source IP; 15-second body/keepalive and 30-second send bounds |
| Pre-auth token/account mutations | 32 KiB body; 5 requests/minute/IP with burst 5; 20-second upstream timeout |
| Analysis and saved-run uploads | 32 MiB total body; 10 requests/minute/IP with burst 3; 4 concurrent/IP; 130-second upstream timeout |
| Other API requests | 256 KiB body; 30-second upstream timeout |
| Application upload | 10 MiB per file, streamed and hashed; request-scoped temporary directory |
| Uvicorn | two workers; 16 active requests and backlog 64 per worker; five-second keepalive |

The example API memory ceiling is 3 GiB (frontend: 1 GiB). Argon2 verification uses 64 MiB per
active password check; two workers at 16 requests can require about 2 GiB for that work alone,
before Python, database pools, and parsing overhead. A smaller host must lower concurrency and
worker counts together, rather than copy these settings unchanged. A memory ceiling contains host
exhaustion but can still terminate a worker under load; this is not admission or capacity proof.

The 32 MiB proxy ceiling accommodates three 10 MiB files plus multipart overhead. Nginx may buffer
a body before FastAPI authorizes and streams it, so put the client-body temporary directory on a
restricted, monitored, encrypted filesystem with bounded capacity. FastAPI authenticates known
multipart routes before consuming their bodies and removes request directories after success,
validation failure, size rejection, and handled failure. Proxy limits and temporary-storage protections
also apply to unauthenticated submissions. Nginx rejects a total oversized body
before the per-file application rule can run.

Network/IP limits complement the PostgreSQL identifier buckets; neither replaces the other. Nginx
zones are local to an instance, NAT can group legitimate users, and distributed clients can evade
one address bucket. Measure representative traffic, CPU, memory, temporary storage, database pool
pressure, and false rejections before tuning. Do not remove all concurrency protection or silently
serialize the whole application.

## Forwarded headers, hosts, and process privilege

Nginx overwrites `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`, and
`X-Forwarded-Port`, and clears `Forwarded`; it never appends an internet-supplied forwarding chain.
The accepted public hostname and configured HTTPS port are preserved canonically. Unknown public hosts do
not reach either application. Uvicorn binds to loopback and accepts proxy headers only from
`127.0.0.1`:

```text
--proxy-headers --forwarded-allow-ips=127.0.0.1
```

Never use `--forwarded-allow-ips=*` on an exposed listener. If a load balancer is later placed in
front of Nginx, explicitly configure its address as the trusted real-IP source and retest the whole
chain. A local process on the server is inside this network trust boundary; operating-system access
control remains required.

Both systemd examples use the unprivileged `reconcile` account, explicit working directories,
loopback binding, restart-on-failure, a 30-second TERM shutdown window, file/task/memory ceilings,
private temporary directories, a restrictive umask, and a reviewed subset of systemd hardening.
They retain DNS, IPv4/IPv6, Unix sockets, and temporary storage needed for PostgreSQL, SMTP, Python,
and Next.js. Build/install artifacts before enabling `ProtectSystem=strict`; the services do not
write migrations or application source at startup.

## Liveness, readiness, and correctness

- `GET /health` is liveness only: the process can answer and reports its installed application
  version. It does not query dependencies.
- `GET /health/ready` concurrently probes both restricted database engines with configured connection
  and statement bounds. It returns `200 {"status":"ready"}` or a generic, no-store
  `503 {"status":"not_ready"}`. It never returns a URL, database error, tenant row, stack trace, or
  credential and never sends SMTP or mutates data.
- An authenticated release smoke is the business-path check. Readiness alone does not prove RLS,
  permissions, matching correctness, mail delivery, backups, or browser behavior.

Use liveness for process restart decisions and readiness for traffic admission. Alert on persistent
readiness failure, but investigate the identity and tenant pools separately through private operator
telemetry.

## Logging and response-header ownership

FastAPI emits one JSON operational event per request containing only the server-generated request
UUID, HTTP method, normalized route template, response status, elapsed milliseconds, and response
size. Literal UUID paths become templates. It does not log query strings, headers, cookies, bodies,
filenames, source values, notes, external references, idempotency keys, credentials, or report data.
Unexpected errors record only the exception class and request UUID.

The Nginx safe access format contains time, returned request UUID, method, status, bytes, and timing;
it omits the request target and all headers. Unknown-host access logging is off, and proxy error logs
are restricted to critical process events. Keep all log access and retention restricted because
timing and volume can still reveal business activity. Do not enable Uvicorn's default access format
or Nginx's combined format without a separate redaction review.

Next.js owns browser CSP, `nosniff`, Referrer-Policy, and Permissions-Policy. Nginx owns TLS and the
staged HSTS decision. FastAPI owns API `nosniff`, `no-referrer`, and sensitive-response `no-store`.
Proxy-origin body/rate/upstream errors use generic JSON, `nosniff`, and `no-store`. Do not add a second conflicting
CSP, `unsafe-eval`, broad script hosts, remote fonts, or wildcard origins to make a deployment pass.

## Release and migration procedure

Normal HTTP processes never run migrations. Use the following controlled order:

1. Record the release commit, package/frontend artifact hashes, PostgreSQL/client versions, owner,
   maintenance decision, and compatibility review.
2. Confirm the most recent backup/recovery point and its restore evidence meet the operator-approved
   objective. Take a new protected recovery point when required.
3. Stop or drain writes when the reviewed migration requires it. Do not expose migration credentials
   to systemd application units.
4. From an isolated operator session, set `DATABASE_URL` to the migration owner and run
   `alembic upgrade head`, then `alembic check`.
5. Verify the exact revision, ENABLE/FORCE RLS, application group grants, immutable triggers, indexes,
   and that runtime/identity logins remain non-owner, non-admin, and separated.
6. Install the reviewed API/frontend artifacts and render/validate Nginx. Start loopback services,
   then require readiness before admitting traffic.
7. Run the synthetic authenticated smoke below through HTTPS. Test configured SMTP delivery separately
   without putting token links in logs.
8. Observe error/status rates, latency, process/database resources, lock waits, and mail/backup signals
   through the change window. Record the promotion decision.

Schema compatibility is a release property, not implied by Alembic success. The current forward
migrations preserve earlier application data, but an older application must be checked against the
new exact schema before rollback.

## Rollback runbook

Application rollback and database downgrade are different decisions. Never make `alembic downgrade`
an automatic rollback step.

1. Contain traffic or writes and preserve request IDs, deployment events, sanitized process logs,
   revision, and database evidence.
2. If the schema is explicitly backward-compatible with the prior application, reinstall the prior
   signed/reviewed API and frontend artifacts, keep the current schema, restart gracefully, require
   readiness, run the smoke, and observe.
3. If compatibility is unknown or false, keep traffic contained. Choose a reviewed correct-forward,
   a new migration, or restoration of a pre-release recovery point. Restoration can discard
   post-backup changes and can revive old sessions/tokens, so incident and data owners must approve it.
4. Never run a destructive schema downgrade or restore over the live database. Rehearse in isolation,
   verify counts/security/contracts, and use a controlled cutover.
5. Document the cause, exact artifacts/revisions, data window, verification, and follow-up actions.

The deployment acceptance harness performs a graceful Nginx reload and Next.js TERM shutdown,
rejects an unbuilt candidate release, verifies frontend unavailability while API readiness remains
healthy, restores the known-good release link, and verifies frontend recovery. It deliberately does
not downgrade the database. This is an artifact-selection rehearsal, not proof that an arbitrary
older application is compatible with a future schema.

## Monitoring contract

No monitoring vendor is installed. Operators must collect sanitized signals and assign responders:

- request counts/statuses, especially sustained changes in `401`, `403`, `409`, `413`, `422`, and
  `5xx`; request and reconciliation latency; upstream timeouts; Nginx rate/connection rejections;
- authentication throttle activity, mail delivery failures, suspicious invitation/recovery use,
  and repeated cross-tenant/not-found patterns without recording identifiers or token links;
- API/Next/Nginx restarts, readiness state, CPU, memory, file descriptors, worker saturation, and
  temporary-volume usage;
- database connections/pool timeouts, query latency, deadlocks, lock waits, inventory contention,
  transaction age, storage/table/index growth, and role/grant/RLS drift;
- backup completion/integrity, protected-copy age, restore rehearsal age/result, certificate expiry,
  dependency alerts, and failed release smoke checks.

Numeric alerts require measured baselines and traffic objectives. Alert immediately on readiness loss,
repeated `5xx`, database exposure, role drift, backup failure, certificate-renewal failure, secret
leakage, unexpected owner/admin access, or evidence of tenant crossover. Trend capacity signals before
they become outages. Alerts must carry request IDs and event classes, not payloads.

## Operator release smoke

Use only an approved synthetic tenant and files. Record request IDs and results, not source bodies.

1. Confirm the public HTTPS certificate/hostname and HTTP-to-HTTPS redirect.
2. Read `/health` for the expected application version and require `/health/ready` to return 200.
3. Confirm migration revision `0008`, `alembic check`, role separation, RLS/grants/triggers, and private
   PostgreSQL reachability from the operator network only.
4. Sign in through Nginx, inspect Secure/HttpOnly/SameSite=Strict/Path=/ `__Host-` cookies, and select
   the synthetic organization if required.
5. Run the canonical synthetic three-way sample. Confirm 15 invoices, 17 invoice lines, 6 matched,
   11 review-required, and disputed EUR 2450.00, MAD 10199.00, USD 75.00.
6. Open History and the saved result; open Work and Dashboard; verify a MEMBER cannot use admin,
   inventory, or intelligence APIs.
7. As the approved role, read organization administration, inventory balances, selected-run
   procurement/supplier intelligence, and current-ledger inventory intelligence. Do not create real
   inventory or invitations for a smoke test.
8. Sign out, confirm the session is rejected, review sanitized logs/metrics, and record the decision.

The CI acceptance stack uses synthetic data, a one-run ephemeral certificate, Nginx, production Next,
production-configured Uvicorn, and PostgreSQL 17. It verifies HTTPS/redirects, same-origin routing,
cookies, login/session/logout, CSRF, tenancy, headers/no-store, forwarding, body/rate limits,
loopback sockets, readiness, canonical reconciliation, graceful restart, and log-marker absence:

```text
bash scripts/run_deployment_acceptance.sh
```

By default this disposable harness binds Nginx to `127.0.0.1:8080/8443`; build the frontend with
`NEXT_PUBLIC_API_BASE_URL=https://localhost:8443`. `PRODUCTION_E2E_HTTP_PORT` and
`PRODUCTION_E2E_HTTPS_PORT` override the proxy ports when needed. The renderer's production defaults
remain public IPv4 ports 80/443. An optional command argument vector can supply an external browser
runner; CI uses the normal local Playwright command.

It requires Linux, Nginx, OpenSSL, `ss`, Chromium/Playwright, a built frontend, installed Python
extras, and `TEST_DATABASE_ADMIN_URL` pointing to an explicitly disposable PostgreSQL server. The
ephemeral key is generated outside Git and removed afterward. This is evidence for the repository
profile, not a penetration test or public production certification.

The systemd units are reviewed examples; the acceptance test launches the server/proxy configuration
directly with one API worker. It does not apply systemd memory/task/file-descriptor limits or launch
those units. Validate account permissions, DNS, private DB/SMTP reachability,
temporary uploads, static assets, and any required Next cache writes on the actual target host before
enabling them. No real SMTP delivery, certificate renewal, firewall, backup schedule, or alerting
service is exercised by the disposable stack.

See the [backup/restore runbook](backup-restore.md), [incident response](incident-response.md), and
[final threat model](threat-model-final.md) before any customer-facing deployment.
