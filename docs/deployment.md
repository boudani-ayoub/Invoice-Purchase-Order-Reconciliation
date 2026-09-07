# Deployment profile

## Readiness boundary

The product now has first-party authentication, server-side sessions, tenant authorization, CSRF,
and PostgreSQL-backed identifier throttles. Analysis files/results remain request-scoped. This is
not approval for a public financial service: network resource limits, operational recovery,
deployment-specific threat review, and monitoring are still required. Business history and
actor-aware audit events are not implemented. See [the auth threat model](threat-model-auth.md).

The preferred topology uses one public HTTPS origin:

```text
Browser
   ↓ HTTPS
Nginx
   ├── /api/* → Uvicorn / FastAPI on 127.0.0.1:8000
   └── /*     → next start on 127.0.0.1:3000
```

This same-origin arrangement removes the need for cross-origin browser access. Build the frontend
with the public origin, not a private loopback address:

```bash
NEXT_PUBLIC_API_BASE_URL=https://reconcile.example.com npm run build
```

`NEXT_PUBLIC_*` values are embedded in browser assets at build time and are not secrets. Changing
them requires a new frontend build. `NEXT_PUBLIC_RECONCILIATION_TIMEOUT_MS` defaults to `120000`.

## Nginx example

Replace the hostname and certificate paths before use. Enable HSTS only after HTTPS is stable for
the entire hostname.

```nginx
server {
    listen 80;
    server_name reconcile.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name reconcile.example.com;

    ssl_certificate     /etc/letsencrypt/live/reconcile.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/reconcile.example.com/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location /api/ {
        client_max_body_size 32m;
        proxy_connect_timeout 5s;
        proxy_send_timeout 130s;
        proxy_read_timeout 130s;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

The 32 MiB proxy ceiling covers three files at the 10 MiB application limit plus multipart
overhead. It is a total request limit, while FastAPI enforces 10 MiB on each file. Keep both layers:
the multipart server or proxy can receive or spool bytes before the endpoint rejects one file.
Protect proxy and operating-system temporary storage with restrictive permissions, bounded space,
short retention, and encrypted disks where sensitive files are permitted.

The 130-second API proxy timeout is slightly longer than the default 120-second browser wait. A
browser abort does not cancel server-side reconciliation, and the current API exposes no cancellation
protocol. Do not label the timeout as cancellation. Tune all three layers together after measuring
representative files rather than simply increasing them without a resource budget.

## Processes and forwarded headers

Run both services as an unprivileged dedicated account and bind them to loopback. A supervisor such
as systemd should start them after networking, restart unexpected failures, apply memory and file
limits, and collect logs. Representative commands are:

```bash
python -m uvicorn reconcile.web.app:app \
  --host 127.0.0.1 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips=127.0.0.1

npm run start -- --hostname 127.0.0.1 --port 3000
```

Trust forwarded headers only from the actual proxy address. Do not use `*` for
`--forwarded-allow-ips` on an exposed listener. Monitor `GET /health` internally, but do not treat
it as proof that authentication, authorization, or downstream policy is correct.

For a deliberately separate frontend and API origin, build with the exact public API origin and set
the API process environment to the exact frontend origin:

```text
NEXT_PUBLIC_API_BASE_URL=https://api.reconcile.example.com
RECONCILE_ALLOWED_ORIGINS=https://app.reconcile.example.com
```

Also set `FRONTEND_PUBLIC_URL` to the trusted frontend origin. Comma-separated additional trusted
origins are supported. GET/POST credentialed CORS allows Content-Type and X-CSRF-Token only for
the explicit allow-list; wildcards are rejected. Separate hosts must be same-site over HTTPS for
SameSite=Strict cookies. Unrelated cross-site frontend/API deployments are not supported by this
cookie policy. Prefer the same-origin topology instead of weakening the cookies.

## Security headers and browser resources

Next.js owns the focused CSP and static browser headers in `next.config.ts`. Nginx owns transport
controls such as TLS and HSTS. Avoid sending duplicate CSP headers from both layers because browsers
enforce every policy and an accidental conflict can break the application.

The repository has no third-party fonts, scripts, analytics, or CDNs. A stricter deployment CSP that
adds `default-src`, `script-src`, `style-src`, or `connect-src` must account for the selected API
origin and Next.js rendering mode. Use nonces or reviewed hashes when that policy is introduced;
do not add broad host wildcards or `unsafe-eval` to make a broken production policy pass.

## Logging and operations

- Log request time, route, status, response size, and a generated correlation identifier.
- Do not log multipart bodies, CSV rows, response reports, filenames, query strings, or request
  headers that may contain credentials.
- Restrict log access and retention as financial metadata may still be inferable from timing and
  request volume.
- Alert on repeated `413`, `422`, `5xx`, timeouts, restarts, memory pressure, and temporary-volume
  exhaustion without copying uploaded content into alerts.
- Rotate logs and test recovery, graceful restart, deployment rollback, and temporary-file cleanup.
- Keep Nginx, Node.js, Python, FastAPI, Uvicorn, and multipart dependencies patched. Run `npm audit`,
  `python -m pip check`, the test suites, and the production build before promotion.

Network/IP rate limits, bounded concurrency, audit/retention, and incident response must be
operational before this profile is considered internet-facing production. Account buckets alone
cannot stop an attacker rotating identifiers. Never derive trusted IPs from arbitrary forwarded
headers. Apply a small auth-location body limit and suitable proxy connection/timeout limits in
addition to the application's 16 KiB JSON bound; multipart may be parsed/spooled before route
dependencies reject unauthorized analyses.

## Required private authentication configuration

The four `/api/v1/analyses/*` routes and legacy `/api/v1/reconcile` share the same upload boundary.
The 32 MiB total proxy ceiling accommodates the three-file mode; two-file routes declare only
their required inputs. Only the CLI can run without a database URL or optional packages.

Database development and migration commands are in [database-development.md](database-development.md).
Provision separate migration, identity, and tenant-runtime logins. Set `DATABASE_URL` to the
runtime login and `IDENTITY_DATABASE_URL` to the identity login only after owner-run migrations.
HTTP startup rejects owner/admin/both-group connections. Keep PostgreSQL private, authenticate
with strong unique credentials, and use `sslmode=verify-full` with an appropriate trust root for
remote connections. Never expose database or SMTP settings through `NEXT_PUBLIC_*`.

Use [the backend example](../.env.example) as a checklist, not working production credentials:

- Explicit `APP_ENV=production`; `FRONTEND_PUBLIC_URL` and trusted origins use HTTPS.
- A privately generated `AUTH_CSRF_SECRET` of at least 32 random bytes, URL-safe base64. All
  workers must share it. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  in a private setup session, not build logs. Rotation invalidates existing CSRF proofs;
  bootstrap gets a fresh proof. Revoke sessions separately for a session-compromise response.
- `AUTH_REQUIRE_VERIFICATION=true`; `AUTH_MAIL_MODE=smtp`; SMTP host/sender and either SSL
  (default port 465) or STARTTLS (configure the provider's port), with certificate validation.
  Store SMTP credentials in the platform secret manager. Send a real verification/recovery test
  before release. Startup validates configuration, not provider delivery or DNS authentication.
- Default 30-minute idle / 12-hour absolute sessions, 24-hour verification and 30-minute reset
  tokens. Login allows five attempts per identifier per 15 minutes; registration, resend, and
  recovery each allow three per hour. Tune using measured resource budgets.
- `AUTH_DOCS_ENABLED=false` by default in production; `AUTH_REGISTRATION_ENABLED=false` can close
  public registration without disabling existing accounts.

Production cookies are Secure, HttpOnly, SameSite=Strict, Path=/, no Domain, and __Host-prefixed.
Use a single browser-facing hostname consistently in HTTP development too. Mail can be disabled
only in explicit development with verification disabled; no secret links are printed or delivered.

API identity/report/error responses use no-store. Do not log Cookie, Set-Cookie, Authorization,
X-CSRF-Token, bodies, or query strings. Avoid SQL echo and driver parameter logging. PostgreSQL
error DETAIL can contain failed row values: restrict database logs, use terse error verbosity and
disable parameter logging (`log_parameter_max_length=0`, `log_parameter_max_length_on_error=0`)
as appropriate for the deployed cluster; see [PostgreSQL logging settings](https://www.postgresql.org/docs/17/runtime-config-logging.html).
Mail-provider and browser trace artifacts need equivalent
access/retention controls. Error-class-only application logging deliberately sacrifices detailed
tracebacks; use sanitized operational metrics for diagnosis.

Expired session/token/throttle records are not automatically purged in Phase 2. Plan bounded,
privileged retention jobs and monitor table/index growth before public exposure; normal HTTP roles
have no DELETE privilege. Back up account state and test recovery with dedicated operator access.
