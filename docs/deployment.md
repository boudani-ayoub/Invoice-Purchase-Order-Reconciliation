# Deployment profile

## Readiness boundary

The current application is a hardened stateless MVP, not an anonymous public financial service.
It has no authentication, authorization, tenant isolation, rate limiting, persistence, or audit
trail. Keep it on a trusted network until those controls have a dedicated threat model.

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

Comma-separated additional trusted origins are supported. Wildcards and credentialed CORS are not.

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

Authentication, authorization, rate limits, CSRF assumptions, audit events, data retention, and
incident response must be designed before this profile is considered internet-facing production.
