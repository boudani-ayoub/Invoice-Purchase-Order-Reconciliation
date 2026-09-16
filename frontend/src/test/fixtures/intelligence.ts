import type {
  InventoryIntelligence,
  ProcurementIntelligence,
  SupplierIntelligencePage,
} from "@/types/intelligence";

export const procurement: ProcurementIntelligence = {
  scope: "selected_run",
  run: {
    id: "run-a",
    title: "Quarter review",
    mode: "three-way",
    completed_at: "2026-09-15T00:00:00Z",
    archived: false,
  },
  availability: {
    has_purchase_orders: true,
    has_receipts: true,
    has_invoices: true,
  },
  documents: { purchase_orders: 2, goods_receipts: 2, invoices: 2 },
  lines: { purchase_orders: 3, goods_receipts: 3, invoices: 3 },
  result_state: { matched_lines: 2, review_required_lines: 1 },
  issues: { by_code: { PRICE_MISMATCH: 1 }, by_category: { COMMERCIAL: 1 } },
  fulfillment: {
    FULLY_RECEIVED: 1,
    PARTIALLY_RECEIVED: 1,
    NOT_RECEIVED: 0,
    OVER_RECEIVED: 1,
  },
  money: {
    ordered_value_by_currency: { MAD: "1250.00", USD: "40.00" },
    invoiced_value_by_currency: { MAD: "1300.00", USD: "40.00" },
    authoritative_disputed_amounts_by_currency: { MAD: "50.00" },
  },
};

export const suppliers: SupplierIntelligencePage = {
  scope: "selected_run",
  run_id: "run-a",
  next_cursor: null,
  items: [
    {
      identity: {
        supplier_code: '<script>alert("x")</script>',
        resolved_supplier_id: null,
        supplier_name: null,
        supplier_status: null,
        resolved: false,
      },
      purchase_orders: {
        document_count: 1,
        line_count: 2,
        ordered_value_by_currency: { MAD: "1250.00" },
      },
      invoices: {
        document_count: 1,
        line_count: 2,
        invoiced_value_by_currency: { MAD: "1300.00" },
        review_line_count: 1,
      },
      issues: {
        by_code: { PRICE_MISMATCH: 1 },
        by_category: { COMMERCIAL: 1 },
      },
      receiving: {
        FULLY_RECEIVED: 1,
        PARTIALLY_RECEIVED: 1,
        NOT_RECEIVED: 0,
        OVER_RECEIVED: 0,
      },
      receipt_timing: {
        median_observed_days_to_first_receipt: "3.5",
        first_receipt_eligible_line_count: 2,
        median_observed_days_to_full_receipt: "5",
        full_receipt_eligible_line_count: 1,
        basis: "observed_in_selected_run_source_set",
      },
    },
  ],
};

export const inventory: InventoryIntelligence = {
  scope: "current_organization_inventory_ledger",
  server_now: "2026-09-16T00:00:00Z",
  period: {
    window: "30d",
    start: "2026-08-17T00:00:00Z",
    end: "2026-09-16T00:00:00Z",
    time_field: "occurred_at",
  },
  summary: {
    active_inventory_item_count: 1,
    active_inventory_location_count: 1,
    positive_item_location_position_count: 1,
    operation_counts_by_type: { STOCK_RECEIPT: 1, REVERSAL: 0 },
    reversal_operation_count: 0,
  },
  items: [
    {
      item: {
        id: "item-a",
        item_code: "SKU-1",
        description: "Exact part",
        base_uom: "EA",
        status: "ACTIVE",
      },
      location: {
        id: "location-a",
        location_code: "MAIN",
        name: "Main store",
        status: "ACTIVE",
      },
      current_on_hand: "12.500",
      operation_count: 1,
      net_ledger_quantity_delta: "2.500",
      last_movement_at: "2026-09-15T00:00:00Z",
      last_inbound_at: "2026-09-15T00:00:00Z",
      last_outbound_at: null,
    },
  ],
  next_cursor: null,
};
