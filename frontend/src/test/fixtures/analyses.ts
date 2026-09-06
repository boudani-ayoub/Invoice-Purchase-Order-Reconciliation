import type {
  AnalysisReport,
  InvoicePoReport,
  InvoiceReceiptReport,
  PoReceiptReport,
  ThreeWayReport,
} from "@/types/analysis";
import { RECONCILIATION_REPORT_FIXTURE } from "./reconciliation";

const invoice = {
  supplier_id: "SUP-A",
  invoice_number: "INV-A",
  invoice_line_number: 1,
  invoice_date: "2026-01-01",
  po_number: "PO-A",
  po_line_number: 1,
  item_code: "ITEM-A",
  status: "MATCHED" as const,
  issues: [],
  previously_invoiced_quantity: "0",
  current_invoiced_quantity: "10",
  supported_quantity: "10",
  invoice_unit_price: "2.50",
  currency: "EUR",
};
const summary = {
  invoices_processed: 1,
  invoice_lines_processed: 1,
  matched_lines: 1,
  review_required_lines: 0,
  issue_counts: {},
};

export const INVOICE_PO_REPORT: InvoicePoReport = {
  mode: "invoice-po",
  summary: { ...summary, disputed_amounts: {} },
  results: [
    {
      ...invoice,
      ordered_quantity: "10",
      po_unit_price: "2.50",
      potential_disputed_amount: "0.00",
    },
  ],
};
export const INVOICE_RECEIPT_REPORT: InvoiceReceiptReport = {
  mode: "invoice-receipt",
  summary: { ...summary, unsupported_amounts: {} },
  results: [
    {
      ...invoice,
      received_quantity: "10",
      potential_unsupported_amount: "0.00",
    },
  ],
};
export const PO_RECEIPT_REPORT: PoReceiptReport = {
  mode: "po-receipt",
  summary: {
    purchase_orders_processed: 1,
    po_lines_processed: 1,
    receipt_lines_processed: 1,
    status_counts: {
      FULLY_RECEIVED: 0,
      PARTIALLY_RECEIVED: 1,
      NOT_RECEIVED: 0,
      OVER_RECEIVED: 0,
    },
    orphan_receipt_lines: 1,
    outstanding_values: { EUR: "5.00" },
    over_received_values: {},
  },
  results: [
    {
      po_number: "PO-A",
      po_line_number: 1,
      item_code: "ITEM-A",
      supplier_id: "SUP-A",
      status: "PARTIALLY_RECEIVED",
      ordered_quantity: "10",
      received_quantity: "8",
      outstanding_quantity: "2",
      over_received_quantity: "0",
      po_unit_price: "2.50",
      currency: "EUR",
      outstanding_ordered_value: "5.00",
      over_received_reference_value: "0.00",
    },
  ],
  orphan_receipts: [
    {
      receipt_id: "ORPHAN",
      receipt_line_number: 1,
      receipt_date: "2026-01-01",
      po_number: "ABSENT",
      po_line_number: 1,
      item_code: "ITEM-A",
      received_quantity: "1",
      issue: "UNKNOWN_PO",
    },
  ],
};
export const THREE_WAY_REPORT: ThreeWayReport = {
  ...RECONCILIATION_REPORT_FIXTURE,
  mode: "three-way",
};
export const ANALYSIS_REPORTS: AnalysisReport[] = [
  INVOICE_PO_REPORT,
  INVOICE_RECEIPT_REPORT,
  PO_RECEIPT_REPORT,
  THREE_WAY_REPORT,
];
