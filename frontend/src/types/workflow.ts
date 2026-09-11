import type { AnalysisMode } from "./analysis";
import type { MembershipRole } from "./auth";

export type FindingStatus = "OPEN" | "IN_REVIEW" | "RESOLVED";
export type FindingEventType =
  | "COMMENT_ADDED"
  | "ASSIGNEE_CHANGED"
  | "DUE_DATE_CHANGED"
  | "REMINDER_CHANGED"
  | "STATUS_CHANGED"
  | "RESOLVED"
  | "REOPENED";
export interface FindingState {
  id: string;
  analysis_run_id: string;
  code: string;
  category: string;
  status: FindingStatus;
  assignee_user_id: string | null;
  due_at: string | null;
  reminder_at: string | null;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  overdue: boolean;
  reminder_due: boolean;
}
export interface Finding extends FindingState {
  assignee: { display_name: string; active: boolean } | null;
  run: {
    id: string;
    title: string | null;
    mode: AnalysisMode;
    archived: boolean;
  };
  reference: {
    invoice_number: string | null;
    invoice_line_number: number | null;
    receipt_number: string | null;
    receipt_line_number: number | null;
    supplier_code: string | null;
    source_row_number: number;
    po_number: string;
    po_line_number: number;
    item_code: string;
    po_reference_resolved: boolean;
    item_master_resolved: boolean;
  };
}
export interface FindingDetail {
  finding: Finding & { resolution_note: string | null };
  server_now: string;
}
export interface PageResult<T> {
  items: T[];
  next_cursor: string | null;
}
export interface FindingQueue extends PageResult<Finding> {
  server_now: string;
}
export interface Assignee {
  user_id: string;
  display_name: string;
  role: MembershipRole;
}
export interface FindingEvent {
  id: string;
  finding_id: string;
  actor_user_id: string;
  event_type: FindingEventType;
  request_id: string;
  created_at: string;
  message: string | null;
  metadata: {
    previous?: string | null;
    new?: string | null;
    previous_version?: number;
    new_version?: number;
  };
}
export interface WorkflowQuery {
  run_id?: string;
  status?: FindingStatus;
  assignee?: "me" | "unassigned" | string;
  overdue?: boolean;
  reminder_due?: boolean;
  cursor?: string;
}
export interface WorkflowMutation {
  expected_version: number;
  assignee_user_id?: string | null;
  due_at?: string | null;
  reminder_at?: string | null;
}
