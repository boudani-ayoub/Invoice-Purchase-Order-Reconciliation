import {
  ANALYSIS_MODES,
  analysisApiPath,
  FULFILLMENT_LABELS,
} from "@/constants/analysis-modes";
import type { UploadFiles } from "@/constants/uploads";
import type {
  AnalysisMode,
  AnalysisReport,
  PoReceiptResult,
  OrphanReceipt,
} from "@/types/analysis";
import {
  isObject,
  isStringRecord,
  isNumberRecord,
  isReconciliationReport,
  requestFiles,
  ReconciliationRequestError,
} from "./reconciliation";

const stringFields = (
  value: Record<string, unknown>,
  fields: readonly string[],
) => fields.every((field) => typeof value[field] === "string");
const nullableString = (value: unknown) =>
  value === null || typeof value === "string";

function isInvoiceLine(value: unknown): boolean {
  return (
    isObject(value) &&
    stringFields(value, [
      "supplier_id",
      "invoice_number",
      "invoice_date",
      "po_number",
      "item_code",
      "currency",
      "previously_invoiced_quantity",
      "current_invoiced_quantity",
      "invoice_unit_price",
    ]) &&
    typeof value.invoice_line_number === "number" &&
    typeof value.po_line_number === "number" &&
    ["MATCHED", "REVIEW_REQUIRED"].includes(String(value.status)) &&
    Array.isArray(value.issues) &&
    value.issues.every((issue) => typeof issue === "string") &&
    nullableString(value.supported_quantity)
  );
}
function isFulfillmentLine(value: unknown): value is PoReceiptResult {
  return (
    isObject(value) &&
    stringFields(value, [
      "po_number",
      "item_code",
      "supplier_id",
      "ordered_quantity",
      "received_quantity",
      "outstanding_quantity",
      "over_received_quantity",
      "po_unit_price",
      "currency",
      "outstanding_ordered_value",
      "over_received_reference_value",
    ]) &&
    typeof value.po_line_number === "number" &&
    typeof value.status === "string" &&
    Object.hasOwn(FULFILLMENT_LABELS, value.status)
  );
}
function isOrphan(value: unknown): value is OrphanReceipt {
  return (
    isObject(value) &&
    stringFields(value, [
      "receipt_id",
      "receipt_date",
      "po_number",
      "item_code",
      "received_quantity",
      "issue",
    ]) &&
    typeof value.po_line_number === "number" &&
    typeof value.receipt_line_number === "number"
  );
}

export function isAnalysisReport(value: unknown): value is AnalysisReport {
  if (
    !isObject(value) ||
    !isObject(value.summary) ||
    !Array.isArray(value.results)
  )
    return false;
  const summary = value.summary;
  const statusCounts = summary.status_counts;
  if (value.mode === "three-way") return isReconciliationReport(value);
  if (value.mode === "po-receipt") {
    return (
      [
        "purchase_orders_processed",
        "po_lines_processed",
        "receipt_lines_processed",
        "orphan_receipt_lines",
      ].every((key) => typeof summary[key] === "number") &&
      isNumberRecord(statusCounts) &&
      Object.keys(FULFILLMENT_LABELS).every(
        (key) => typeof statusCounts[key] === "number",
      ) &&
      isStringRecord(summary.outstanding_values) &&
      isStringRecord(summary.over_received_values) &&
      value.results.every(isFulfillmentLine) &&
      Array.isArray(value.orphan_receipts) &&
      value.orphan_receipts.every(isOrphan)
    );
  }
  if (
    ![
      "invoices_processed",
      "invoice_lines_processed",
      "matched_lines",
      "review_required_lines",
    ].every((key) => typeof summary[key] === "number") ||
    !isNumberRecord(summary.issue_counts) ||
    !value.results.every(isInvoiceLine)
  )
    return false;
  if (value.mode === "invoice-po")
    return (
      isStringRecord(summary.disputed_amounts) &&
      value.results.every(
        (row) =>
          isObject(row) &&
          nullableString(row.ordered_quantity) &&
          nullableString(row.po_unit_price) &&
          typeof row.potential_disputed_amount === "string",
      )
    );
  if (value.mode === "invoice-receipt")
    return (
      isStringRecord(summary.unsupported_amounts) &&
      value.results.every(
        (row) =>
          isObject(row) &&
          typeof row.received_quantity === "string" &&
          typeof row.potential_unsupported_amount === "string",
      )
    );
  return false;
}

export async function analyzeFiles(
  mode: AnalysisMode,
  files: UploadFiles,
): Promise<AnalysisReport> {
  const payload = await requestFiles(
    files,
    analysisApiPath(mode),
    ANALYSIS_MODES[mode].requiredSources,
  );
  if (!isAnalysisReport(payload) || payload.mode !== mode)
    throw new ReconciliationRequestError({ kind: "unexpected_response" });
  return payload;
}
