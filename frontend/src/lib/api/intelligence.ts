import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import {
  INTELLIGENCE_API_PATH,
  INTELLIGENCE_PAGE_SIZE,
} from "@/constants/intelligence";
import type {
  CountMap,
  IntelligenceWindow,
  InventoryIntelligence,
  MoneyMap,
  ProcurementIntelligence,
  SupplierIntelligencePage,
} from "@/types/intelligence";
import { apiFetch } from "./transport";

export class IntelligenceRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "IntelligenceRequestError";
  }
}

const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string";
const nullableText = (value: unknown) => value === null || text(value);
const integer = (value: unknown) =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const nullableInteger = (value: unknown) => value === null || integer(value);
const timestamp = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const decimal = (value: unknown) =>
  text(value) && /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value);
const status = (value: unknown) => value === "ACTIVE" || value === "ARCHIVED";
const nullableStatus = (value: unknown) => value === null || status(value);

function countMap(value: unknown): value is CountMap {
  return object(value) && Object.values(value).every(integer);
}

function moneyMap(value: unknown): value is MoneyMap {
  return (
    object(value) &&
    Object.entries(value).every(
      ([currency, amount]) => /^[A-Z]{3}$/.test(currency) && decimal(amount),
    )
  );
}

const nullableMoneyMap = (value: unknown) => value === null || moneyMap(value);

function invalid(): never {
  throw new IntelligenceRequestError(
    0,
    "The intelligence response could not be read. Refresh to try again.",
  );
}

async function request(path: string, signal?: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await apiFetch(path, { signal });
  } catch {
    throw new IntelligenceRequestError(
      0,
      "Unable to reach Insights. Check your connection and try again.",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return invalid();
  }
  if (!response.ok) {
    const defaults: Record<number, string> = {
      401: "Your session expired. Sign in again.",
      403: "Insights requires AP manager or organization administrator access.",
      404: "The selected run was not found in this organization.",
      422: "The selected intelligence filters are invalid.",
    };
    throw new IntelligenceRequestError(
      response.status,
      object(payload) && text(payload.message)
        ? payload.message
        : (defaults[response.status] ?? "Insights could not be loaded."),
    );
  }
  return payload;
}

function run(value: unknown) {
  return (
    object(value) &&
    text(value.id) &&
    nullableText(value.title) &&
    text(value.mode) &&
    Object.hasOwn(ANALYSIS_MODES, value.mode) &&
    timestamp(value.completed_at) &&
    typeof value.archived === "boolean"
  );
}

function availability(value: unknown) {
  return (
    object(value) &&
    typeof value.has_purchase_orders === "boolean" &&
    typeof value.has_receipts === "boolean" &&
    typeof value.has_invoices === "boolean"
  );
}

function metricCounts(value: unknown) {
  return (
    object(value) &&
    nullableInteger(value.purchase_orders) &&
    nullableInteger(value.goods_receipts) &&
    nullableInteger(value.invoices)
  );
}

function procurement(value: unknown): value is ProcurementIntelligence {
  return (
    object(value) &&
    value.scope === "selected_run" &&
    run(value.run) &&
    availability(value.availability) &&
    metricCounts(value.documents) &&
    metricCounts(value.lines) &&
    object(value.result_state) &&
    nullableInteger(value.result_state.matched_lines) &&
    nullableInteger(value.result_state.review_required_lines) &&
    object(value.issues) &&
    countMap(value.issues.by_code) &&
    countMap(value.issues.by_category) &&
    (value.fulfillment === null || countMap(value.fulfillment)) &&
    object(value.money) &&
    nullableMoneyMap(value.money.ordered_value_by_currency) &&
    nullableMoneyMap(value.money.invoiced_value_by_currency) &&
    nullableMoneyMap(value.money.authoritative_disputed_amounts_by_currency)
  );
}

function supplier(value: unknown) {
  if (!object(value) || !object(value.identity)) return false;
  const identity = value.identity;
  if (
    !text(identity.supplier_code) ||
    !nullableText(identity.resolved_supplier_id) ||
    !nullableText(identity.supplier_name) ||
    !nullableStatus(identity.supplier_status) ||
    typeof identity.resolved !== "boolean"
  )
    return false;
  if (!object(value.purchase_orders) || !object(value.invoices)) return false;
  if (
    !nullableInteger(value.purchase_orders.document_count) ||
    !nullableInteger(value.purchase_orders.line_count) ||
    !nullableMoneyMap(value.purchase_orders.ordered_value_by_currency) ||
    !nullableInteger(value.invoices.document_count) ||
    !nullableInteger(value.invoices.line_count) ||
    !nullableInteger(value.invoices.review_line_count) ||
    !nullableMoneyMap(value.invoices.invoiced_value_by_currency)
  )
    return false;
  if (
    !object(value.issues) ||
    !countMap(value.issues.by_code) ||
    !countMap(value.issues.by_category) ||
    !(value.receiving === null || countMap(value.receiving))
  )
    return false;
  if (value.receipt_timing === null) return true;
  return (
    object(value.receipt_timing) &&
    (value.receipt_timing.median_observed_days_to_first_receipt === null ||
      decimal(value.receipt_timing.median_observed_days_to_first_receipt)) &&
    integer(value.receipt_timing.first_receipt_eligible_line_count) &&
    (value.receipt_timing.median_observed_days_to_full_receipt === null ||
      decimal(value.receipt_timing.median_observed_days_to_full_receipt)) &&
    integer(value.receipt_timing.full_receipt_eligible_line_count) &&
    value.receipt_timing.basis === "observed_in_selected_run_source_set"
  );
}

function supplierPage(value: unknown): value is SupplierIntelligencePage {
  return (
    object(value) &&
    value.scope === "selected_run" &&
    text(value.run_id) &&
    Array.isArray(value.items) &&
    value.items.length <= INTELLIGENCE_PAGE_SIZE &&
    value.items.every(supplier) &&
    nullableText(value.next_cursor)
  );
}

function inventoryItem(value: unknown) {
  return (
    object(value) &&
    object(value.item) &&
    text(value.item.id) &&
    text(value.item.item_code) &&
    text(value.item.description) &&
    nullableText(value.item.base_uom) &&
    status(value.item.status) &&
    object(value.location) &&
    text(value.location.id) &&
    text(value.location.location_code) &&
    text(value.location.name) &&
    status(value.location.status) &&
    decimal(value.current_on_hand) &&
    integer(value.operation_count) &&
    decimal(value.net_ledger_quantity_delta) &&
    (value.last_movement_at === null || timestamp(value.last_movement_at)) &&
    (value.last_inbound_at === null || timestamp(value.last_inbound_at)) &&
    (value.last_outbound_at === null || timestamp(value.last_outbound_at))
  );
}

function inventory(value: unknown): value is InventoryIntelligence {
  return (
    object(value) &&
    value.scope === "current_organization_inventory_ledger" &&
    timestamp(value.server_now) &&
    object(value.period) &&
    ["7d", "30d", "90d"].includes(String(value.period.window)) &&
    timestamp(value.period.start) &&
    timestamp(value.period.end) &&
    value.period.time_field === "occurred_at" &&
    object(value.summary) &&
    integer(value.summary.active_inventory_item_count) &&
    integer(value.summary.active_inventory_location_count) &&
    integer(value.summary.positive_item_location_position_count) &&
    countMap(value.summary.operation_counts_by_type) &&
    integer(value.summary.reversal_operation_count) &&
    Array.isArray(value.items) &&
    value.items.length <= INTELLIGENCE_PAGE_SIZE &&
    value.items.every(inventoryItem) &&
    nullableText(value.next_cursor)
  );
}

export async function getProcurementIntelligence(
  runId: string,
  signal?: AbortSignal,
): Promise<ProcurementIntelligence> {
  const value = await request(
    `${INTELLIGENCE_API_PATH}/runs/${encodeURIComponent(runId)}/procurement`,
    signal,
  );
  return procurement(value) ? value : invalid();
}

export async function getSupplierIntelligence(
  runId: string,
  signal?: AbortSignal,
): Promise<SupplierIntelligencePage> {
  const value = await request(
    `${INTELLIGENCE_API_PATH}/runs/${encodeURIComponent(runId)}/suppliers?limit=${INTELLIGENCE_PAGE_SIZE}`,
    signal,
  );
  return supplierPage(value) ? value : invalid();
}

export async function getInventoryIntelligence(
  window: IntelligenceWindow,
  signal?: AbortSignal,
): Promise<InventoryIntelligence> {
  const value = await request(
    `${INTELLIGENCE_API_PATH}/inventory?window=${encodeURIComponent(window)}&limit=${INTELLIGENCE_PAGE_SIZE}`,
    signal,
  );
  return inventory(value) ? value : invalid();
}
