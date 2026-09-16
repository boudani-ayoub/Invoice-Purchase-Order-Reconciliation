# Intelligence threat review

This review covers Product Phase 8's read-only procurement, supplier, and inventory intelligence.
It records application boundaries and tested controls, not a production-readiness claim.

## Assets and trust boundaries

Intelligence exposes same-organization business labels, exact financial values, issue mixes,
receipt observations, inventory balances, and ledger activity. Counts and aggregates are sensitive
even when no source row is returned. The browser is untrusted. FastAPI must authenticate the live
session and membership, authorize `VIEW_INTELLIGENCE`, then open a transaction-local tenant context;
forced PostgreSQL RLS remains defense in depth.

Procurement truth is an immutable selected-run snapshot plus that run's source set. Inventory truth
is the explicit append-only stock ledger. Joining them by inference would create false provenance.

## Reviewed threats and controls

| Threat | Control and verification | Residual risk |
| --- | --- | --- |
| Aggregate tenant leakage | Every source, snapshot, finding, label, operation, and movement query includes organization scope under forced RLS. Tenant-switch and foreign-run tests cover counts, sums, names, timing, positions, and activity. | A schema owner/superuser or arbitrary SQL compromise is outside RLS's application-isolation guarantee. |
| Run UUID IDOR | The selected run query requires current organization, `COMPLETED`, and an immutable snapshot. Foreign/non-completed IDs return `404` after permission checks; malformed UUIDs receive framework validation failure. | UUID secrecy is not a control; authorization and RLS must remain intact. |
| Supplier UUID or source-code leakage | The API has no supplier-detail UUID route. Supplier identities come only from the selected run's source codes; the bounded label lookup is organization-scoped. Unresolved codes remain unresolved. | Supplier codes/names are sensitive business data and must be protected in logs and exports. |
| Stale membership or role downgrade | Every request re-authenticates and rechecks the active membership and explicit role map. MEMBER is denied; AP_MANAGER and ORG_ADMIN are allowed. Live downgrade/archive tests prove immediate denial. | A response already returned cannot be recalled. Session lifecycle monitoring remains deployment work. |
| Organization switching | Server-side active-organization selection changes the principal context; intelligence state is refetched and RLS is rebound per transaction. | Multiple browser tabs may display an old response until refreshed, but cannot fetch old-tenant data after the switch. |
| Unbounded analytics / denial of service | Windows are an enum (`7d`, `30d`, `90d`); supplier and inventory pages default to 25 and cap at 100; selected-run source sets bound procurement. SQL grouping avoids ledger materialization. | Large single imports and long-lived ledgers still need deployed query/lock monitoring and resource budgets. |
| SQL or window injection | SQLAlchemy uses bound values. Window values are parsed as an enum; UUIDs and numeric limits are typed. No client-controlled column/order SQL exists. | Application or dependency compromise can bypass this design. |
| Cursor tampering | Opaque URL-safe Base64 JSON cursors are length-, arity-, string-, and UUID-validated; malformed values return `400`. They carry ordering keys, never authorization. | Cursors are not signed; harmless valid alterations can only seek within the already-authorized tenant query. |
| N+1 query amplification | Grouped queries operate on the bounded supplier page. Query-count regression proves the supplier SELECT count is constant for different page sizes; procurement/inventory have explicit ceilings. | Query counts do not replace production latency and cardinality monitoring. |
| Sensitive text leakage | Responses exclude workflow comments, resolution/run notes, emails, invitations, credentials, tokens, source hashes/bytes, and inventory notes/references. Only required supplier/item/location labels are returned. | Legitimate labels may themselves contain commercially sensitive text. |
| Stored XSS | React renders labels as text; the principal real-stack browser flow stores markup-like labels and confirms it is displayed, not executed. No response value is injected as HTML. | Future rich-text or chart libraries require a new sink review. |
| Currency mixing | All money fields are exact maps keyed by currency. There is no combined currency total or conversion. Frontend tables retain currency rows. | Consumers outside this repository could misuse the API; metric names and this contract make the boundary explicit. |
| Decimal-to-float conversion | PostgreSQL `NUMERIC` becomes Python `Decimal` and JSON strings. Runtime validators reject numeric money/quantity payloads; browser formatting avoids `Number` arithmetic. | Locale display remains representational and must not become a calculation input. |
| Duplicate-run double counting | Procurement/supplier routes require one run ID and follow only its `analysis_sources`. Duplicate-run regression proves identical files saved twice produce independent equal views; no all-runs route exists. | A future canonical document model would require explicit migration and revised semantics, not an implicit sum. |
| Snapshot/findings/source semantic drift | Persisted snapshot summary supplies matched/review, issue summary, and disputed totals. Source rows supply only descriptive counts, values, dates, and attribution. Workflow state is not reinterpreted. | Schema/engine version evolution may require version-aware adapters in a future phase. |
| Current inventory inferred from receipts | Inventory queries touch only the inventory ledger. Regression proves procurement receipt evidence leaves inventory empty until an explicit stock operation, after which procurement results remain unchanged. | Users may still assume provenance; the UI and metric contract repeat the separation. |
| Read endpoints mutate state | Only GET routes exist. Count/immutability regression compares source, run, snapshot, finding, master, ledger, and audit rows before/after and prevents engine invocation. | Database access logging outside the application may record reads; it is not business-state mutation. |
| RLS failure or wrong context | All tenant tables retain ENABLE/FORCE RLS and runtime is a non-owner without BYPASSRLS. Missing/wrong context and organization-switch integration tests fail closed. | Runtime SQL injection could set its own context; application authorization remains required. |
| Database privilege widening | Phase 8 adds no table or write grants. `0008` adds only an index. Existing startup/schema tests verify runtime/identity boundaries and ledger immutability. | Privileged operators can alter roles, DDL, policies, or triggers; production drift detection is Phase 9 work. |

## Semantic abuse cases

The API intentionally omits organization-wide procurement spend, cross-run supplier totals,
supplier rankings/scores, on-time delivery, savings, payment state, currency conversion, inventory
valuation, aggregate unlike-item quantities, stockout/reorder claims, forecasting, recommendations,
and AI-generated interpretations. Workflow `RESOLVED` means investigation state only; it does not
erase original exception evidence or prove an invoice or supplier was correct.

Transfer counts describe internal relocation and reversal counts describe correction history.
`net_ledger_quantity_delta` is not demand, sales, usage, or consumption. `occurred_at` is mutable
only at posting time but may be backdated, so a past activity window can change when a new backdated
operation is appended. Current on-hand is current state, not a historical as-of balance.

## Deployment work still required

Phase 9 must address HTTPS/proxy limits, trusted forwarding, query and database monitoring,
timeouts, retention, encrypted backups and recovery, secret rotation, deployment-specific CSP,
incident response, rate/concurrency budgets, and real workload testing. Phase 8's local PostgreSQL
plans and browser acceptance are engineering evidence only.
