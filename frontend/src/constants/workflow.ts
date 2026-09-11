import type { FindingEventType, FindingStatus } from "@/types/workflow";

export const WORK_PATH = "/work";
export const FINDINGS_API_PATH = "/api/v1/findings";
export const ASSIGNEES_API_PATH = "/api/v1/workflow/assignees";
export const WORKFLOW_PAGE_SIZE = 25;
export const WORKFLOW_TEXT_LIMIT = 4000;
export const WORKFLOW_CONFLICT =
  "This finding changed. Refresh before editing again.";
export const WORKFLOW_RESOLUTION_COPY =
  "Resolved closes this investigation only. It does not approve payment, waive a discrepancy, or change source evidence or saved results.";
export const WORKFLOW_REMINDER_COPY =
  "Reminders are in-app follow-up dates. No email or push notification is sent when the app is closed. Refresh to check current due states.";
export const FINDING_STATUSES: Record<FindingStatus, string> = {
  OPEN: "Open",
  IN_REVIEW: "In review",
  RESOLVED: "Resolved",
};
export const EVENT_LABELS: Record<FindingEventType, string> = {
  COMMENT_ADDED: "Comment added",
  ASSIGNEE_CHANGED: "Assignee changed",
  DUE_DATE_CHANGED: "Due date changed",
  REMINDER_CHANGED: "Reminder changed",
  STATUS_CHANGED: "Review started",
  RESOLVED: "Resolved",
  REOPENED: "Reopened",
};
export const findingPath = (id: string) =>
  `${WORK_PATH}/${encodeURIComponent(id)}`;
export const findingApiPath = (id: string) =>
  `${FINDINGS_API_PATH}/${encodeURIComponent(id)}`;
export const runWorkPath = (runId: string) =>
  `${WORK_PATH}?${new URLSearchParams({ run_id: runId })}`;
