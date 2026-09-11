import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import {
  ASSIGNEES_API_PATH,
  EVENT_LABELS,
  FINDINGS_API_PATH,
  FINDING_STATUSES,
  WORKFLOW_CONFLICT,
  WORKFLOW_PAGE_SIZE,
  findingApiPath,
} from "@/constants/workflow";
import type {
  Assignee,
  Finding,
  FindingDetail,
  FindingEvent,
  FindingQueue,
  FindingState,
  FindingStatus,
  PageResult,
  WorkflowMutation,
  WorkflowQuery,
} from "@/types/workflow";
import { isObject } from "./reconciliation";
import { apiFetch } from "./transport";

export class WorkflowRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "WorkflowRequestError";
  }
}
const text = (v: unknown): v is string => typeof v === "string";
const nullableText = (v: unknown) => v === null || text(v);
const integer = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const timestamp = (v: unknown) => text(v) && Number.isFinite(Date.parse(v));
const nullableTime = (v: unknown) => v === null || timestamp(v);
function isState(v: unknown): v is FindingState {
  return (
    isObject(v) &&
    ["id", "analysis_run_id", "code", "category"].every((k) => text(v[k])) &&
    text(v.status) &&
    Object.hasOwn(FINDING_STATUSES, v.status) &&
    integer(v.version) &&
    nullableText(v.assignee_user_id) &&
    nullableText(v.resolved_by_user_id) &&
    ["due_at", "reminder_at", "resolved_at"].every((k) => nullableTime(v[k])) &&
    timestamp(v.created_at) &&
    timestamp(v.updated_at) &&
    typeof v.overdue === "boolean" &&
    typeof v.reminder_due === "boolean"
  );
}
function isFinding(v: unknown): v is Finding {
  if (!isState(v) || !isObject(v)) return false;
  const r = v.reference,
    run = v.run;
  return (
    isObject(r) &&
    isObject(run) &&
    text(run.id) &&
    nullableText(run.title) &&
    text(run.mode) &&
    Object.hasOwn(ANALYSIS_MODES, run.mode) &&
    typeof run.archived === "boolean" &&
    ["invoice_number", "receipt_number", "supplier_code"].every((k) =>
      nullableText(r[k]),
    ) &&
    ["invoice_line_number", "receipt_line_number"].every(
      (k) => r[k] === null || integer(r[k]),
    ) &&
    ["source_row_number", "po_line_number"].every((k) => integer(r[k])) &&
    text(r.po_number) &&
    text(r.item_code) &&
    typeof r.po_reference_resolved === "boolean" &&
    typeof r.item_master_resolved === "boolean" &&
    (v.assignee === null ||
      (isObject(v.assignee) &&
        text(v.assignee.display_name) &&
        typeof v.assignee.active === "boolean"))
  );
}
function isEvent(v: unknown): v is FindingEvent {
  if (!isObject(v) || !isObject(v.metadata)) return false;
  const metadata = v.metadata;
  return (
    isObject(v) &&
    ["id", "finding_id", "actor_user_id", "request_id"].every((k) =>
      text(v[k]),
    ) &&
    text(v.event_type) &&
    Object.hasOwn(EVENT_LABELS, v.event_type) &&
    timestamp(v.created_at) &&
    nullableText(v.message) &&
    isObject(v.metadata) &&
    ["previous", "new"].every(
      (k) => metadata[k] === undefined || nullableText(metadata[k]),
    ) &&
    ["previous_version", "new_version"].every(
      (k) => metadata[k] === undefined || integer(metadata[k]),
    )
  );
}
function isAssignee(v: unknown): v is Assignee {
  return (
    isObject(v) &&
    text(v.user_id) &&
    text(v.display_name) &&
    ["MEMBER", "AP_MANAGER", "ORG_ADMIN"].includes(String(v.role))
  );
}
function page<T>(v: unknown, guard: (v: unknown) => v is T): PageResult<T> {
  if (
    !isObject(v) ||
    !Array.isArray(v.items) ||
    !v.items.every(guard) ||
    !nullableText(v.next_cursor)
  )
    return invalid();
  return v as unknown as PageResult<T>;
}
function invalid(): never {
  throw new WorkflowRequestError(
    0,
    "The workflow response could not be read. Refresh the finding and timeline before retrying a change.",
  );
}
async function request(path: string, options?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await apiFetch(path, options);
  } catch {
    throw new WorkflowRequestError(
      0,
      "Unable to reach workflow. Check your connection, then refresh the finding and timeline before retrying a change.",
    );
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "Your session expired. Sign in again.",
      403: "Your access could not be verified. Refresh your session and organization.",
      404: "Finding or member not found or no longer accessible in this organization.",
      409: WORKFLOW_CONFLICT,
      413: "The request is too large. Shorten the workflow text.",
      422: "Check the workflow fields, resolution note, and allowed transition. Change at least one field before saving.",
    };
    throw new WorkflowRequestError(
      response.status,
      messages[response.status] ??
        "No successful workflow change was confirmed. Refresh the finding and timeline before retrying.",
    );
  }
  try {
    return await response.json();
  } catch {
    return invalid();
  }
}
const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
export async function listFindings(
  query: WorkflowQuery,
  signal?: AbortSignal,
): Promise<FindingQueue> {
  const params = new URLSearchParams({ limit: String(WORKFLOW_PAGE_SIZE) });
  for (const [key, value] of Object.entries(query))
    if (value !== undefined && value !== "") params.set(key, String(value));
  const value = await request(`${FINDINGS_API_PATH}?${params}`, { signal });
  const result = page(value, isFinding);
  if (!isObject(value) || !timestamp(value.server_now)) return invalid();
  return { ...result, server_now: value.server_now as string };
}
export async function getFinding(
  id: string,
  signal?: AbortSignal,
): Promise<FindingDetail> {
  const value = await request(findingApiPath(id), { signal });
  if (
    !isObject(value) ||
    !isFinding(value.finding) ||
    !isObject(value.finding) ||
    !nullableText(value.finding.resolution_note) ||
    !timestamp(value.server_now)
  )
    return invalid();
  return value as unknown as FindingDetail;
}
export async function listFindingEvents(
  id: string,
  cursor?: string,
  signal?: AbortSignal,
): Promise<PageResult<FindingEvent>> {
  const params = new URLSearchParams({ limit: String(WORKFLOW_PAGE_SIZE) });
  if (cursor) params.set("cursor", cursor);
  return page(
    await request(`${findingApiPath(id)}/events?${params}`, { signal }),
    isEvent,
  );
}
export async function listAssignees(
  cursor?: string,
  signal?: AbortSignal,
): Promise<PageResult<Assignee>> {
  const params = new URLSearchParams({ limit: String(WORKFLOW_PAGE_SIZE) });
  if (cursor) params.set("cursor", cursor);
  return page(
    await request(`${ASSIGNEES_API_PATH}?${params}`, { signal }),
    isAssignee,
  );
}
export async function manageFinding(
  id: string,
  body: WorkflowMutation,
): Promise<FindingState> {
  const value = await request(findingApiPath(id), json("PATCH", body));
  if (!isState(value)) return invalid();
  return value;
}
export async function transitionFinding(
  id: string,
  version: number,
  target: FindingStatus,
  note?: string,
): Promise<FindingState> {
  const value = await request(
    `${findingApiPath(id)}/transition`,
    json("POST", {
      expected_version: version,
      target_status: target,
      ...(note !== undefined ? { resolution_note: note } : {}),
    }),
  );
  if (!isState(value)) return invalid();
  return value;
}
export async function commentFinding(
  id: string,
  value: string,
): Promise<FindingEvent> {
  const event = await request(
    `${findingApiPath(id)}/comments`,
    json("POST", { text: value }),
  );
  if (!isEvent(event)) return invalid();
  return event;
}
