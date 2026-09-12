import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { DashboardPage } from "./dashboard-page";
import { RecentRuns } from "./recent-runs";
import { ActivityTrend } from "./activity-trend";
import {
  getIssues,
  getOverview,
  getTrends,
  getWorkload,
  DashboardRequestError,
} from "@/lib/api/dashboard";
import { listRuns } from "@/lib/api/runs";
import { overview, trends, workload } from "@/test/fixtures/dashboard";
import { savedRun } from "@/test/fixtures/runs";
import { ANALYSIS_REPORTS } from "@/test/fixtures/analyses";

const auth = vi.hoisted(() => ({ role: "ORG_ADMIN", refresh: vi.fn() }));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    refresh: auth.refresh,
    session: {
      active_organization_id: "org",
      memberships: [{ organization_id: "org", role: auth.role }],
    },
  }),
}));
vi.mock("@/lib/api/dashboard", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api/dashboard")>(
    "@/lib/api/dashboard",
  )),
  getOverview: vi.fn(),
  getTrends: vi.fn(),
  getIssues: vi.fn(),
  getWorkload: vi.fn(),
}));
vi.mock("@/lib/api/runs", () => ({ listRuns: vi.fn() }));
beforeEach(() => {
  auth.role = "ORG_ADMIN";
  vi.mocked(getOverview).mockReset().mockResolvedValue(overview);
  vi.mocked(getTrends).mockReset().mockResolvedValue(trends);
  vi.mocked(getIssues)
    .mockReset()
    .mockResolvedValue({ server_now: overview.server_now, items: [] });
  vi.mocked(getWorkload).mockReset().mockResolvedValue(workload);
  vi.mocked(listRuns)
    .mockReset()
    .mockResolvedValue({ items: [], next_cursor: null });
});
it("does not fetch dashboard data for members", () => {
  auth.role = "MEMBER";
  render(<DashboardPage />);
  expect(
    screen.getByRole("heading", { name: "Dashboard access required" }),
  ).toBeVisible();
  expect(getOverview).not.toHaveBeenCalled();
  expect(listRuns).not.toHaveBeenCalled();
});
for (const role of ["AP_MANAGER", "ORG_ADMIN"]) {
  it(`renders server counts and exact workload labels for ${role}`, async () => {
    auth.role = role;
    render(<DashboardPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading dashboard");
    await screen.findByRole("heading", { name: "Current backlog" });
    expect(
      within(screen.getByRole("region", { name: "Current backlog" })).getByText(
        "7",
      ),
    ).toBeVisible();
    expect(await screen.findByText("<script>member</script>")).toBeVisible();
    expect(screen.getByText("Inactive")).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    expect(listRuns).toHaveBeenCalledWith(
      { archived: false, limit: 5 },
      expect.any(AbortSignal),
    );
  });
}
it("changes the reporting window without local rebucketing and refreshes", async () => {
  const user = userEvent.setup();
  render(<DashboardPage />);
  await screen.findByRole("heading", { name: "Current backlog" });
  await user.selectOptions(screen.getByLabelText("Activity window"), "7d");
  await waitFor(() =>
    expect(getOverview).toHaveBeenLastCalledWith("7d", expect.any(AbortSignal)),
  );
  await user.click(screen.getByRole("button", { name: "Refresh dashboard" }));
  await waitFor(() => expect(getOverview).toHaveBeenCalledTimes(3));
});
it("focuses access failures and allows an explicit session refresh/retry", async () => {
  vi.mocked(getOverview).mockRejectedValueOnce(
    new DashboardRequestError(403, "Access changed"),
  );
  const user = userEvent.setup();
  render(<DashboardPage />);
  expect(await screen.findByRole("alert")).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Retry dashboard" }));
  await screen.findByRole("heading", { name: "Current backlog" });
  expect(auth.refresh).toHaveBeenCalled();
});
it("paginates workload and retains the Unassigned row", async () => {
  vi.mocked(getWorkload).mockResolvedValueOnce({
    ...workload,
    next_cursor: "next",
  });
  const user = userEvent.setup();
  render(<DashboardPage />);
  await screen.findByRole("table", { name: "Current assignee workload" });
  await user.click(screen.getByRole("button", { name: "Next assignees" }));
  await waitFor(() =>
    expect(getWorkload).toHaveBeenLastCalledWith(
      "next",
      expect.any(AbortSignal),
    ),
  );
  await screen.findByRole("table", { name: "Current assignee workload" });
  await user.click(screen.getByRole("button", { name: "Previous assignees" }));
  await waitFor(() =>
    expect(getWorkload).toHaveBeenLastCalledWith(
      undefined,
      expect.any(AbortSignal),
    ),
  );
});
it("shows meaningful empty ages and zero-filled table instead of a decorative chart", async () => {
  vi.mocked(getOverview).mockResolvedValue({
    ...overview,
    age: {
      median_unresolved_age_seconds: null,
      oldest_unresolved_age_seconds: null,
    },
  });
  render(<DashboardPage />);
  expect(await screen.findAllByText("No unresolved findings")).toHaveLength(2);
});
it("provides a daily accessible table for every returned bucket", async () => {
  const user = userEvent.setup();
  render(<ActivityTrend trends={trends} />);
  await user.click(screen.getByText("Daily activity table", { exact: true }));
  expect(screen.getAllByRole("row")).toHaveLength(31);
  expect(
    within(screen.getByRole("table")).getByText("2026-08-14"),
  ).toBeVisible();
});
it("keeps repeated runs and exact per-run currency strings separate", () => {
  const run = savedRun(
    ANALYSIS_REPORTS.find((report) => report.mode === "three-way")!,
  ).run;
  render(<RecentRuns runs={[run, { ...run, id: "repeat" }]} />);
  expect(screen.getAllByText("2,450.00")).toHaveLength(2);
  expect(screen.queryByText("4,900.00")).not.toBeInTheDocument();
  expect(
    screen.getAllByText("Potential disputed amount — this run"),
  ).toHaveLength(2);
});
