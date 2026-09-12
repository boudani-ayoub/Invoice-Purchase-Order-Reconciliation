import {
  DASHBOARD_API_PATH,
  REPORTING_WINDOWS,
  WORKLOAD_PAGE_MAX,
  WORKLOAD_PAGE_SIZE,
} from "@/constants/dashboard";
import type {
  DashboardIssues,
  DashboardOverview,
  DashboardTrends,
  DashboardWorkload,
  ReportingWindow,
} from "@/types/dashboard";
import { apiFetch } from "./transport";
import { isObject } from "./reconciliation";

export class DashboardRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "DashboardRequestError";
  }
}
const text = (v: unknown): v is string => typeof v === "string";
const nullableText = (v: unknown) => v === null || text(v);
const timestamp = (v: unknown) => text(v) && Number.isFinite(Date.parse(v));
const count = (v: unknown) =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const duration = (v: unknown) =>
  v === null || (typeof v === "number" && Number.isFinite(v));
function counts(v: unknown, keys: string[]) {
  return isObject(v) && keys.every((k) => count(v[k]));
}
function period(v: unknown) {
  return (
    isObject(v) &&
    text(v.window) &&
    Object.hasOwn(REPORTING_WINDOWS, v.window) &&
    timestamp(v.start) &&
    timestamp(v.end)
  );
}
const activity = (v: unknown) =>
  counts(v, ["new_findings", "resolution_events", "reopen_events"]);
function invalid(): never {
  throw new DashboardRequestError(
    0,
    "The dashboard response could not be read. Refresh to try again.",
  );
}
async function request(path: string, signal?: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await apiFetch(`${DASHBOARD_API_PATH}/${path}`, { signal });
  } catch {
    throw new DashboardRequestError(
      0,
      "Unable to reach the dashboard. Check your connection and try again.",
    );
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "Your session expired. Sign in again.",
      403: "Manager dashboard access is required. Refresh your session and organization.",
      422: "Choose a supported reporting window or workload page.",
    };
    throw new DashboardRequestError(
      response.status,
      messages[response.status] ?? "The dashboard is unavailable. Try again.",
    );
  }
  try {
    return await response.json();
  } catch {
    return invalid();
  }
}
export async function getOverview(
  window: ReportingWindow,
  signal?: AbortSignal,
): Promise<DashboardOverview> {
  const v = await request(
    `overview?${new URLSearchParams({ window })}`,
    signal,
  );
  if (
    !isObject(v) ||
    !timestamp(v.server_now) ||
    !period(v.period) ||
    !activity(v.activity) ||
    !counts(v.backlog, [
      "open",
      "in_review",
      "unresolved",
      "resolved",
      "unassigned_unresolved",
      "overdue",
      "reminder_due",
    ]) ||
    !isObject(v.age) ||
    !duration(v.age.median_unresolved_age_seconds) ||
    !duration(v.age.oldest_unresolved_age_seconds)
  )
    return invalid();
  return v as unknown as DashboardOverview;
}
export async function getTrends(
  window: ReportingWindow,
  signal?: AbortSignal,
): Promise<DashboardTrends> {
  const v = await request(`trends?${new URLSearchParams({ window })}`, signal);
  if (
    !isObject(v) ||
    !timestamp(v.server_now) ||
    !period(v.period) ||
    !Array.isArray(v.items) ||
    v.items.length !== REPORTING_WINDOWS[window] ||
    !v.items.every(
      (row) => isObject(row) && timestamp(row.bucket_start) && activity(row),
    )
  )
    return invalid();
  return v as unknown as DashboardTrends;
}
export async function getIssues(
  signal?: AbortSignal,
): Promise<DashboardIssues> {
  const v = await request("issues", signal);
  if (
    !isObject(v) ||
    !timestamp(v.server_now) ||
    !Array.isArray(v.items) ||
    !v.items.every(
      (row) =>
        isObject(row) &&
        text(row.code) &&
        text(row.category) &&
        count(row.count),
    )
  )
    return invalid();
  return v as unknown as DashboardIssues;
}
function workloadRow(v: unknown) {
  return (
    isObject(v) &&
    counts(v, ["open", "in_review", "unresolved", "overdue"]) &&
    nullableText(v.assignee_user_id) &&
    nullableText(v.display_name) &&
    (v.active === null || typeof v.active === "boolean") &&
    (v.role === null ||
      ["MEMBER", "AP_MANAGER", "ORG_ADMIN"].includes(String(v.role)))
  );
}
export async function getWorkload(
  cursor?: string,
  signal?: AbortSignal,
): Promise<DashboardWorkload> {
  const params = new URLSearchParams({ limit: String(WORKLOAD_PAGE_SIZE) });
  if (cursor) params.set("cursor", cursor);
  const v = await request(`workload?${params}`, signal);
  if (
    !isObject(v) ||
    !timestamp(v.server_now) ||
    !workloadRow(v.unassigned) ||
    !nullableText(v.next_cursor) ||
    !Array.isArray(v.items) ||
    v.items.length > WORKLOAD_PAGE_MAX ||
    !v.items.every(workloadRow)
  )
    return invalid();
  return v as unknown as DashboardWorkload;
}
