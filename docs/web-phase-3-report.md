# Web Phase 3 report

## Starting point

Web Phase 3 started from accepted `main` commit:

```text
14014ce docs: record web phase 2 CI success
```

The starting tree contained the complete V0.1 engine and CLI, the stateless FastAPI adapter, and
the typed Web Phase 2 interface. The tree was clean and matched `origin/main`. Reconciliation,
allocation, reporting, and CSV validation rules remained authoritative and were not changed.

## Scope and decisions

The phase hardens the existing stateless workflow without adding accounts, storage, analytics, or
new business rules. Ambiguous implementation choices were resolved as follows:

- Playwright runs Chromium against a production `next start` build and a real Uvicorn process.
  The default loopback origins are `http://127.0.0.1:3010` and `http://127.0.0.1:8010`.
- Test hosts, ports, and the Python executable are environment-overridable. They are centralized in
  `e2e/environment.ts` and `playwright.config.ts`, not repeated through feature tests.
- FastAPI remains the only authority for the 10 MiB per-file limit. The browser has no duplicated
  preflight limit that could drift from the API response.
- The browser waits 120 seconds by default. `AbortController` stops the browser request when that
  limit is reached, but it is explicitly not a server-side cancellation feature.
- Automated service unavailability uses a deterministic connection-refused route abort because the
  shared real backend serves the rest of the suite. A manual pass separately stopped the actual API
  process and confirmed recovery after restart.
- Next.js owns a focused, static browser-header baseline. TLS and HSTS belong to the reverse proxy.
  A broader script/style/connect CSP is deferred until its deployment origin and nonce/hash strategy
  are known; no unsafe directive or wildcard was added to simulate completeness.

## Browser test architecture

The frontend adds `@playwright/test` 1.63.0 and `@axe-core/playwright` 4.13.0. The configuration uses
one Chromium worker to avoid port and large-file contention. Failed tests retain trace, screenshot,
and video artifacts under ignored directories.

```text
Playwright Chromium
       ├── http://127.0.0.1:3010 → next start
       └── http://127.0.0.1:8010 → Uvicorn / FastAPI
                                           ↓
                         existing loaders → reconcile() → JSON report
```

The cross-origin test topology proves the configured CORS path in an actual browser. CI sets
`NEXT_PUBLIC_API_BASE_URL` before the production build and supplies `E2E_PYTHON_EXECUTABLE=python`.
Local Windows runs use the repository virtual environment by default.

The ten browser tests cover:

- actual sample uploads and the accepted 15-invoice, 17-line result;
- default review-first rendering, status filter, issue filter, text search, and restoration of all
  rows;
- native file removal and reselection, result focus, and full reset;
- structured invalid-CSV feedback from FastAPI;
- one near-limit valid upload and duplicate-submit prevention while it is running;
- authoritative `413` details, file replacement, and successful retry;
- a browser network failure followed by retry against the real API;
- long multilingual identifiers and page-level overflow at 390 × 844;
- expected security response headers on the production page;
- axe checks for initial, ready, successful, and validation-error states.

Selectors use visible roles, labels, names, and state text. They do not depend on generated class
names, timing sleeps, or mocked report payloads.

## Accessibility

axe runs on four meaningful application states. The enforced threshold is `serious` and `critical`;
lower severities remain review information rather than silently changing the acceptance threshold.
All four final scans contain zero violations at the enforced severities.

The first scan of the successful results exposed a real 4.0:1 contrast failure on destructive issue
badges. The badge now uses an explicit destructive foreground token on a solid destructive
background and passes the automated check. Native labels, live regions, table semantics, pressed
status controls, and focused result navigation remain intact.

## Upload and resource boundaries

Large fixtures are generated at runtime inside Playwright output directories and are never committed:

| Scenario | Generated size | Expected result |
| --- | ---: | --- |
| Large valid purchase-order CSV | 9,506,549 bytes | HTTP 200 and the normal report |
| Oversized purchase-order CSV | 10,485,761 bytes | HTTP 413 naming the field and 10 MiB limit |

The valid file extends the real purchase-order sample with unique, schema-valid rows and bounded
individual fields. It stays close to the limit while remaining fast enough for CI. The oversized
file is rejected during streamed upload before CSV parsing. Replacing it with the sample file and
retrying succeeds in the same browser session.

The client intentionally does not inspect file size. This avoids a second security boundary and
keeps the backend payload authoritative. Deployment still needs a total-body ceiling because three
allowed files plus multipart overhead can exceed 30 MiB.

## Timeout and recovery

`NEXT_PUBLIC_RECONCILIATION_TIMEOUT_MS` is validated as a positive integer and defaults to
`120000`. The API client passes an abort signal to `fetch`, clears its timer on every outcome, and
maps expiration to a separate human-readable timeout state with retry.

The timeout only ends the browser's wait. Uvicorn may still be reading or reconciling the request,
so the UI says that processing may continue. No Cancel button is shown and the deployment guide
keeps proxy timeouts slightly longer than the browser timeout.

## Security and deployment review

`next.config.ts` now sends:

```text
Content-Security-Policy: base-uri 'self'; frame-ancestors 'none'; object-src 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), geolocation=(), microphone=()
```

HSTS is not sent by the application because local HTTP remains supported and the TLS terminator must
own that policy. The frontend loads no remote fonts, scripts, analytics, CDNs, or other third-party
resources.

`docs/deployment.md` supplies a same-origin Nginx profile with HTTPS redirection, a 32 MiB total API
body ceiling, aligned timeouts, standard proxy headers, loopback upstreams, and explicit forwarded-
header trust. It also records process-supervision, logging, temporary-storage, health-check, patching,
and separate-origin CORS guidance. The document repeats that the unauthenticated MVP is not approved
for anonymous internet exposure.

The dependency and secret review found:

- `npm audit --audit-level=high`: zero known vulnerabilities;
- clean `npm ci` from the committed lockfile;
- `python -m pip check`: no broken requirements;
- no credential-shaped values or private-key blocks in project content;
- no committed runtime-generated browser artifacts or large test fixtures;
- no secrets in either `NEXT_PUBLIC_*` variable.

The clean install reports that ESLint 9.39.5 has reached end of support. ESLint 10 was evaluated,
but the import, JSX accessibility, and React plugins bundled by `eslint-config-next` 16.3.4 still
declare peer support only through ESLint 9. The final lock therefore keeps the valid peer graph
instead of forcing ESLint 10; upgrading the Next lint stack is a recorded maintenance item. This is
a tooling-support warning, not an `npm audit` vulnerability.

## CI

The existing Python 3.11 and 3.12 jobs remain unchanged. The frontend job now also:

1. installs Python 3.12 and the `web` extra;
2. installs Chromium and its Linux dependencies;
3. builds with the dedicated test API origin;
4. runs the production Next.js server and Uvicorn through Playwright;
5. executes E2E and axe coverage in Chromium.

No browser report, trace, screenshot, video, generated CSV, `.env.local`, or build output is
committed. Remote CI remains pending until this local commit is explicitly pushed.

## Verification

Final local results:

```text
Python tests:                         195 passed, 0 failed
Frontend Vitest:                      20 passed, 0 failed
Playwright Chromium + axe:            10 passed, 0 failed
Ruff lint:                            passed
Ruff formatting:                      passed (42 files)
ESLint:                               passed
Next.js production build/start:       passed
pip dependency check:                 passed
npm audit:                            0 vulnerabilities
Python source/wheel build:             passed
CLI entry points and sample report:    passed
```

The only Python warning is the accepted upstream Starlette use of a deprecated AnyIO alias.

## Manual browser verification

The production frontend and real API were inspected through the browser at normal desktop width and
390 × 844:

- all three native file controls exposed clear accessible names and selected file details;
- Tab reached the submit control, Enter submitted, and focus moved to the result heading;
- summary cards, issue counts, disputed totals, filters, and table labels were visually coherent;
- the mobile cards and controls stacked without page-level horizontal overflow;
- the wide result table scrolled independently from identifiers through financial totals;
- stopping the real API produced the network message and retry control;
- restarting the API and selecting Try again returned the complete report without reselecting files.

The browser viewport was reset and the temporary services were stopped after verification.

## Remaining limitations

- There is no authentication, authorization, rate limiting, tenant isolation, persistence, or audit
  trail.
- The API exposes no upload progress or server-side cancellation endpoint.
- A request can continue after the browser times out, and retrying can temporarily duplicate compute
  work even though reconciliation has no persistence side effect.
- The proxy example is a baseline, not infrastructure-as-code or a claim of production readiness.
- A full resource CSP needs a deployment-specific origin and nonce/hash design.
- The core CLI still has no project-specific total file-size or row-count limit.
- The accepted Next.js lint plugin set still constrains the project to end-of-support ESLint 9.

A future phase should start with identity, data retention, authorization, rate limits, and an updated
threat model before adding saved runs or public deployment.
