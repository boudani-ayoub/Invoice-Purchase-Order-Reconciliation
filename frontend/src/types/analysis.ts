import type {
  ReconciliationReport,
  ReconciliationResult,
  ReconciliationSummary,
} from "./reconciliation";

export type AnalysisMode =
  | "invoice-po"
  | "invoice-receipt"
  | "po-receipt"
  | "three-way";
export type InvoicePoResult = Omit<ReconciliationResult, "received_quantity">;
export type InvoiceReceiptResult = Omit<
  ReconciliationResult,
  "ordered_quantity" | "po_unit_price" | "potential_disputed_amount"
> & { received_quantity: string; potential_unsupported_amount: string };
export type InvoiceReceiptSummary = Omit<
  ReconciliationSummary,
  "disputed_amounts"
> & {
  unsupported_amounts: Record<string, string>;
};

export type FulfillmentStatus =
  | "FULLY_RECEIVED"
  | "PARTIALLY_RECEIVED"
  | "NOT_RECEIVED"
  | "OVER_RECEIVED";
export interface PoReceiptResult {
  po_number: string;
  po_line_number: number;
  item_code: string;
  supplier_id: string;
  status: FulfillmentStatus;
  ordered_quantity: string;
  received_quantity: string;
  outstanding_quantity: string;
  over_received_quantity: string;
  po_unit_price: string;
  currency: string;
  outstanding_ordered_value: string;
  over_received_reference_value: string;
}
export interface OrphanReceipt {
  receipt_id: string;
  receipt_line_number: number;
  receipt_date: string;
  po_number: string;
  po_line_number: number;
  item_code: string;
  received_quantity: string;
  issue: string;
}
export interface PoReceiptSummary {
  purchase_orders_processed: number;
  po_lines_processed: number;
  receipt_lines_processed: number;
  status_counts: Record<FulfillmentStatus, number>;
  orphan_receipt_lines: number;
  outstanding_values: Record<string, string>;
  over_received_values: Record<string, string>;
}
export interface InvoicePoReport {
  mode: "invoice-po";
  results: InvoicePoResult[];
  summary: ReconciliationSummary;
}
export interface InvoiceReceiptReport {
  mode: "invoice-receipt";
  results: InvoiceReceiptResult[];
  summary: InvoiceReceiptSummary;
}
export interface PoReceiptReport {
  mode: "po-receipt";
  results: PoReceiptResult[];
  orphan_receipts: OrphanReceipt[];
  summary: PoReceiptSummary;
}
export type ThreeWayReport = ReconciliationReport & { mode: "three-way" };
export type AnalysisReport =
  | InvoicePoReport
  | InvoiceReceiptReport
  | PoReceiptReport
  | ThreeWayReport;
export type InvoiceResult =
  | ReconciliationResult
  | InvoicePoResult
  | InvoiceReceiptResult;
