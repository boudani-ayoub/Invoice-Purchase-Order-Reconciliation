import type { AnalysisMode } from "./analysis";

export type IntelligenceWindow = "7d" | "30d" | "90d";
export type CountMap = Record<string, number>;
export type MoneyMap = Record<string, string>;

export interface ProcurementIntelligence {
  scope: "selected_run";
  run: {
    id: string;
    title: string | null;
    mode: AnalysisMode;
    completed_at: string;
    archived: boolean;
  };
  availability: {
    has_purchase_orders: boolean;
    has_receipts: boolean;
    has_invoices: boolean;
  };
  documents: Record<"purchase_orders" | "goods_receipts" | "invoices", number | null>;
  lines: Record<"purchase_orders" | "goods_receipts" | "invoices", number | null>;
  result_state: {
    matched_lines: number | null;
    review_required_lines: number | null;
  };
  issues: { by_code: CountMap; by_category: CountMap };
  fulfillment: CountMap | null;
  money: {
    ordered_value_by_currency: MoneyMap | null;
    invoiced_value_by_currency: MoneyMap | null;
    authoritative_disputed_amounts_by_currency: MoneyMap | null;
  };
}

export interface SupplierIntelligence {
  identity: {
    supplier_code: string;
    resolved_supplier_id: string | null;
    supplier_name: string | null;
    supplier_status: "ACTIVE" | "ARCHIVED" | null;
    resolved: boolean;
  };
  purchase_orders: {
    document_count: number | null;
    line_count: number | null;
    ordered_value_by_currency: MoneyMap | null;
  };
  invoices: {
    document_count: number | null;
    line_count: number | null;
    invoiced_value_by_currency: MoneyMap | null;
    review_line_count: number | null;
  };
  issues: { by_code: CountMap; by_category: CountMap };
  receiving: CountMap | null;
  receipt_timing: {
    median_observed_days_to_first_receipt: string | null;
    first_receipt_eligible_line_count: number;
    median_observed_days_to_full_receipt: string | null;
    full_receipt_eligible_line_count: number;
    basis: "observed_in_selected_run_source_set";
  } | null;
}

export interface SupplierIntelligencePage {
  scope: "selected_run";
  run_id: string;
  items: SupplierIntelligence[];
  next_cursor: string | null;
}

export interface InventoryIntelligenceItem {
  item: {
    id: string;
    item_code: string;
    description: string;
    base_uom: string | null;
    status: "ACTIVE" | "ARCHIVED";
  };
  location: {
    id: string;
    location_code: string;
    name: string;
    status: "ACTIVE" | "ARCHIVED";
  };
  current_on_hand: string;
  operation_count: number;
  net_ledger_quantity_delta: string;
  last_movement_at: string | null;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
}

export interface InventoryIntelligence {
  scope: "current_organization_inventory_ledger";
  server_now: string;
  period: {
    window: IntelligenceWindow;
    start: string;
    end: string;
    time_field: "occurred_at";
  };
  summary: {
    active_inventory_item_count: number;
    active_inventory_location_count: number;
    positive_item_location_position_count: number;
    operation_counts_by_type: CountMap;
    reversal_operation_count: number;
  };
  items: InventoryIntelligenceItem[];
  next_cursor: string | null;
}
