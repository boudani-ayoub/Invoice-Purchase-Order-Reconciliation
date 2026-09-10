import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import {
  createRunPath,
  HISTORY_PAGE_SIZE,
  RUN_CONFLICT_MESSAGE,
  RUNS_API_PATH,
  runApiPath,
} from "@/constants/runs";
import type { UploadFiles } from "@/constants/uploads";
import type { AnalysisMode } from "@/types/analysis";
import type {
  HistoryQuery,
  PersistentRunCreateResponse,
  RunDetail,
  RunListItem,
  RunListResponse,
  RunMetadata,
  RunMutation,
  SourceProvenance,
} from "@/types/runs";
import { isAnalysisReport } from "./analyses";
import {
  isObject,
  ReconciliationRequestError,
  requestFiles,
} from "./reconciliation";
import { apiFetch } from "./transport";

export class RunRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "RunRequestError";
  }
}
const nullableText = (value: unknown) =>
  value === null || typeof value === "string";
const positiveInteger = (value: unknown) =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
function isRun(value: unknown): value is RunListItem {
  return (
    isObject(value) &&
    typeof value.id === "string" &&
    typeof value.mode === "string" &&
    Object.hasOwn(ANALYSIS_MODES, value.mode) &&
    value.status === "COMPLETED" &&
    nullableText(value.title) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string" &&
    nullableText(value.archived_at) &&
    positiveInteger(value.version) &&
    nullableText(value.created_by_user_id) &&
    isAnalysisReport({
      mode: value.mode,
      summary: value.summary,
      results: [],
      orphan_receipts: [],
    })
  );
}
function isMetadata(value: unknown): value is RunMetadata {
  return isRun(value) && "note" in value && nullableText(value.note);
}
function isCreated(value: unknown): value is PersistentRunCreateResponse {
  return (
    isObject(value) &&
    isMetadata(value.run) &&
    isAnalysisReport(value.report) &&
    value.run.mode === value.report.mode
  );
}
function isSource(value: unknown): value is SourceProvenance {
  return (
    isObject(value) &&
    ["purchase_orders", "receipts", "invoices"].includes(
      String(value.source_type),
    ) &&
    typeof value.filename === "string" &&
    typeof value.size_bytes === "number" &&
    Number.isSafeInteger(value.size_bytes) &&
    value.size_bytes >= 0 &&
    typeof value.sha256 === "string" &&
    /^[a-f0-9]{64}$/.test(value.sha256) &&
    typeof value.created_at === "string"
  );
}
async function request(path: string, options?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await apiFetch(path, options);
  } catch {
    throw new RunRequestError(
      0,
      "Unable to reach saved history. Check your connection and try again.",
    );
  }
  if (!response.ok) {
    const message =
      response.status === 409
        ? RUN_CONFLICT_MESSAGE
        : response.status === 404
          ? "Run not found or no longer accessible in this organization."
          : response.status === 401
            ? "Your session expired. Sign in again."
            : response.status === 403
              ? "Your access could not be verified. Refresh your session and organization."
              : response.status === 422
                ? "Check the metadata fields and try again."
                : "The saved run request failed. No successful change was confirmed.";
    throw new RunRequestError(response.status, message);
  }
  try {
    return await response.json();
  } catch {
    throw new RunRequestError(0, "The saved run response could not be read.");
  }
}
function invalid(): never {
  throw new RunRequestError(0, "The saved run response could not be read.");
}

export async function createRun(
  mode: AnalysisMode,
  files: UploadFiles,
): Promise<PersistentRunCreateResponse> {
  const payload = await requestFiles(
    files,
    createRunPath(mode),
    ANALYSIS_MODES[mode].requiredSources,
  );
  if (!isCreated(payload) || payload.report.mode !== mode)
    throw new ReconciliationRequestError({ kind: "unexpected_response" });
  return payload;
}
export async function listRuns(
  query: HistoryQuery,
  signal?: AbortSignal,
): Promise<RunListResponse> {
  const params = new URLSearchParams({
    archived: String(query.archived),
    limit: String(HISTORY_PAGE_SIZE),
  });
  if (query.mode) params.set("mode", query.mode);
  if (query.cursor) params.set("cursor", query.cursor);
  const payload = await request(`${RUNS_API_PATH}?${params}`, { signal });
  if (
    !isObject(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isRun) ||
    !nullableText(payload.next_cursor)
  )
    return invalid();
  return payload as unknown as RunListResponse;
}
export async function getRun(
  id: string,
  signal?: AbortSignal,
): Promise<RunDetail> {
  const payload = await request(runApiPath(id), { signal });
  if (
    !isCreated(payload) ||
    !("sources" in payload) ||
    !Array.isArray(payload.sources) ||
    !payload.sources.every(isSource) ||
    !("engine_version" in payload) ||
    typeof payload.engine_version !== "string" ||
    !("schema_version" in payload) ||
    !positiveInteger(payload.schema_version)
  )
    return invalid();
  return payload as RunDetail;
}
export async function updateRun(
  id: string,
  mutation: RunMutation,
): Promise<RunMetadata> {
  const payload = await request(runApiPath(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mutation),
  });
  if (!isMetadata(payload)) return invalid();
  return payload;
}
export async function archiveRun(
  id: string,
  version: number,
  archived: boolean,
): Promise<RunMetadata> {
  const payload = await request(
    `${runApiPath(id)}/${archived ? "archive" : "restore"}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: version }),
    },
  );
  if (!isMetadata(payload)) return invalid();
  return payload;
}
