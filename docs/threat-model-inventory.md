# Inventory threat model

## Scope and trust boundaries

Phase 7 covers item inventory metadata, flat locations, explicit stock operations, derived on-hand
balances, and immutable operation history. It does not cover valuation, reservations, warehouse
hierarchy, automatic procurement posting, or supplier/procurement intelligence.

The browser is untrusted. Navigation and disabled controls are convenience only. FastAPI derives
the actor and organization from the authenticated session, rechecks the live membership and exact
permission, and ignores no client-supplied tenant or actor because those fields are forbidden.
PostgreSQL forced RLS and same-organization foreign keys form the second tenant boundary. The
schema owner and database administrator remain stronger trust boundaries.

## Permission boundary

| Capability | MEMBER | AP_MANAGER | ORG_ADMIN |
| --- | :---: | :---: | :---: |
| View items, locations, on-hand, and operations | No | Yes | Yes |
| Create or change item/location master data | No | No | Yes |
| Post movement, transfer, or reversal | No | No | Yes |

Permissions are explicit; there is no wildcard grant and no inventory-manager role. A role change
or membership archive affects the next request. Cross-organization UUIDs return `404` only after
the caller has the relevant permission, while an insufficient role returns `403`.

## Abuse cases and controls

| Threat | Control and residual boundary |
| --- | --- |
| Inventory IDOR or aggregate tenant leakage | Active-organization authorization, forced RLS on locations/operations/movements, tenant-owned item RLS, same-tenant composite foreign keys, and organization-scoped aggregate tests. A database owner can still bypass application controls. |
| Cross-tenant item/location substitution | Service lookups include organization and lock the selected rows; composite foreign keys reject mismatched movement lines; foreign identifiers are reported as not found. |
| Actor or request-ID spoofing | Neither value exists in write bodies. Actor comes from the live session and request ID from middleware. |
| Mass assignment | Pydantic inputs use `extra="forbid"`; master APIs expose only documented fields and optimistic versions. |
| Arbitrary signed delta or floating-point coercion | API quantity must be a positive, finite, plain decimal JSON string. The server derives signs; database checks and triggers reject invalid movement shapes. |
| Negative-stock race | Every writer locks the item, then affected locations in deterministic UUID order, recalculates from `NUMERIC` movements, and rejects a negative result. The database insert trigger repeats the negative check. |
| Transfer split or partial commit | Transfer creates one parent and two exact opposite lines in one transaction; a deferred database constraint verifies the pair. |
| Transfer deadlock | All writers acquire item and location locks in the same deterministic order. Real concurrent opposing-transfer tests verify completion. Lock waits remain a capacity and denial-of-service concern. |
| Duplicate posting or lost response | Organization/key advisory lock, unique idempotency constraint, actor-bound canonical fingerprint, and explicit same-key browser retry. Keys are not request IDs. |
| Idempotency key collision/reuse | Same actor and intent replays; a different actor or intent conflicts. UUID entropy remains dependent on the client platform's cryptographic generator. |
| Opening-balance abuse | Only one opening balance is allowed before any history for the item/location; later corrections require adjustment or reversal. |
| Reversal erases or oversells history | Reversal appends exact inverse lines, permits one direct reversal, and applies the same negative-stock policy. Original rows remain immutable. |
| Archived or unit-redefined master data | Active item/location and configured UOM are required. Nonzero masters cannot be archived, and base UOM cannot change after the first movement. Service checks have trigger defense-in-depth. |
| Ledger tampering | Runtime has no UPDATE/DELETE grants on operations or movements, and immutable triggers reject both. Database owners remain capable of changing schema or disabling controls. |
| Goods receipt counted twice | Procurement evidence and reconciliation saves have no inventory write path. Regression tests import the same receipt inputs twice and observe no movement. Explicit `STOCK_RECEIPT` is the only receipt-like inventory action. |
| CSRF | Inventory writes use the existing trusted-Origin and session/context-bound CSRF proof. Same-origin XSS remains able to act as the user. |
| Stored XSS | Names, descriptions, references, and notes are bounded plain text; React renders them as text and no inventory view uses `dangerouslySetInnerHTML`. CSP is defense-in-depth. |
| Unbounded ledger reads or response amplification | Read limits default to 25 and cap at 100, cursors are bounded/validated, and no arbitrary analytics endpoint is exposed. Aggregate cost still grows with tenant history and needs operational monitoring. |
| RLS context omission or corruption | FORCE RLS policies compare every tenant row with a transaction-local UUID setting. Missing or invalid context exposes no inventory rows. |
| Database-role widening | Runtime receives narrow ledger and master privileges; identity receives none. Startup verifies expected grants. Triggers reduce, but do not eliminate, damage from accidental privilege widening. |
| Generic audit leakage | Inventory history is authoritative in the inventory domain. Phase 7 does not add notes, references, or movement detail to the identity-domain general audit, avoiding a new cross-role read path. |

## Availability and scale risks

Location locks serialize all inventory writes touching the same location, even when items differ.
Balance reads calculate sums over the append-only ledger. The current indexes match item/location,
location/item, operation, chronology, and type filters, but no load claim is made. Deployments need
request/concurrency limits, query and lock-wait monitoring, storage planning, tested backups, and a
reviewed retention policy. Do not add a mutable balance cache until measurements justify its
consistency and recovery complexity.

## Review boundary

The review includes authorization, IDOR, tenant aggregates, decimal parsing, negative-stock races,
deadlock ordering, idempotency, archive and UOM races, CSRF, stored XSS, RLS, grants, ledger
immutability, and procurement separation. It does not establish production readiness, penetration
test coverage, compliance certification, non-repudiation, or resilience against a compromised
database owner, authenticated administrator, same-origin script, host, backup system, or client
device.
