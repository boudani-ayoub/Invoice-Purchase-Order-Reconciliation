import type { MembershipRole } from "./auth";

export type ReportingWindow = "7d" | "30d" | "90d";
export interface DashboardPeriod {
  window: ReportingWindow;
  start: string;
  end: string;
}
export interface ActivityCounts {
  new_findings: number;
  resolution_events: number;
  reopen_events: number;
}
export interface DashboardOverview {
  server_now: string;
  period: DashboardPeriod;
  backlog: {
    open: number;
    in_review: number;
    unresolved: number;
    resolved: number;
    unassigned_unresolved: number;
    overdue: number;
    reminder_due: number;
  };
  activity: ActivityCounts;
  age: {
    median_unresolved_age_seconds: number | null;
    oldest_unresolved_age_seconds: number | null;
  };
}
export interface ActivityBucket extends ActivityCounts {
  bucket_start: string;
}
export interface DashboardTrends {
  server_now: string;
  period: DashboardPeriod;
  items: ActivityBucket[];
}
export interface DashboardIssues {
  server_now: string;
  items: Array<{ code: string; category: string; count: number }>;
}
export interface WorkloadRow {
  assignee_user_id: string | null;
  display_name: string | null;
  role: MembershipRole | null;
  active: boolean | null;
  open: number;
  in_review: number;
  unresolved: number;
  overdue: number;
}
export interface DashboardWorkload {
  server_now: string;
  unassigned: WorkloadRow;
  items: WorkloadRow[];
  next_cursor: string | null;
}
