# Intelligence metric contract

Product Phase 8 is a read model over two deliberately separate evidence domains. Procurement and
supplier metrics describe exactly one completed saved analysis. Inventory metrics describe the
active organization's explicit stock ledger. Neither domain is a substitute for the other.

## Scope and identity rules

Every procurement import creates source rows belonging to that import. Saving the same files twice
creates two legitimate, independent historical runs and two source sets; the schema has no
canonical business-document identity across imports. Summing runs would therefore double count
re-imported or overlapping documents. There is no all-runs endpoint, implicit latest-run rollup, or
organization-wide procurement total. The client supplies one run ID, and the service uses only that
completed run's `analysis_sources`, source rows, immutable `result_snapshots`, and findings.

Archived completed runs remain readable because archive is a history visibility state, not
deletion. The active organization and live `VIEW_INTELLIGENCE` permission are checked on every
request. A foreign or non-completed run is indistinguishable from a missing run.

Inventory has a different identity: an idempotent, append-only `inventory_operations` /
`stock_movements` ledger. Current on-hand may therefore be calculated across that organization's
ledger. Imported `goods_receipt_lines` never enter this calculation. A selected run's receiving
evidence and current inventory may coexist, but no provenance relationship is inferred.

In the tables below, “selected run” always means the one completed run named in the request;
“current organization” means the organization selected by the authenticated session. Count metrics
have no currency. `—` under numerator or denominator means the metric is a count, sum, timestamp, or
label rather than a ratio; Phase 8 exposes no percentages.

## Shared representation rules

- Money and quantity originate as PostgreSQL `NUMERIC`, remain Python `Decimal`, and are JSON
  strings. The browser formats strings and performs no floating-point business arithmetic.
- Money maps are keyed by source ISO-style currency code. Amounts in different currencies are never
  added or converted.
- A missing source dimension is `null`, not zero. An available source containing no matching rows is
  an empty map or zero count. An issue map may be empty when the selected snapshot has no issues.
- Source dates are descriptive business dates. Inventory periods use UTC `occurred_at` and the
  half-open interval `[period.start, period.end)`. Backdated postings can therefore change a prior
  period's activity after it was first viewed.
- Historical selected-run rows keep archived supplier labels/status. Current inventory includes
  positions involving archived items or locations because archive does not erase ledger history.
- Supplier and inventory lists use opaque keyset cursors, default page size 25, maximum 100. Cursors
  do not expose totals and are valid only within the authorized tenant query.

## Procurement overview metrics

All fields below have scope `selected_run`. Source rows must belong to the source files joined to
that run through `analysis_sources`; rows from every other run/import are excluded. Current master
status does not remove historical evidence.

| Exact response name | Source | Numerator / calculation | Denominator | Inclusion and exclusion | Currency | Time field | Archive handling | Zero / null |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `documents.purchase_orders` | `purchase_orders` | Distinct PO headers in the selected PO source | — | Includes every persisted header in that source; excludes all other sources | None | Source set, not a time window | Run may be archived | `null` without a PO source; otherwise integer, including 0 |
| `documents.goods_receipts` | `goods_receipts` | Distinct receipt headers in the selected receipt source | — | Includes every persisted header in that source | None | Source set | Run may be archived | `null` without a receipt source; otherwise integer |
| `documents.invoices` | `invoices` | Distinct invoice headers in the selected invoice source | — | Includes every persisted header in that source | None | Source set | Run may be archived | `null` without an invoice source; otherwise integer |
| `lines.purchase_orders` | `purchase_order_lines` joined to selected PO headers | Count of persisted PO lines | — | Includes resolved and unresolved source evidence | None | Source set | Run may be archived | `null` without PO source; otherwise integer |
| `lines.goods_receipts` | `goods_receipt_lines` joined to selected receipt headers | Count of persisted receipt lines | — | Includes resolved and unresolved source evidence | None | Source set | Run may be archived | `null` without receipt source; otherwise integer |
| `lines.invoices` | `invoice_lines` joined to selected invoice headers | Count of preserved invoice occurrences | — | Duplicate source occurrences remain separate by design | None | Source set | Run may be archived | `null` without invoice source; otherwise integer |
| `result_state.matched_lines` | selected immutable `result_snapshots.report.summary` | Persisted engine `matched_lines` value | Snapshot result population | No recomputation from findings or source rows | None | Run completion | Run may be archived | Snapshot value; `null` when the mode does not publish it |
| `result_state.review_required_lines` | selected immutable snapshot summary | Persisted engine `review_required_lines` value | Snapshot result population | Workflow resolution does not alter this original result | None | Run completion | Run may be archived | Snapshot value; `null` when unavailable |
| `issues.by_code[IssueCode]` | selected immutable snapshot summary | Persisted count for the exact issue code | Snapshot result population | Original exception evidence only; excludes workflow state interpretation | None | Run completion | Run may be archived | Missing codes are omitted; empty object means no recorded issues |
| `issues.by_category[category]` | immutable `findings.code/category` for selected run | Count of findings grouped by immutable category | — | Includes all finding workflow states; excludes comment/resolution text | None | Run completion | Run may be archived | Missing categories omitted; empty object means no findings |
| `fulfillment[state]` | PO-receipt snapshot status; for three-way, selected PO and receipt source links | Count of PO lines in `FULLY_RECEIVED`, `PARTIALLY_RECEIVED`, `NOT_RECEIVED`, or `OVER_RECEIVED` | PO lines eligible in selected PO/receipt source set | PO-receipt uses persisted result status. Three-way groups persisted resolved receipt links by PO line to avoid multiplying PO fulfillment by invoice occurrences; no matching rules are rerun. Invoice-only modes excluded | None | Source set, using persisted quantities | Run may be archived | Whole object is `null` without both PO and receipt sources; supported states are present with 0 when absent |
| `money.ordered_value_by_currency[currency]` | selected `purchase_orders` / `purchase_order_lines` | Sum of `ordered_quantity × unit_price` per PO header currency | — | Includes every selected-source PO line; does not mean spend, payment, cost, or cash flow | Separate map entry per currency | Source set | Run may be archived | `null` without PO source; empty map if available and empty; exact decimal strings |
| `money.invoiced_value_by_currency[currency]` | selected `invoices` / `invoice_lines` | Sum of `invoiced_quantity × unit_price` per invoice header currency | — | Includes preserved duplicate occurrences; does not mean paid amount | Separate map entry per currency | Source set | Run may be archived | `null` without invoice source; empty map if available and empty; strings |
| `money.authoritative_disputed_amounts_by_currency[currency]` | selected immutable snapshot summary `disputed_amounts` | Exact persisted engine total per currency | Snapshot's engine-defined result population | Never reconstructed or summed from finding rows; no cross-run or cross-currency sum | Separate map entry per currency | Run completion | Run may be archived | `null` when the mode has no disputed-total concept; otherwise strings, with absent currencies omitted |

`availability.has_purchase_orders`, `has_receipts`, and `has_invoices` are source-presence flags,
not metrics. The run metadata reports ID, title, mode, completion time, and archive state so consumers
can display the evidence boundary explicitly.

## Supplier metrics

Every row is grouped by the exact persisted `source_supplier_code` found in the selected run's PO
or invoice sources. A nullable resolved supplier ID is only a label link. Unresolved codes remain
separate rows and never cause a supplier master to be created or heuristically merged. All fields
have scope `selected_run`; current supplier archive status changes the label metadata only.

| Exact response name | Source | Numerator / calculation | Denominator | Inclusion and exclusion | Currency | Time field | Archive handling | Zero / null |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `purchase_orders.document_count` | selected PO headers | Distinct headers with this source supplier code | — | Only the selected PO source | None | Source set | Archived master remains labelled | `null` without PO source; otherwise integer |
| `purchase_orders.line_count` | selected PO headers/lines | Lines on those headers | — | Includes all selected-source lines | None | Source set | Same | `null` without PO source; otherwise integer |
| `purchase_orders.ordered_value_by_currency` | selected PO headers/lines | `Σ ordered_quantity × unit_price`, grouped by header currency and source supplier code | — | No organization history, payment, or cross-currency sum | Per-currency strings | Source set | Same | `null` without PO source; otherwise map, possibly empty |
| `invoices.document_count` | selected invoice headers | Distinct headers with this source supplier code | — | Only selected invoice source | None | Source set | Same | `null` without invoice source; otherwise integer |
| `invoices.line_count` | selected invoice headers/lines | Preserved invoice occurrences on those headers | — | Duplicate occurrences count separately | None | Source set | Same | `null` without invoice source; otherwise integer |
| `invoices.invoiced_value_by_currency` | selected invoice headers/lines | `Σ invoiced_quantity × unit_price`, grouped by currency and source supplier code | — | No payment/spend claim and no currency mixing | Per-currency strings | Source set | Same | `null` without invoice source; otherwise map |
| `invoices.review_line_count` | selected immutable snapshot result rows | Result rows for this supplier whose original status is `REVIEW_REQUIRED` | Invoice result rows for this supplier | Does not use mutable workflow status and is not a failure/quality rate | None | Run completion | Same | `null` without invoice source; otherwise integer, including 0 |
| `issues.by_code[IssueCode]` | selected immutable snapshot result rows | Occurrences of each original row issue; PO-receipt `OVER_RECEIVED` status is represented as that issue code | — | Exact source supplier code attribution; workflow resolution excluded | None | Run completion | Same | Empty map means no issues attributed |
| `issues.by_category[category]` | issue-code-to-category contract | Sum of attributed issue occurrences mapped to immutable category | — | Same original evidence; no mutable workflow meaning | None | Run completion | Same | Empty map means none |
| `receiving[state]` | same selected-run fulfillment basis as procurement overview | PO-line count per fulfillment state for this supplier code | Eligible selected-source PO lines for that code | Requires both PO and receipt sources; no OTD or SLA interpretation | None | Source set | Same | Whole object `null` when unavailable; supported states contain integer 0 when absent |
| `receipt_timing.median_observed_days_to_first_receipt` | selected PO `order_date`; linked selected receipt-line `receipt_date` | Deterministic median of `(earliest observed receipt_date − order_date)` in whole days across eligible PO lines | `first_receipt_eligible_line_count` | A PO line is eligible when at least one selected-source receipt line resolves to it. This is observed lead time, not lateness or OTD | None | Source dates | Same | `null` when denominator is 0; even samples average the two middle integers and serialize Decimal string |
| `receipt_timing.first_receipt_eligible_line_count` | same linked PO/receipt lines | PO lines with at least one observed receipt date | — | Lines without a linked selected-source receipt excluded | None | Source dates | Same | Integer 0 when none |
| `receipt_timing.median_observed_days_to_full_receipt` | selected PO order/quantity and chronological linked receipt dates/quantities | Median days from order date to first date cumulative received quantity reaches or exceeds ordered quantity | `full_receipt_eligible_line_count` | Incomplete lines excluded; cumulative quantities are grouped by date; no promised date exists | None | Source dates | Same | `null` when denominator is 0; Decimal string otherwise |
| `receipt_timing.full_receipt_eligible_line_count` | same | PO lines that reach ordered quantity within this selected source set | — | Incomplete lines excluded | None | Source dates | Same | Integer 0 when none |

The timing `basis` is always `observed_in_selected_run_source_set`. Phase 8 deliberately exposes no
supplier score, rating, tier, risk label, concentration across currencies, or on-time-delivery KPI.

## Inventory metrics

Inventory fields have scope `current_organization_inventory_ledger`. Summary counts and position
rows never use procurement sources. The selected 7, 30, or 90 day window affects activity fields,
not current on-hand or last-ever movement timestamps.

| Exact response name | Source | Numerator / calculation | Denominator | Inclusion and exclusion | Currency / unit | Time field | Archive handling | Zero / null |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `summary.active_inventory_item_count` | `items` | Count where status is `ACTIVE` | — | Current organization only; no requirement for movement history | None | Current state | Archived items excluded | Integer 0 when none |
| `summary.active_inventory_location_count` | `inventory_locations` | Count where status is `ACTIVE` | — | Current organization only | None | Current state | Archived locations excluded | Integer 0 when none |
| `summary.positive_item_location_position_count` | all `stock_movements` | Count of item/location groups whose all-time `SUM(quantity_delta) > 0` | — | Includes every committed movement; does not add quantities across groups | None | Current derived state | Archived items/locations remain in ledger groups | Integer 0 when none |
| `summary.operation_counts_by_type[type]` | `inventory_operations` | Count of operations of each explicit type in `[start,end)` | — | Includes transfer and reversal as their own operation types; does not infer demand/usage | None | UTC `occurred_at` | Operations remain regardless of master archive | Every known type is present with integer 0 when absent |
| `summary.reversal_operation_count` | `inventory_operations` | Count where type is `REVERSAL` in `[start,end)` | — | Exact alias of the reversal entry in operation counts | None | UTC `occurred_at` | Same | Integer 0 when none |
| `items[].current_on_hand` | all `stock_movements` for exact item/location | `SUM(quantity_delta)` across all committed history | — | Opening, receipt, issue, adjustment, transfer, and reversal deltas included; procurement receipts excluded | Exact Decimal string in that item's base UOM; never summed across items | All history; not an as-of reconstruction | Archived item/location positions retained | Exact string, including `"0"`; absent never fabricated for combinations with no movement history |
| `items[].operation_count` | joined operations/movements for exact item/location | Count of distinct operations touching the position in `[start,end)` | — | A multi-line operation counts once for that position | None | UTC `occurred_at` | Archived positions retained | Integer 0 when no period activity |
| `items[].net_ledger_quantity_delta` | joined movements for exact item/location | `SUM(quantity_delta)` for movements whose operation is in `[start,end)` | — | All committed operation types included; this is ledger net delta, not sales, demand, usage, or consumption | Exact Decimal string in item base UOM | UTC `occurred_at` | Archived positions retained | Exact `"0"` when no period movement |
| `items[].last_movement_at` | joined operations/movements | Maximum `occurred_at` for the position | — | All operation types included, all history | None | UTC `occurred_at` | Archived positions retained | `null` only if no movement; returned rows normally have one |
| `items[].last_inbound_at` | joined movements with positive delta | Maximum operation `occurred_at` | — | Positive movement legs only; a transfer destination is inbound | None | UTC `occurred_at` | Archived positions retained | `null` if never positive |
| `items[].last_outbound_at` | joined movements with negative delta | Maximum operation `occurred_at` | — | Negative movement legs only; a transfer source is outbound | None | UTC `occurred_at` | Archived positions retained | `null` if never negative |

`server_now` is the UTC clock captured for the request. `period.start` is exactly `server_now` minus
the selected number of days, `period.end` equals `server_now`, and `period.time_field` is
`occurred_at`. No inventory value, universal quantity total, stockout, reorder, reservation,
forecast, or available-to-promise metric exists.

## Query design and cost

The supplier page first obtains one bounded set of source supplier codes, then uses grouped queries
and one bounded master-label lookup. Its SELECT count is constant as page size changes (measured at
the same count for limits 1 and 10, with a ceiling of 12). Procurement uses at most 12 SELECTs and
inventory at most 10. Inventory returns only a keyset page and aggregates in PostgreSQL; it never
loads the ledger into Python.

Migration `0008` adds
`ix_inventory_operations_intelligence_window (organization_id, occurred_at, operation_type)` for
the bounded operation-count path. An `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` comparison using
20,000 operations under the restricted runtime role and forced RLS measured 2.624 ms without the
index and 0.657 ms with it; the indexed plan named the new index and returned the same rows. These
local measurements justify this query shape but are not a production capacity guarantee.
