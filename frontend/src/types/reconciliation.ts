export type ReconciliationStatus = "MATCHED" | "REVIEW_REQUIRED";

export interface ReconciliationResult {
  supplier_id: string;
  invoice_number: string;
  invoice_line_number: number;
  invoice_date: string;
  po_number: string;
  po_line_number: number;
  item_code: string;
  status: ReconciliationStatus;
  issues: string[];
  ordered_quantity: string | null;
  received_quantity: string | null;
  previously_invoiced_quantity: string;
  current_invoiced_quantity: string;
  supported_quantity: string | null;
  invoice_unit_price: string;
  po_unit_price: string | null;
  potential_disputed_amount: string;
  currency: string;
}

export interface ReconciliationSummary {
  invoices_processed: number;
  invoice_lines_processed: number;
  matched_lines: number;
  review_required_lines: number;
  issue_counts: Record<string, number>;
  disputed_amounts: Record<string, string>;
}

export interface ReconciliationReport {
  summary: ReconciliationSummary;
  results: ReconciliationResult[];
}

export interface CsvValidationIssue {
  file: string;
  source: string;
  row: number | null;
  column: string;
  value: string;
  reason: string;
}

export type ReconciliationErrorDetail =
  | { kind: "authorization" }
  | { kind: "storage_capacity" }
  | {
      kind: "validation";
      message: string;
      issues: CsvValidationIssue[];
    }
  | {
      kind: "file_too_large";
      file: string;
      maxBytes: number;
    }
  | {
      kind: "missing_upload";
      fields: string[];
    }
  | {
      kind: "network";
    }
  | {
      kind: "timeout";
    }
  | {
      kind: "server";
    }
  | {
      kind: "unexpected_response";
    };
