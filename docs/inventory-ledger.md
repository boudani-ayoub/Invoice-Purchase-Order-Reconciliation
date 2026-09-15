# Inventory ledger

## What counts as stock

An item is master data, not an inventory balance. A goods-receipt row is procurement evidence,
not proof that the goods remain on hand. Imports and saved reconciliation runs can overlap or be
repeated, so they never create stock movements.

On-hand changes only through an explicit inventory operation. Phase 7 does not automatically link
an operation to a purchase order, invoice, or imported goods receipt. `external_reference` is
optional plain text entered by an operator; it is not resolved as provenance.

The authoritative balance is:

```text
SUM(stock_movements.quantity_delta)
GROUP BY organization_id, item_id, location_id
```

There is no editable quantity on `items` and no inventory-position cache. API quantities are exact
decimal strings, Python uses `Decimal`, and PostgreSQL uses unconstrained `NUMERIC`. JavaScript
floating-point arithmetic is not used for stock.

## Master data

The existing organization-owned `items` table remains the only item master. Inventory adds a
positive optimistic `version` and nullable `base_uom`. Existing items migrate with version 1 and no
invented unit. An active item needs a configured base unit before its first movement. The unit is a
normalized token such as `EA`, `KG`, or `BOX`; Phase 7 performs no conversion. It can be corrected
until the first movement and is immutable afterward.

Locations are a flat organization-owned list with an immutable code, mutable name, ACTIVE or
ARCHIVED status, and positive optimistic version. There are no warehouse, zone, or bin hierarchies.

Item and location archive operations use `expected_version` and row locks. Archive is reversible,
but is rejected while the current derived balance is nonzero. Archived records remain in history
and reject new movements. Neither master is hard-deleted.

## Operations and signs

`inventory_operations` records the business action and authenticated actor. `stock_movements`
records its item/location deltas. Both tables are append-only.

| Operation | Movement rule |
| --- | --- |
| `OPENING_BALANCE` | one positive movement; allowed only before any movement for that item/location |
| `STOCK_RECEIPT` | one positive movement |
| `STOCK_ISSUE` | one negative movement derived from a positive request quantity |
| `ADJUSTMENT_IN` | one positive movement |
| `ADJUSTMENT_OUT` | one negative movement derived from a positive request quantity |
| `TRANSFER` | one negative source and one equal positive destination movement in one transaction |
| `REVERSAL` | exact opposite of every movement on one original operation |

Clients send a positive plain decimal string. They cannot submit a signed delta. The service owns
the sign, and database triggers enforce sign, line-count, transfer-pair, and reversal rules if a
future code path bypasses the service.

A transfer is one operation, never a separate issue and receipt. The item and both active locations
must belong to the active organization, and source and destination must differ. The operation and
both movement lines commit or roll back together.

History is corrected by a new reversal, not UPDATE or DELETE. One original operation permits at
most one direct reversal. A reversal can fail when its outbound inverse would make stock negative;
the original remains unchanged.

## Time and current balance

`created_at` is the server recording time. `occurred_at` is the business event time, defaults to
server now, accepts legitimate backdating, and rejects future values. Every posted movement is
included in current on-hand regardless of `occurred_at`. Phase 7 does not claim complete historical
or as-of reconstruction semantics.

The UI and API call the result **on-hand**, not available stock. There are no reservations,
allocations, available-to-promise calculations, safety stock, or projected balances.

## Negative-stock and concurrency policy

An outbound movement must not make on-hand negative. Every writer follows one locking protocol:

```text
authenticate and authorize
→ acquire organization/idempotency advisory lock
→ lock the item
→ lock all affected locations in sorted UUID order
→ calculate current item/location balance from movements
→ validate the operation
→ insert operation and movement lines
→ commit
```

The item lock also prevents a base-unit change racing the first movement. Deterministic location
ordering makes opposing transfers deadlock-safe. Location-level locking intentionally serializes
otherwise unrelated item writes at a busy location. This conservative tradeoff is suitable for the
current scale; measure real contention and query cost before considering a balance cache or finer
locking scheme.

## Idempotency

Every movement, transfer, and reversal requires a client-generated UUID. The database uniquely
indexes `(organization_id, idempotency_key)`. The service takes a transaction-scoped PostgreSQL
advisory lock derived from that pair before checking or inserting the operation.

- The first accepted request returns `201 Created`.
- The same key, actor, and canonical intent returns the existing operation with `200 OK` and no new
  movement.
- The same key with another actor or intent returns `409 Conflict`.
- Concurrent requests with one key create exactly one operation.

The browser keeps the UUID after an ambiguous network failure and offers an explicit retry with the
same key. It does not silently retry inventory writes. Server request IDs remain separate,
server-owned correlation identifiers.

## Security and storage boundary

Every inventory table carries `organization_id`, tenant-leading constraints/indexes, same-tenant
foreign keys, and forced row-level security. Missing or invalid organization context fails closed.
The runtime role has SELECT/INSERT on the ledger but no UPDATE/DELETE; triggers reject ledger
mutation even if privileges are widened accidentally. Master updates are column-scoped. The
identity role receives no inventory access.

List endpoints use bounded keyset pagination with a default of 25 and maximum of 100. Current
balances are calculated from the ledger at read time. Expected growth, lock contention, index use,
and retention must be monitored in a deployment; Phase 7 does not claim production capacity.

## Explicit exclusions

Phase 7 has quantity only. It adds no inventory valuation, FIFO/LIFO, average cost, COGS, landed
cost, currency conversion, multiple-unit conversion, lots, serials, expiry, barcodes, hierarchy,
reservations, allocations, reorder logic, forecasts, or procurement intelligence. Purchase-order
and invoice prices are not treated as inventory cost. Phase 8 is separate work.
