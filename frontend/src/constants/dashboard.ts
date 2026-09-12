import type { MembershipRole } from "@/types/auth";
import type { ActivityCounts, ReportingWindow } from "@/types/dashboard";

export const DASHBOARD_PATH = "/dashboard";
export const DASHBOARD_API_PATH = "/api/v1/dashboard";
export const DEFAULT_REPORTING_WINDOW: ReportingWindow = "30d";
export const REPORTING_WINDOWS: Record<ReportingWindow, number> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
};
export const RECENT_RUN_LIMIT = 5;
export const WORKLOAD_PAGE_SIZE = 25;
export const WORKLOAD_PAGE_MAX = 100;
export const ACTIVITY_SERIES: Array<{
  key: keyof ActivityCounts;
  label: string;
  dash?: string;
  className: string;
}> = [
  { key: "new_findings", label: "New findings", className: "text-primary" },
  {
    key: "resolution_events",
    label: "Resolution actions",
    dash: "8 4",
    className: "text-foreground",
  },
  {
    key: "reopen_events",
    label: "Reopen actions",
    dash: "2 4",
    className: "text-warning-foreground",
  },
];
export const canViewDashboard = (role?: MembershipRole | null) =>
  role === "AP_MANAGER" || role === "ORG_ADMIN";
