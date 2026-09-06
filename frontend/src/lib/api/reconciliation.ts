import { getApiBaseUrl, getReconciliationTimeoutMs } from "@/lib/config";
import type {
  CsvValidationIssue,
  ReconciliationErrorDetail,
  ReconciliationReport,
  ReconciliationResult,
  ReconciliationSummary,
} from "@/types/reconciliation";
import type { UploadFiles } from "@/constants/uploads";

const RECONCILIATION_PATH = "/api/v1/reconcile";

export class ReconciliationRequestError extends Error {
  constructor(public readonly detail: ReconciliationErrorDetail) {
    super(detail.kind);
    this.name = "ReconciliationRequestError";
  }
}

export async function reconcileFiles(files: UploadFiles): Promise<ReconciliationReport> {
  const formData = new FormData();
  for (const [field, file] of Object.entries(files)) {
    if (!file) {
      throw new ReconciliationRequestError({ kind: "missing_upload", fields: [field] });
    }
    formData.append(field, file);
  }

  const abortController = new AbortController();
  const timeout = window.setTimeout(
    () => abortController.abort(),
    getReconciliationTimeoutMs(),
  );
  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${RECONCILIATION_PATH}`, {
      method: "POST",
      body: formData,
      signal: abortController.signal,
    });
  } catch {
    throw new ReconciliationRequestError({
      kind: abortController.signal.aborted ? "timeout" : "network",
    });
  } finally {
    window.clearTimeout(timeout);
  }

  const payload = await readJson(response);
  if (response.ok) {
    if (isReconciliationReport(payload)) {
      return payload;
    }
    throw new ReconciliationRequestError({ kind: "unexpected_response" });
  }

  if (response.status === 413 && isFileTooLargePayload(payload)) {
    throw new ReconciliationRequestError({
      kind: "file_too_large",
      file: payload.file,
      maxBytes: payload.max_bytes,
    });
  }
  if (response.status === 422 && isValidationPayload(payload)) {
    throw new ReconciliationRequestError({
      kind: "validation",
      message: payload.message,
      issues: payload.issues,
    });
  }
  if (response.status === 422 && isFastApiValidationPayload(payload)) {
    throw new ReconciliationRequestError({
      kind: "missing_upload",
      fields: payload.detail
        .filter((issue) => issue.type === "missing")
        .map((issue) => issue.loc.at(-1))
        .filter((field): field is string => typeof field === "string"),
    });
  }
  if (response.status >= 500) {
    throw new ReconciliationRequestError({ kind: "server" });
  }

  throw new ReconciliationRequestError({ kind: "unexpected_response" });
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ReconciliationRequestError({ kind: "unexpected_response" });
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return isObject(value) && Object.values(value).every((item) => typeof item === "string");
}

function isNumberRecord(value: unknown): value is Record<string, number> {
  return isObject(value) && Object.values(value).every((item) => typeof item === "number");
}

function isReconciliationSummary(value: unknown): value is ReconciliationSummary {
  return (
    isObject(value) &&
    typeof value.invoices_processed === "number" &&
    typeof value.invoice_lines_processed === "number" &&
    typeof value.matched_lines === "number" &&
    typeof value.review_required_lines === "number" &&
    isNumberRecord(value.issue_counts) &&
    isStringRecord(value.disputed_amounts)
  );
}

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isReconciliationResult(value: unknown): value is ReconciliationResult {
  return (
    isObject(value) &&
    typeof value.supplier_id === "string" &&
    typeof value.invoice_number === "string" &&
    typeof value.invoice_line_number === "number" &&
    typeof value.invoice_date === "string" &&
    typeof value.po_number === "string" &&
    typeof value.po_line_number === "number" &&
    typeof value.item_code === "string" &&
    (value.status === "MATCHED" || value.status === "REVIEW_REQUIRED") &&
    Array.isArray(value.issues) &&
    value.issues.every((issue) => typeof issue === "string") &&
    isNullableString(value.ordered_quantity) &&
    isNullableString(value.received_quantity) &&
    typeof value.previously_invoiced_quantity === "string" &&
    typeof value.current_invoiced_quantity === "string" &&
    isNullableString(value.supported_quantity) &&
    typeof value.invoice_unit_price === "string" &&
    isNullableString(value.po_unit_price) &&
    typeof value.potential_disputed_amount === "string" &&
    typeof value.currency === "string"
  );
}

function isReconciliationReport(value: unknown): value is ReconciliationReport {
  return (
    isObject(value) &&
    isReconciliationSummary(value.summary) &&
    Array.isArray(value.results) &&
    value.results.every(isReconciliationResult)
  );
}

function isCsvValidationIssue(value: unknown): value is CsvValidationIssue {
  return (
    isObject(value) &&
    typeof value.file === "string" &&
    typeof value.source === "string" &&
    (typeof value.row === "number" || value.row === null) &&
    typeof value.column === "string" &&
    typeof value.value === "string" &&
    typeof value.reason === "string"
  );
}

function isValidationPayload(
  value: unknown,
): value is { error: "validation_error"; message: string; issues: CsvValidationIssue[] } {
  return (
    isObject(value) &&
    value.error === "validation_error" &&
    typeof value.message === "string" &&
    Array.isArray(value.issues) &&
    value.issues.every(isCsvValidationIssue)
  );
}

function isFileTooLargePayload(
  value: unknown,
): value is { error: "file_too_large"; file: string; max_bytes: number } {
  return (
    isObject(value) &&
    value.error === "file_too_large" &&
    typeof value.file === "string" &&
    typeof value.max_bytes === "number"
  );
}

interface FastApiValidationIssue {
  type: string;
  loc: unknown[];
}

function isFastApiValidationPayload(value: unknown): value is { detail: FastApiValidationIssue[] } {
  return (
    isObject(value) &&
    Array.isArray(value.detail) &&
    value.detail.every(
      (issue) => isObject(issue) && typeof issue.type === "string" && Array.isArray(issue.loc),
    )
  );
}
