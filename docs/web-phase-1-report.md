# Web Phase 1 Completion Report

Date: 2026-09-05

Project: Invoice / Purchase Order Reconciliation

Scope: Optional stateless FastAPI backend MVP

## Outcome

Web Phase 1 adds a small HTTP adapter around the completed V0.1 core package. It accepts three
multipart CSV uploads, processes them in a request-scoped temporary directory, and returns the
existing Phase D JSON report. The core loaders, reconciliation engine, summary calculation,
reporting schema, CLI arguments, and CLI output behavior were not changed.

No frontend, database, authentication, persistence, queue, OCR, ML, ERP integration, Docker, or
deployment configuration was added.

## Starting point

Work started on clean, pushed `main` at:

```text
2583150 docs: record phase F CI success
```

The accepted core CI was green on Python 3.11 and 3.12 before web work began.

## Architecture

The API pipeline is:

```text
multipart UploadFile streams
        ↓
request-scoped TemporaryDirectory
        ↓
fixed internal CSV filenames
        ↓
existing Phase B loaders
        ↓
existing reconcile()
        ↓
existing render_json_report()
        ↓
HTTP application/json response
        ↓
temporary directory cleanup
```

`src/reconcile/web/app.py` is the only application module. It exposes `create_app()` for tests and
`app` for Uvicorn. `reconcile/__init__.py` and the CLI do not import the web package. There is no
global mutable request state.

The adapter calls these accepted public functions directly:

```text
load_purchase_orders
load_goods_receipts
load_invoices
reconcile
render_json_report
```

No business rule, issue count, disputed-total calculation, or JSON field mapping is duplicated.

## Dependencies

The base distribution still declares no required runtime dependencies.

The optional groups are:

```text
web
  fastapi>=0.141,<1
  python-multipart>=0.0.32,<1
  uvicorn>=0.52,<1

dev
  build>=1.2,<2
  httpx2>=2.12,<3
  pytest>=7.4,<9
  ruff>=0.6,<1
```

The current Starlette test client prefers `httpx2`; using the older `httpx` package produced an
explicit deprecation warning, so Web Phase 1 uses the supported development dependency. No
`fastapi[all]` convenience extra was added.

The wheel metadata exposes `dev` and `web` extras separately. Installing the wheel with
`--no-deps` in a clean environment successfully imported `reconcile`, ran the CLI, and completed
the sample workflow while FastAPI was absent.

## API contract

### `GET /health`

Returns HTTP 200 with `application/json`:

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

The version comes from installed distribution metadata and is not duplicated as an application
constant.

### `POST /api/v1/reconcile`

Required multipart upload fields:

```text
purchase_orders
receipts
invoices
```

The endpoint returns HTTP 200 and the exact UTF-8 bytes produced by
`render_json_report(results, summary)`. A regression test also asserts that parsed API JSON equals
`json.loads(render_json_report(results, summary))`.

### Errors

Core CSV validation errors return HTTP 422:

```json
{
  "error": "validation_error",
  "message": "Uploaded CSV data failed validation.",
  "issues": [
    {
      "file": "purchase_orders",
      "source": "purchase_orders.csv",
      "row": 2,
      "column": "ordered_quantity",
      "value": "-3",
      "reason": "ordered_quantity must be a finite decimal greater than zero"
    }
  ]
}
```

An oversized upload returns HTTP 413:

```json
{
  "error": "file_too_large",
  "file": "invoices",
  "max_bytes": 10485760
}
```

A missing multipart field uses FastAPI's HTTP 422 request-validation structure. Its relevant entry
is stable at the field boundary:

```json
{
  "type": "missing",
  "loc": ["body", "invoices"],
  "msg": "Field required",
  "input": null
}
```

An unexpected internal failure returns HTTP 500 without exception or path detail:

```json
{
  "error": "internal_error",
  "message": "Internal server error."
}
```

The full exception remains available to server logging.

## Upload security decisions

- `UploadFile` is consumed once in 64 KiB chunks; the endpoint never performs an unbounded
  `await upload.read()`.
- The application enforces 10 MiB per uploaded file. Tests inject a smaller limit without changing
  the production default.
- Every request gets a unique `TemporaryDirectory` and only the fixed names
  `purchase_orders.csv`, `goods_receipts.csv`, and `invoices.csv` are written.
- Client filenames are ignored for path construction. Traversal names using both slash styles and
  a misleading executable extension still process only through the controlled paths.
- Temporary directories are removed after success, CSV validation failure, size failure, and
  unexpected application failure. `UploadFile` resources are closed in a `finally` block.
- Extensions and client-provided MIME types are not treated as security controls. Strict core CSV
  parsing remains authoritative.
- Outward validation issues derive from structured `CsvValidationIssue` attributes. Only the fixed
  source basename is exposed; random temporary paths never enter the payload.
- There is no database, upload folder, result store, or history.
- No CORS middleware is enabled because there is no frontend yet.
- No authentication or authorization is implemented. The service is not suitable for anonymous
  public deployment with sensitive financial data.
- The endpoint limit does not prevent the ASGI multipart layer from receiving or spooling request
  data first. A production edge still needs body-size limits, timeouts, HTTPS, logging controls,
  authentication, and explicit trusted origins.

## Tests

Ten Web Phase 1 test cases cover:

- health status and authoritative package version;
- built-in Swagger/OpenAPI availability and multipart/JSON media declarations;
- exact sample renderer equivalence and all accepted issue/totals;
- structured invalid-CSV errors without temporary paths;
- each missing multipart field and proof that reconciliation does not run;
- deterministic HTTP 413 behavior and proof that reconciliation does not run;
- client filename/path traversal resistance;
- temporary cleanup after success, validation, size, and internal failure;
- generic internal-error responses without sensitive exception text.

All 180 accepted core tests remain unchanged and pass. Final local result:

```text
190 passed
0 failed
```

Current Starlette 1.6.0 emits one upstream `anyio.abc.BlockingPortal` deprecation warning while
importing its test client. The project does not call that deprecated alias, and no transitive
dependency was pinned or warning hidden solely to silence it.

## Verification

Verification used Python 3.12.7:

| Command | Result |
| --- | --- |
| `python -m pip install -e ".[dev,web]"` | Passed |
| `python -m pytest -vv` | Passed: 190 passed, 0 failed |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed: 37 files already formatted |
| `python -m pip check` | Passed: no broken requirements |
| `python -m build` | Passed: sdist and universal wheel built |
| clean wheel install with `--no-deps` | Passed |
| clean core import with FastAPI absent | Passed |
| clean core CLI help and sample workflow | Passed |
| `reconcile --help` | Passed |
| `python -m reconcile --help` | Passed |
| `git diff --check` | Passed |
| `git diff --cached --check` | Passed |

The GitHub workflow now installs `.[dev,web]` on both Python 3.11 and 3.12, while its clean wheel
smoke remains dependency-free and explicitly imports the core package. These changes have not been
pushed, so remote Web Phase 1 CI has not run.

## Manual backend verification

Uvicorn was started without reload on `127.0.0.1:8000`. Real HTTP requests produced:

```text
GET  /health            200 application/json, status=ok, version=0.1.0
GET  /docs              200 text/html, Swagger UI present
POST /api/v1/reconcile  200 application/json, 17 results
```

The multipart request used the three repository sample CSVs. The server was terminated afterward,
and port 8000 was verified closed.

## Accepted business regression

The direct core pipeline, API test client, live Uvicorn request, and core-only wheel smoke all
preserve:

```text
invoices: 15
invoice lines: 17
matched: 6
review required: 11

UNKNOWN_PO=1
UNKNOWN_ITEM=1
DUPLICATE_INVOICE=2
SUPPLIER_MISMATCH=1
CURRENCY_MISMATCH=1
MISSING_RECEIPT=1
QUANTITY_EXCEEDS_PO=2
QUANTITY_EXCEEDS_RECEIPT=2
PRICE_MISMATCH=1

EUR=2450.00
MAD=10199.00
USD=75.00
```

`ReconciliationSummary.disputed_amounts` remains the only source of official totals.

## Limitations

- There is no frontend, authentication, authorization, database, persistence, or run history.
- The local Uvicorn command does not supply HTTPS or production process management.
- Application upload limits need matching reverse-proxy or server limits in deployment.
- Multipart parsing occurs before endpoint-level size enforcement.
- Requests use in-process CPU and file handling without quotas or workload isolation.
- There is no rate limiting, audit trail, secrets management, monitoring, or retention policy.
- The accepted core limitations for returns, credit notes, tax, freight, as-of-date processing,
  receipt findings, and whole-document duplicate identity remain.

## Next step

Web Phase 2 should add a frontend only: select the three CSVs, perform client-side presence and
10 MiB usability checks, submit multipart data to this API, display validation issues by source and
row, and render summary totals plus detailed reconciliation results. It should add explicit local
development CORS origins when required. It should not add authentication, persistence, or change
core reconciliation rules unless those become a separately defined later phase.
