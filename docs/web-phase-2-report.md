# Web Phase 2 report

## Starting point

Web Phase 2 started from accepted `main` commit:

```text
a2d64af docs: record web phase 1 CI success
```

The starting tree had the completed Python core, CLI, reporting layer, and stateless FastAPI
adapter. It had no frontend, no browser-origin policy, and no frontend CI job. The reconciliation
engine, loaders, models, schemas, and reporting modules were treated as authoritative and were not
changed.

## Stack

The frontend was created with the current compatible toolchain available at implementation time.
Exact installed versions from `package-lock.json` and `npm ls --depth=0` are:

| Area | Package | Version |
| --- | --- | ---: |
| Runtime target | Node.js | 24.19.0 locally; 24.x in CI |
| Framework | Next.js | 16.3.4 |
| UI runtime | React / React DOM | 19.2.8 |
| Language | TypeScript | 5.9.3 |
| Styling | Tailwind CSS / PostCSS adapter | 4.3.3 |
| Component tooling | shadcn CLI | 4.21.0 |
| Primitives | radix-ui | 1.6.7 |
| Icons | lucide-react | 1.41.0 |
| Variants | class-variance-authority | 0.7.1 |
| Tests | Vitest | 4.1.11 |
| Test DOM | jsdom | 27.4.0 |
| React testing | @testing-library/react | 16.3.3 |
| User interaction testing | @testing-library/user-event | 14.6.7 |
| DOM assertions | @testing-library/jest-dom | 7.0.1 |
| Lint | ESLint | 9.39.5 |

The package declares `^22.22.2 || >=24.15.0` as its supported Node range. GitHub Actions uses
Node 24. A clean lockfile install completed, and the install audit found no known vulnerabilities.

## Architecture

The browser path keeps presentation, state, transport, and business decisions separate:

```text
src/app/page.tsx
        ↓
ReconciliationWorkspace
        ↓
useReconciliation (session state)
        ↓
reconcileFiles (typed HTTP boundary)
        ↓
POST /api/v1/reconcile
        ↓
FastAPI adapter → existing loaders → existing reconcile() → existing JSON report
```

The frontend uses the following responsibility-based structure:

```text
frontend/
├── .env.example
├── components.json
├── package.json
├── package-lock.json
├── vitest.config.mts
└── src/
    ├── app/
    │   ├── globals.css
    │   ├── layout.tsx
    │   └── page.tsx
    ├── components/
    │   ├── reconciliation/
    │   │   ├── disputed-amounts.tsx
    │   │   ├── file-input-card.tsx
    │   │   ├── file-upload-section.tsx
    │   │   ├── issue-overview.tsx
    │   │   ├── reconciliation-error.tsx
    │   │   ├── reconciliation-summary.tsx
    │   │   ├── reconciliation-workspace.tsx
    │   │   ├── results-table.tsx
    │   │   └── validation-issues.tsx
    │   └── ui/
    ├── constants/
    │   ├── issues.ts
    │   └── uploads.ts
    ├── hooks/
    │   └── use-reconciliation.ts
    ├── lib/
    │   ├── api/reconciliation.ts
    │   ├── config.ts
    │   ├── formatters.ts
    │   └── utils.ts
    ├── test/
    │   ├── fixtures/reconciliation.ts
    │   └── setup.ts
    └── types/
        └── reconciliation.ts
```

`page.tsx` remains a server component and only provides the restrained shell. The client boundary
starts at the workspace. React state is local to one reconciliation session; no global store or
browser persistence was introduced.

## Design decisions

shadcn/ui was chosen because its source-owned primitives provide accessible semantics without
forcing a second visual system or an enterprise data-grid dependency. Chakra, Material UI,
Bootstrap, and comparable component suites were not added. Only Button, Card, Alert, Badge, Table,
Select, and Separator primitives needed by the workflow were generated.

The visual direction is a calm procurement workspace rather than a landing page or fictional SaaS
dashboard. The shell has no sidebar, account controls, charts, notifications, or dead navigation.
It uses a restrained navy primary, green success, amber review, and destructive error treatments.
Colors, radius, borders, foregrounds, and focus rings are semantic tokens in `globals.css`; feature
components do not scatter raw color values.

The type system uses one system sans-serif stack and one system monospace stack for scannable
financial values. Spacing follows the Tailwind scale. Desktop results use compact summaries and a
wide operational table. Cards stack at narrow widths, controls remain readable, and the table
scrolls horizontally inside its bordered container rather than overflowing the page.

## API integration

`src/lib/config.ts` is the only source boundary that reads `NEXT_PUBLIC_API_BASE_URL`. It requires a
non-empty HTTP or HTTPS origin and strips URL duplication from feature components. The committed
`.env.example` supplies the local development value; no `.env.local` or secret is committed.

`src/lib/api/reconciliation.ts` owns the endpoint, request construction, response checks, and typed
error mapping. It sends:

```text
POST /api/v1/reconcile

purchase_orders
receipts
invoices
```

The multipart names and their presentation metadata live once in `constants/uploads.ts`. Browser
code does not set the multipart content-type header manually. It also does not parse CSV contents
or reproduce any reconciliation rule.

The exact report, summary, issue, and 18-field result-row contract is modeled in
`types/reconciliation.ts`. Financial values remain strings. Display formatting adds grouping
separators without converting values to JavaScript floating point, and no frontend financial
arithmetic exists. Summary issue counts and disputed amounts are rendered directly from the API.

Known API failures become a small discriminated error model:

- structured CSV validation (`422`)
- missing multipart fields (`422`)
- oversized upload (`413`)
- unavailable service or network failure
- unexpected server response (`5xx`)
- malformed successful response

The UI renders natural messages and never injects API strings as HTML.

## CORS strategy

The FastAPI adapter now accepts explicit origins through the testable `create_app()` argument or a
comma-separated `RECONCILE_ALLOWED_ORIGINS` environment variable. Values are normalized,
deduplicated, and required to be origin-only HTTP or HTTPS URLs.

No browser origin is enabled by default. Wildcard origins are rejected. Credentials are disabled,
and the CORS middleware allows only `POST` and the content-type header required by the multipart
request. Tests cover configured, unconfigured, environment-driven, direct-string, and wildcard
behavior. No Python core module was changed.

## Components

- `ReconciliationWorkspace` composes the workflow and moves focus to successful results.
- `FileUploadSection` presents the three inputs, privacy note, and guarded primary action.
- `FileInputCard` wraps a labeled native CSV input with selected, replace, and remove states.
- `ReconciliationSummary` renders the four authoritative counters.
- `IssueOverview` renders `summary.issue_counts` without deriving new counts.
- `DisputedAmounts` renders `summary.disputed_amounts` without recalculation.
- `ResultsTable` provides status, issue, and text filters over useful review columns.
- `ValidationIssues` groups structured source issues with row, column, value, and reason.
- `ReconciliationError` presents retryable and non-retryable request failures.
- `useReconciliation` owns files, loading, result, error, retry, and reset session state.

Unknown future issue codes remain visible through a readable fallback instead of crashing.

## UX states

| State | Behavior |
| --- | --- |
| Empty | Three clearly labeled source controls; primary action disabled. |
| Ready | Selected filenames and sizes remain visible; replace/remove actions are available. |
| Loading | `Reconciling…` text, spinner, live announcement, disabled inputs, and duplicate-submit prevention. |
| Success | Authoritative summary, issue counts, disputed totals, focused exceptions, filters, and table. |
| Validation error | Source, row, column, rejected value, and reason are grouped for review. |
| Upload too large | Clear file-specific guidance replaces a raw `413` status message. |
| Network error | Explains that FastAPI could not be reached and offers retry. |
| Server error | Generic processing failure without server internals, with retry. |
| Reset | `Start new reconciliation` clears files, result, error, loading state, and filters. |

## Testing

Frontend behavior is covered by 18 Vitest tests across the API boundary, workspace, formatter, and
presentation metadata. The suite covers the initial file workflow, exact FormData names, duplicate
submission prevention, success rendering, status and issue filtering, structured validation,
oversized uploads, network and server failures, malformed responses, reset, string-safe money
formatting, and unknown issue codes.

The final local acceptance commands are:

```text
npm run lint
npm test -- --run
npm run build
python -m pytest -vv
python -m ruff check .
python -m ruff format --check .
python -m pip check
python -m build
python -m reconcile --help
reconcile --help
```

Final local results:

```text
frontend: 18 passed, 0 failed
backend: 195 passed, 0 failed
lint: passed
Next.js production build: passed
Python Ruff, dependency, package build, and CLI smoke checks: passed
```

The only Python warning is an upstream Starlette/AnyIO deprecation notice already present in the
accepted stack.

## Manual browser verification

FastAPI and the Next.js development server were run together and exercised through the rendered
browser application.

- The empty state prevented submission until all three files were selected.
- Keyboard focus moved through Purchase orders, Goods receipts, and Invoices in workflow order.
- The sample files returned 15 invoices, 17 lines, 6 matched, and 11 review-required lines.
- Official disputed amounts displayed as EUR 2,450.00, MAD 10,199.00, and USD 75.00.
- Matched/review, issue, and text filters changed the visible result set correctly.
- An invalid purchase-order CSV exposed row 2, `ordered_quantity`, value `-3`, and its reason.
- With FastAPI stopped, the UI reported that the reconciliation service could not be reached.
- Desktop at 1440 × 900 and narrow layout at 390 × 844 had no page-level horizontal overflow.
  The wide result table remained readable through its own horizontal scroll container.
- Visual review found a restrained working application with prominent exceptions, scannable money,
  consistent spacing, visible focus treatment, and no fake controls or decorative effects.

## CI

The existing Python 3.11 and 3.12 job remains intact. A separate `frontend` job uses Node 24,
installs with `npm ci`, and runs lint, the Vitest suite, and the production build. The public build
configuration is provided in workflow environment configuration rather than application source.

The implementation was pushed through commit `5587d7a`. GitHub Actions run
[`34003810515`](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/34003810515)
completed successfully:

```text
Frontend     success
Python 3.11  success
Python 3.12  success
```

## Scope

Web Phase 2 remains intentionally stateless. It adds no database, accounts, authentication,
authorization, saved history, file persistence, analytics, charting, Docker layer, or frontend-side
reconciliation rules. The API still uses temporary request storage and the frontend holds one run
only in React memory.

## Remaining limitations

- Production exposure is not approved: there is no identity, authorization, HTTPS termination, or
  deployment-layer request limiting in this repository.
- Browser E2E and automated accessibility regression suites are not yet part of CI; the current
  phase uses component tests plus documented manual browser verification.
- Result rows prioritize review fields in a wide table; less-important contract fields are typed
  but do not yet have a row-detail view.
- The backend exposes no request progress, so loading is necessarily indeterminate.

## Next phase

Web Phase 3 should harden the completed stateless workflow with a small browser E2E suite covering
real uploads and failures, automated accessibility checks, large-file usability testing, and a
documented reverse-proxy/deployment profile with request-size, timeout, logging, and HTTPS controls.
Authentication, authorization, persistence, and public deployment should remain a separately
threat-modeled product phase rather than being added incidentally.
