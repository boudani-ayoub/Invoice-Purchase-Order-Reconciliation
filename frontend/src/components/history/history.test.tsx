import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { HistoryPage } from "./history-page";
import { RunDetailPage } from "./run-detail";
import { RunActions } from "./run-actions";
import {
  archiveRun,
  getRun,
  listRuns,
  RunRequestError,
  updateRun,
} from "@/lib/api/runs";
import { ANALYSIS_REPORTS } from "@/test/fixtures/analyses";
import { savedRun } from "@/test/fixtures/runs";
import { RUN_CONFLICT_MESSAGE, runPath } from "@/constants/runs";

const active = vi.hoisted(() => ({ role: "ORG_ADMIN" }));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    session: {
      active_organization_id: "org",
      memberships: [{ organization_id: "org", role: active.role }],
    },
  }),
}));
vi.mock("@/lib/api/runs", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api/runs")>("@/lib/api/runs")),
  listRuns: vi.fn(),
  getRun: vi.fn(),
  updateRun: vi.fn(),
  archiveRun: vi.fn(),
}));

const DETAIL = savedRun(ANALYSIS_REPORTS[0]);
beforeEach(() => {
  active.role = "ORG_ADMIN";
  vi.mocked(listRuns)
    .mockReset()
    .mockResolvedValue({ items: [DETAIL.run], next_cursor: null });
  vi.mocked(getRun).mockReset().mockResolvedValue(DETAIL);
  vi.mocked(updateRun)
    .mockReset()
    .mockResolvedValue({ ...DETAIL.run, version: 2 });
  vi.mocked(archiveRun)
    .mockReset()
    .mockResolvedValue({ ...DETAIL.run, version: 2 });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});

it("shows loading, an authoritative summary, and the detail link", async () => {
  render(<HistoryPage />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading history");
  expect(
    await screen.findByRole("link", { name: "Invoice vs Purchase Order" }),
  ).toHaveAttribute("href", runPath(DETAIL.run.id));
  expect(
    screen.getByText(
      new RegExp(
        `${"invoice_lines_processed" in DETAIL.run.summary ? DETAIL.run.summary.invoice_lines_processed : 0} invoice lines`,
      ),
    ),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
});

it("distinguishes empty active and archived history", async () => {
  vi.mocked(listRuns).mockResolvedValue({ items: [], next_cursor: null });
  const user = userEvent.setup();
  render(<HistoryPage />);
  expect(await screen.findByText(/No saved runs match/)).toBeVisible();
  await user.selectOptions(screen.getByLabelText("History status"), "true");
  expect(await screen.findByText("No archived runs.")).toBeVisible();
  expect(listRuns).toHaveBeenLastCalledWith(
    expect.objectContaining({ archived: true }),
    expect.any(AbortSignal),
  );
});

it("uses server filters and bounded next/previous cursors", async () => {
  vi.mocked(listRuns)
    .mockResolvedValueOnce({ items: [DETAIL.run], next_cursor: "next-page" })
    .mockResolvedValue({ items: [], next_cursor: null });
  const user = userEvent.setup();
  render(<HistoryPage />);
  await screen.findByRole("link");
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() =>
    expect(listRuns).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "next-page" }),
      expect.any(AbortSignal),
    ),
  );
  await user.click(screen.getByRole("button", { name: "Previous page" }));
  await user.selectOptions(
    screen.getByLabelText("Analysis type"),
    "po-receipt",
  );
  await waitFor(() =>
    expect(listRuns).toHaveBeenLastCalledWith(
      expect.objectContaining({ mode: "po-receipt", cursor: undefined }),
      expect.any(AbortSignal),
    ),
  );
});

it("offers retry on a network failure", async () => {
  vi.mocked(listRuns).mockRejectedValueOnce(
    new Error("Connection unavailable"),
  );
  const user = userEvent.setup();
  render(<HistoryPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Connection unavailable",
  );
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("link")).toBeVisible();
});

for (const report of ANALYSIS_REPORTS) {
  it(`renders the stored ${report.mode} report and provenance`, async () => {
    vi.mocked(getRun).mockResolvedValue(savedRun(report));
    render(<RunDetailPage runId={DETAIL.run.id} />);
    expect(
      await screen.findByRole("heading", { name: "Source provenance" }),
    ).toBeVisible();
    expect(screen.getByText(/original saved result/)).toBeVisible();
    expect(screen.getAllByText(/\.csv ·/)).toHaveLength(
      savedRun(report).sources.length,
    );
    expect(screen.getByRole("button", { name: "Edit metadata" })).toBeVisible();
  });
}

it("does not offer metadata or archive controls to a member", async () => {
  active.role = "MEMBER";
  render(<RunDetailPage runId={DETAIL.run.id} />);
  await screen.findByRole("heading", { name: "Source provenance" });
  expect(
    screen.queryByRole("button", { name: "Edit metadata" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Archive run" }),
  ).not.toBeInTheDocument();
});

it("renders stored title, note, and filename payloads as text", async () => {
  const attack = "<script>alert(1)</script>";
  vi.mocked(getRun).mockResolvedValue({
    ...DETAIL,
    run: { ...DETAIL.run, title: attack, note: attack },
    sources: [{ ...DETAIL.sources[0], filename: attack }],
  });
  const { container } = render(<RunDetailPage runId={DETAIL.run.id} />);
  expect(await screen.findByRole("heading", { name: attack })).toBeVisible();
  expect(screen.getAllByText(attack).length).toBeGreaterThanOrEqual(2);
  expect(container.querySelector("script")).toBeNull();
});

for (const [status, message] of [
  [401, "Your session expired. Sign in again."],
  [404, "Run not found or no longer accessible in this organization."],
  [403, "Your access could not be verified."],
] as const) {
  it(`shows a safe ${status} detail error`, async () => {
    vi.mocked(getRun).mockRejectedValue(new RunRequestError(status, message));
    render(<RunDetailPage runId={DETAIL.run.id} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(
      screen.queryByRole("heading", { name: "Source provenance" }),
    ).not.toBeInTheDocument();
  });
}

it("submits only metadata with the displayed version and focuses conflicts", async () => {
  vi.mocked(updateRun).mockRejectedValue(
    new RunRequestError(409, RUN_CONFLICT_MESSAGE),
  );
  const changed = vi.fn();
  const user = userEvent.setup();
  render(<RunActions run={DETAIL.run} onChanged={changed} />);
  await user.click(screen.getByRole("button", { name: "Edit metadata" }));
  expect(screen.getByLabelText("Title")).toHaveFocus();
  await user.type(screen.getByLabelText("Title"), "Quarter review");
  await user.click(screen.getByRole("button", { name: "Save metadata" }));
  expect(updateRun).toHaveBeenCalledWith(DETAIL.run.id, {
    title: "Quarter review",
    note: "",
    expected_version: 1,
  });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    RUN_CONFLICT_MESSAGE,
  );
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(screen.getByRole("button", { name: "Save metadata" })).toBeDisabled();
  expect(changed).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Refresh run" }));
  expect(changed).toHaveBeenCalledOnce();
});

it("confirms soft archive before sending a versioned request", async () => {
  const changed = vi.fn();
  const user = userEvent.setup();
  render(<RunActions run={DETAIL.run} onChanged={changed} />);
  await user.click(screen.getByRole("button", { name: "Archive run" }));
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "does not permanently erase",
  );
  expect(archiveRun).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm archive" }));
  await waitFor(() =>
    expect(archiveRun).toHaveBeenCalledWith(DETAIL.run.id, 1, true),
  );
  expect(changed).toHaveBeenCalledOnce();
});

it("restores an archived run using its current version", async () => {
  const user = userEvent.setup();
  render(
    <RunActions
      run={{ ...DETAIL.run, archived_at: DETAIL.run.created_at, version: 3 }}
      onChanged={vi.fn()}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Restore run" }));
  await waitFor(() =>
    expect(archiveRun).toHaveBeenCalledWith(DETAIL.run.id, 3, false),
  );
});

it("returns focus to the archive button when confirmation is cancelled", async () => {
  const user = userEvent.setup();
  render(<RunActions run={DETAIL.run} onChanged={vi.fn()} />);
  const archive = screen.getByRole("button", { name: "Archive run" });
  await user.click(archive);
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(archive).toHaveFocus();
  expect(archiveRun).not.toHaveBeenCalled();
});
