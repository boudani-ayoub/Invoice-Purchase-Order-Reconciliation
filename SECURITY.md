# Security policy

## Scope

The project contains the V0.1 local CLI, an optional stateless FastAPI adapter, and a Next.js
frontend. They use the same deterministic reconciliation package and return terminal, JSON, CSV,
or browser-rendered reports. None executes input content or persists reconciliation data.

The process can read and write any path permitted to the operating-system user who runs it. Run
it with ordinary user privileges and review paths before using `--force`.

## Input and output safety

- CSV input is parsed as UTF-8 data with Python's strict CSV parser. Input text is never executed,
  evaluated, or interpolated into a shell command.
- Malformed CSV, invalid UTF-8, invalid schemas, and expected input filesystem errors become
  structured validation errors rather than tracebacks.
- Inputs and reconciliation records are held in memory. Python's CSV parser limits individual
  field size, but V0.1 sets no project-specific file-size or row-count limit. Very large files can
  exhaust local memory or take a long time to process.
- Detailed CSV reports preserve source identifiers exactly. Values beginning with `=`, `+`, `-`,
  or `@` may be treated as formulas by spreadsheet applications. Treat exported CSV as
  potentially untrusted data and import identifier columns as text. V0.1 does not prefix or alter
  values because doing so would break machine-readable round-trip fidelity.
- Report files use UTF-8. Existing files are refused unless `--force` is explicit. Non-forced
  writes use exclusive file creation to preserve this protection even if a destination appears
  after preflight.
- Forced single-file output is written and flushed to a same-directory temporary file before
  replacement. Forced CSV output stages both files before replacing either destination. The two
  final CSV replacements are separate filesystem operations, so the pair is not transactional;
  a failure during the second replacement can leave one new file and one old file.
- An interrupted non-forced write can leave a newly created partial file. The tool never silently
  overwrites that file on the next run.

## Web API boundary

- Each request uses a unique standard-library temporary directory with fixed internal filenames.
  Client filenames never determine server paths, and request files are removed on success, input
  validation failure, size failure, and unexpected application failure.
- `UploadFile` streams data to the controlled files in 64 KiB chunks. Each upload is limited to
  10 MiB and produces HTTP 413 when exceeded. The multipart server may receive or spool request
  data before the endpoint applies this limit, so a deployment still needs request-size and timeout
  controls at the ASGI server or reverse proxy.
- MIME types and filename extensions are not security checks. The existing strict UTF-8 CSV
  parser and schema validation remain authoritative. Structured validation failures return HTTP
  422 without exposing temporary server paths.
- Unexpected failures return a generic HTTP 500 payload. Detailed exceptions remain in server
  logs rather than HTTP responses.
- Browser access is denied by default. `RECONCILE_ALLOWED_ORIGINS` accepts a comma-separated list
  of exact HTTP or HTTPS origins. Wildcards are rejected, credentials are disabled, and the CORS
  policy permits only the reconciliation `POST` method and its content-type header.
- The API has no database, upload storage, result history, authentication, or authorization. It is
  intended for local development and trusted environments only.
- Do not expose the MVP anonymously to the public internet with sensitive financial data. A
  production deployment requires HTTPS, explicit trusted origins, authentication and
  authorization, deployment-layer request limits, timeouts, logging controls, and a new threat
  review.

## Frontend boundary

- `NEXT_PUBLIC_API_BASE_URL` is intentionally browser-visible configuration and accepts only an
  HTTP or HTTPS origin. It must never contain tokens, passwords, or other secrets.
- `NEXT_PUBLIC_RECONCILIATION_TIMEOUT_MS` is public build configuration. It defaults to 120 seconds
  and must be a positive integer. Timing out aborts the browser request; it does not terminate work
  already executing in FastAPI. A retry can overlap with that work, although the current operation
  is stateless and creates no payment or persistence side effect.
- Uploaded files and reconciliation responses stay in the current React session. The frontend
  does not write them to local storage, session storage, IndexedDB, or a database; refreshing or
  starting a new reconciliation clears the current state.
- Browser filename and MIME hints improve usability only. FastAPI and the strict Python loaders
  remain the validation and size-enforcement boundary. The frontend intentionally has no second
  file-size constant that could drift from the API limit.
- The frontend renders API strings as text and does not inject returned values as HTML.
- Next.js emits a focused CSP (`base-uri`, `frame-ancestors`, and `object-src`), `nosniff`, a strict
  origin referrer policy, and a restrictive permissions policy. TLS termination and HSTS belong to
  the deployment proxy. A broader script/style/connect CSP requires a deployment-specific policy
  and must not be approximated with unsafe directives or broad wildcards.
- The application loads no remote fonts, scripts, analytics, or other third-party browser assets.
- There are no user accounts, tokens, or authentication flows. The current frontend does not make
  anonymous public deployment appropriate.

## Optional persistence boundary

The `db` extra adds PostgreSQL infrastructure under `reconcile.persistence`. It is not imported by
the CLI or stateless HTTP handlers, and uploads/results are not saved by current workflows.
There are no public organization, user, invoice, run-history, or other company-data CRUD routes.

Tenant tables carry organization ownership, composite foreign keys, and ENABLE/FORCE RLS policies
with both read and write predicates. Missing transaction context fails closed. `tenant_session`
uses bound transaction-local context, tested across committed and rolled-back transactions on a
reused connection. It accepts an already verified organization UUID; it does not establish identity
or membership. Phase 2 must derive that context from authenticated authorization. A browser-supplied
organization ID is only a selector.

The provisioned runtime role does not own tables and must not have superuser/BYPASSRLS. It has no
users access, identity-management writes, schema creation, DELETE, or TRUNCATE privileges. Schema
migrations use a separate role. `DATABASE_URL` stays private and configuration errors do not reveal
its value. Financial fields use finite NUMERIC/Decimal constraints. Duplicates and unresolved
references are retained as evidence; discrepancies are not rejected by agreement constraints.

No raw uploaded bytes or temporary paths are stored. Result snapshots carry explicit versions and
cannot be mutated through ordinary SQL, including privileged row UPDATE/DELETE. Future retention
and audit operations need a deliberately authorized policy. Table owners/superusers still control
DDL and can disable protections; database administration is a separate trust boundary.

See [data-model-v1.md](docs/data-model-v1.md) and the
[ASVS 5.0 security roadmap](docs/security-roadmap.md). Reviewing that checklist is not certification
or a claim of production security. Database RLS does not protect unauthenticated HTTP traffic.

## Dependencies and data

The core application has no third-party runtime dependencies. FastAPI, Uvicorn, and multipart
parsing are isolated in the optional `web` dependency group; HTTP testing tools remain in `dev`.
Dependabot monitors these packages and GitHub Actions weekly. The files under
`examples/sample_data` are deterministic synthetic fixtures, not customer or supplier records.

## Reporting a vulnerability

Avoid including sensitive data in a public issue. Use the repository's private vulnerability
reporting option under the GitHub **Security** tab when available. Otherwise, contact the
repository owner through the GitHub profile to agree on a private reporting channel.

A future public deployment with authentication, authorization, and persistence will require a
separate threat model. This policy does not claim production readiness or compliance certification.
The current reverse-proxy baseline and its remaining requirements are documented in
[`docs/deployment.md`](docs/deployment.md).
