import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "./transport";
import {
  commentFinding,
  getFinding,
  listAssignees,
  listFindingEvents,
  listFindings,
  manageFinding,
  transitionFinding,
} from "./workflow";
import { WORKFLOW_DETAIL, WORKFLOW_EVENT } from "@/test/fixtures/workflow";
import { WORKFLOW_PAGE_SIZE, findingApiPath } from "@/constants/workflow";

vi.mock("./transport", () => ({ apiFetch: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
function respond(body: unknown, status = 200) {
  vi.mocked(apiFetch).mockResolvedValue(
    new Response(JSON.stringify(body), { status }),
  );
}
it("uses a bounded encoded server queue query", async () => {
  respond({
    items: [WORKFLOW_DETAIL.finding],
    next_cursor: null,
    server_now: WORKFLOW_DETAIL.server_now,
  });
  await listFindings({
    run_id: "id&status=RESOLVED",
    status: "OPEN",
    assignee: "me",
    overdue: true,
    reminder_due: true,
  });
  const url = new URL(
    vi.mocked(apiFetch).mock.calls[0][0],
    "http://example.test",
  );
  expect(url.searchParams.get("run_id")).toBe("id&status=RESOLVED");
  expect(url.searchParams.get("status")).toBe("OPEN");
  expect(url.searchParams.get("limit")).toBe(String(WORKFLOW_PAGE_SIZE));
});
it("validates detail and independent event pages", async () => {
  respond(WORKFLOW_DETAIL);
  expect(await getFinding(WORKFLOW_DETAIL.finding.id)).toEqual(WORKFLOW_DETAIL);
  respond({ items: [WORKFLOW_EVENT], next_cursor: null });
  expect((await listFindingEvents("id")).items).toEqual([WORKFLOW_EVENT]);
});
it("validates narrow assignee pages", async () => {
  respond({
    items: [{ user_id: "user", display_name: "Name", role: "MEMBER" }],
    next_cursor: "next",
  });
  expect((await listAssignees()).next_cursor).toBe("next");
});
it("sends only explicit mutation fields including null unassignment", async () => {
  respond(WORKFLOW_DETAIL.finding);
  await manageFinding("id", { expected_version: 2, assignee_user_id: null });
  expect(apiFetch).toHaveBeenCalledWith(
    findingApiPath("id"),
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ expected_version: 2, assignee_user_id: null }),
    }),
  );
});
it("sends resolution text only with the transition request", async () => {
  respond(WORKFLOW_DETAIL.finding);
  await transitionFinding("id", 2, "RESOLVED", "Evidence reviewed");
  expect(
    JSON.parse(vi.mocked(apiFetch).mock.calls[0][1]!.body as string),
  ).toEqual({
    expected_version: 2,
    target_status: "RESOLVED",
    resolution_note: "Evidence reviewed",
  });
});
it("comments carry no actor, tenant, request ID, or finding version", async () => {
  respond(WORKFLOW_EVENT);
  await commentFinding("id", "Comment");
  expect(
    JSON.parse(vi.mocked(apiFetch).mock.calls[0][1]!.body as string),
  ).toEqual({ text: "Comment" });
});
it.each([401, 403, 404, 409, 413, 422, 500])(
  "handles %s without retry or raw server disclosure",
  async (status) => {
    respond({ message: "private content echoed by server" }, status);
    const error = await getFinding("id").catch((error) => error);
    expect(error.status).toBe(status);
    expect(error.message).not.toContain("private content");
    expect(apiFetch).toHaveBeenCalledOnce();
  },
);
it.each([
  {},
  { ...WORKFLOW_DETAIL, finding: { ...WORKFLOW_DETAIL.finding, version: "1" } },
  { ...WORKFLOW_DETAIL, server_now: "invalid" },
])("rejects malformed detail envelopes", async (payload) => {
  respond(payload);
  await expect(getFinding("id")).rejects.toThrow(/could not be read/);
});
it("warns about ambiguous network outcome without resubmitting comments", async () => {
  vi.mocked(apiFetch).mockRejectedValue(new TypeError("Network error"));
  await expect(commentFinding("id", "Comment")).rejects.toThrow(
    /refresh the finding and timeline before retrying/,
  );
  expect(apiFetch).toHaveBeenCalledOnce();
});
