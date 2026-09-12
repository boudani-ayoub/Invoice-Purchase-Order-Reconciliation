import type {
  DashboardOverview,
  DashboardTrends,
  DashboardWorkload,
} from "@/types/dashboard";

export const overview: DashboardOverview = {
  server_now: "2026-09-12T12:00:00+00:00",
  period: {
    window: "30d",
    start: "2026-08-14T00:00:00+00:00",
    end: "2026-09-12T12:00:00+00:00",
  },
  backlog: {
    open: 5,
    in_review: 2,
    unresolved: 7,
    resolved: 3,
    unassigned_unresolved: 4,
    overdue: 1,
    reminder_due: 2,
  },
  activity: { new_findings: 10, resolution_events: 4, reopen_events: 1 },
  age: {
    median_unresolved_age_seconds: 86400,
    oldest_unresolved_age_seconds: 172800,
  },
};
export const trends: DashboardTrends = {
  server_now: overview.server_now,
  period: overview.period,
  items: Array.from({ length: 30 }, (_, i) => ({
    bucket_start: new Date(
      Date.parse(overview.period.start) + i * 86400000,
    ).toISOString(),
    new_findings: i === 0 ? 10 : 0,
    resolution_events: i === 1 ? 4 : 0,
    reopen_events: i === 2 ? 1 : 0,
  })),
};
export const workload: DashboardWorkload = {
  server_now: overview.server_now,
  next_cursor: null,
  unassigned: {
    assignee_user_id: null,
    display_name: null,
    active: null,
    role: null,
    open: 3,
    in_review: 1,
    unresolved: 4,
    overdue: 1,
  },
  items: [
    {
      assignee_user_id: "assignee-1",
      display_name: "<script>member</script>",
      active: false,
      role: "MEMBER",
      open: 2,
      in_review: 1,
      unresolved: 3,
      overdue: 0,
    },
  ],
};
