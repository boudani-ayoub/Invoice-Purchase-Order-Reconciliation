import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  commentFinding,
  getFinding,
  listAssignees,
  listFindingEvents,
  listFindings,
  manageFinding,
  transitionFinding,
  WorkflowRequestError,
} from "@/lib/api/workflow";
import { WORKFLOW_DETAIL, WORKFLOW_EVENT } from "@/test/fixtures/workflow";
import {
  WORKFLOW_CONFLICT,
  findingPath,
  runWorkPath,
} from "@/constants/workflow";
import { FindingDetailPage } from "./finding-detail";
import { WorkflowControls } from "./workflow-controls";
import { WorkQueue } from "./work-queue";
import { FindingTimeline } from "./finding-timeline";

const account = vi.hoisted(() => ({ role: "ORG_ADMIN", refresh: vi.fn() }));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    session: {
      user: { id: "actor" },
      active_organization_id: "org",
      memberships: [{ organization_id: "org", role: account.role }],
    },
    refresh: account.refresh,
  }),
}));
vi.mock("@/lib/api/workflow", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api/workflow")>(
    "@/lib/api/workflow",
  )),
  commentFinding: vi.fn(),
  getFinding: vi.fn(),
  listAssignees: vi.fn(),
  listFindingEvents: vi.fn(),
  listFindings: vi.fn(),
  manageFinding: vi.fn(),
  transitionFinding: vi.fn(),
}));
const FINDING = WORKFLOW_DETAIL.finding;
beforeEach(() => {
  vi.resetAllMocks();
  account.role = "ORG_ADMIN";
  vi.mocked(getFinding).mockResolvedValue(WORKFLOW_DETAIL);
  vi.mocked(listFindings).mockResolvedValue({
    items: [FINDING],
    next_cursor: null,
    server_now: WORKFLOW_DETAIL.server_now,
  });
  vi.mocked(listFindingEvents).mockResolvedValue({
    items: [WORKFLOW_EVENT],
    next_cursor: null,
  });
  vi.mocked(listAssignees).mockResolvedValue({
    items: [
      { user_id: "actor", display_name: "Test member", role: "ORG_ADMIN" },
    ],
    next_cursor: null,
  });
  vi.mocked(manageFinding).mockResolvedValue({ ...FINDING, version: 2 });
  vi.mocked(transitionFinding).mockResolvedValue({ ...FINDING, version: 2 });
  vi.mocked(commentFinding).mockResolvedValue(WORKFLOW_EVENT);
});
it("loads the operational queue without computed financial totals", async () => {
  render(<WorkQueue runId={FINDING.run.id} />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading work queue");
  expect(
    await screen.findByRole("link", { name: "Unknown purchase order" }),
  ).toHaveAttribute("href", findingPath(FINDING.id));
  expect(screen.getByText(/Invoice INV-X/)).toBeVisible();
  expect(listFindings).toHaveBeenCalledWith(
    expect.objectContaining({ run_id: FINDING.run.id }),
    expect.any(AbortSignal),
  );
  expect(screen.queryByText(/savings|KPI/i)).not.toBeInTheDocument();
});
it("sends assignment, status, overdue, and reminder filters to the server", async () => {
  const user = userEvent.setup();
  render(<WorkQueue />);
  await screen.findByRole("link", { name: "Unknown purchase order" });
  await user.selectOptions(screen.getByLabelText("Assignment"), "me");
  await user.selectOptions(
    screen.getByLabelText("Workflow status"),
    "IN_REVIEW",
  );
  await user.click(screen.getByLabelText("Overdue only"));
  await user.click(screen.getByLabelText("Reminder due only"));
  await waitFor(() =>
    expect(listFindings).toHaveBeenLastCalledWith(
      expect.objectContaining({
        assignee: "me",
        status: "IN_REVIEW",
        overdue: true,
        reminder_due: true,
        cursor: undefined,
      }),
      expect.any(AbortSignal),
    ),
  );
});
it("uses keyset next and previous pages and resets cursor after filtering", async () => {
  vi.mocked(listFindings).mockResolvedValue({
    items: [FINDING],
    next_cursor: "cursor",
    server_now: WORKFLOW_DETAIL.server_now,
  });
  const user = userEvent.setup();
  render(<WorkQueue />);
  await screen.findByRole("link", { name: "Unknown purchase order" });
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() =>
    expect(listFindings).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "cursor" }),
      expect.any(AbortSignal),
    ),
  );
  await user.selectOptions(screen.getByLabelText("Assignment"), "unassigned");
  await waitFor(() =>
    expect(listFindings).toHaveBeenLastCalledWith(
      expect.objectContaining({ assignee: "unassigned", cursor: undefined }),
      expect.any(AbortSignal),
    ),
  );
});
it("renders empty queue and request errors with retry", async () => {
  vi.mocked(listFindings)
    .mockRejectedValueOnce(new Error("Connection unavailable"))
    .mockResolvedValue({
      items: [],
      next_cursor: null,
      server_now: WORKFLOW_DETAIL.server_now,
    });
  const user = userEvent.setup();
  render(<WorkQueue />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Connection unavailable",
  );
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("No findings match this view.")).toBeVisible();
});
it("shows server-supplied due states and inactive assignment text", async () => {
  vi.mocked(listFindings).mockResolvedValue({
    items: [
      {
        ...FINDING,
        assignee_user_id: "other",
        assignee: { display_name: "Former member", active: false },
        overdue: true,
        reminder_due: true,
      },
    ],
    next_cursor: null,
    server_now: WORKFLOW_DETAIL.server_now,
  });
  render(<WorkQueue />);
  expect(await screen.findByText("Former member (inactive)")).toBeVisible();
  expect(screen.getByText("Overdue", { exact: true })).toBeVisible();
  expect(screen.getByText("Reminder due", { exact: true })).toBeVisible();
});
it.each(["AP_MANAGER", "ORG_ADMIN"])(
  "allows %s to assign and schedule with expected version",
  async (role) => {
    account.role = role;
    const user = userEvent.setup();
    const changed = vi.fn();
    render(
      <WorkflowControls
        finding={FINDING}
        onChanged={changed}
        onComment={vi.fn()}
      />,
    );
    await screen.findByRole("option", { name: /Test member/ });
    await user.selectOptions(screen.getByLabelText("Assignee"), "actor");
    await user.click(
      screen.getByRole("button", { name: "Save assignment and schedule" }),
    );
    expect(manageFinding).toHaveBeenCalledWith(FINDING.id, {
      expected_version: 1,
      assignee_user_id: "actor",
    });
    expect(changed).toHaveBeenCalledOnce();
  },
);
it("lets a member transition only their own assigned finding", async () => {
  account.role = "MEMBER";
  const user = userEvent.setup();
  const view = render(
    <WorkflowControls
      finding={FINDING}
      onChanged={vi.fn()}
      onComment={vi.fn()}
    />,
  );
  expect(screen.queryByLabelText("Assignee")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Start review" }),
  ).not.toBeInTheDocument();
  view.rerender(
    <WorkflowControls
      finding={{ ...FINDING, assignee_user_id: "actor" }}
      onChanged={vi.fn()}
      onComment={vi.fn()}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Start review" }));
  expect(transitionFinding).toHaveBeenCalledWith(FINDING.id, 1, "IN_REVIEW");
});
it("requires a nonblank resolution note and submits it as plain text", async () => {
  const user = userEvent.setup();
  render(
    <WorkflowControls
      finding={FINDING}
      onChanged={vi.fn()}
      onComment={vi.fn()}
    />,
  );
  expect(
    screen.getByRole("button", { name: "Resolve finding" }),
  ).toBeDisabled();
  await user.type(
    screen.getByLabelText("Resolution note"),
    "Supplier confirmed evidence.",
  );
  await user.click(screen.getByRole("button", { name: "Resolve finding" }));
  expect(transitionFinding).toHaveBeenCalledWith(
    FINDING.id,
    1,
    "RESOLVED",
    "Supplier confirmed evidence.",
  );
});
it("reopens without sending historical resolution text", async () => {
  const user = userEvent.setup();
  render(
    <WorkflowControls
      finding={{ ...FINDING, status: "RESOLVED" }}
      onChanged={vi.fn()}
      onComment={vi.fn()}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Reopen finding" }));
  expect(transitionFinding).toHaveBeenCalledWith(FINDING.id, 1, "OPEN");
});
it("appends a comment without a finding version or automatic resubmission", async () => {
  account.role = "MEMBER";
  const user = userEvent.setup();
  const added = vi.fn();
  render(
    <WorkflowControls
      finding={FINDING}
      onChanged={vi.fn()}
      onComment={added}
    />,
  );
  await user.type(
    screen.getByLabelText("Comment", { exact: true }),
    "Investigating.",
  );
  await user.click(screen.getByRole("button", { name: "Add comment" }));
  expect(commentFinding).toHaveBeenCalledExactlyOnceWith(
    FINDING.id,
    "Investigating.",
  );
  expect(added).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("Comment", { exact: true })).toHaveValue("");
});
it.each([409, 0, 403])(
  "focuses %s errors and requires refresh before another write",
  async (status) => {
    vi.mocked(transitionFinding).mockRejectedValue(
      new WorkflowRequestError(status, WORKFLOW_CONFLICT),
    );
    const user = userEvent.setup();
    const changed = vi.fn();
    render(
      <WorkflowControls
        finding={FINDING}
        onChanged={changed}
        onComment={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Start review" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveFocus());
    expect(screen.getByRole("button", { name: "Start review" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Refresh finding" }));
    expect(changed).toHaveBeenCalledOnce();
    expect(account.refresh).toHaveBeenCalledOnce();
  },
);
it("shows source context, unresolved references, and navigation to run findings", async () => {
  render(<FindingDetailPage findingId={FINDING.id} />);
  await screen.findByRole("heading", { name: "Source context" });
  expect(screen.getByText("Unresolved source reference")).toBeVisible();
  expect(
    screen.getByRole("link", { name: "All findings from this run" }),
  ).toHaveAttribute("href", runWorkPath(FINDING.run.id));
});
it("escapes stored comments, resolution notes, member names, and run titles", async () => {
  const markup = '<img src=x onerror="alert(1)">';
  vi.mocked(getFinding).mockResolvedValue({
    ...WORKFLOW_DETAIL,
    finding: {
      ...FINDING,
      assignee_user_id: "other",
      assignee: { display_name: markup, active: true },
      run: { ...FINDING.run, title: markup },
      status: "RESOLVED",
      resolved_at: WORKFLOW_DETAIL.server_now,
      resolved_by_user_id: "actor",
      resolution_note: markup,
    },
  });
  vi.mocked(listFindingEvents).mockResolvedValue({
    items: [{ ...WORKFLOW_EVENT, message: markup }],
    next_cursor: null,
  });
  const view = render(<FindingDetailPage findingId={FINDING.id} />);
  await screen.findByRole("heading", { name: "Source context" });
  await waitFor(() =>
    expect(screen.getAllByText(markup).length).toBeGreaterThanOrEqual(4),
  );
  expect(view.container.querySelector("img")).toBeNull();
});
it("denies cross-tenant detail without showing workflow controls", async () => {
  vi.mocked(getFinding).mockRejectedValue(
    new WorkflowRequestError(404, "Finding unavailable"),
  );
  render(<FindingDetailPage findingId={FINDING.id} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Finding unavailable",
  );
  expect(screen.queryByLabelText("Workflow controls")).not.toBeInTheDocument();
});
it("paginates append-only events independently of finding state", async () => {
  vi.mocked(listFindingEvents).mockResolvedValue({
    items: [WORKFLOW_EVENT],
    next_cursor: "older",
  });
  const user = userEvent.setup();
  render(<FindingTimeline findingId={FINDING.id} />);
  await screen.findByText(WORKFLOW_EVENT.message!);
  await user.click(screen.getByRole("button", { name: "Older events" }));
  await waitFor(() =>
    expect(listFindingEvents).toHaveBeenLastCalledWith(
      FINDING.id,
      "older",
      expect.any(AbortSignal),
    ),
  );
});
