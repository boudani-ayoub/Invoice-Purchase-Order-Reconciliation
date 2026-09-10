import { beforeEach, expect, it, vi } from "vitest";
import {
  archiveRun,
  createRun,
  getRun,
  listRuns,
  RunRequestError,
  updateRun,
} from "./runs";
import { apiFetch } from "./transport";
import { ANALYSIS_REPORTS } from "@/test/fixtures/analyses";
import { savedRun } from "@/test/fixtures/runs";
import { RUNS_API_PATH, runApiPath } from "@/constants/runs";
import { EMPTY_UPLOADS } from "@/constants/uploads";

vi.mock("./transport", () => ({ apiFetch: vi.fn() }));
const detail = savedRun(ANALYSIS_REPORTS[0]);
beforeEach(() => vi.mocked(apiFetch).mockReset());

it("sends bounded server-side filters without exposing snapshots in list requests", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    Response.json({ items: [detail.run], next_cursor: null }),
  );
  expect(
    (await listRuns({ archived: true, mode: "invoice-po", cursor: "opaque" }))
      .items,
  ).toHaveLength(1);
  expect(apiFetch).toHaveBeenCalledWith(
    `${RUNS_API_PATH}?archived=true&limit=25&mode=invoice-po&cursor=opaque`,
    expect.any(Object),
  );
});
it("reads the historical envelope", async () => {
  vi.mocked(apiFetch).mockResolvedValue(Response.json(detail));
  expect(await getRun(detail.run.id)).toEqual(detail);
});
it("sends PATCH and archive/restore through the credentialed transport", async () => {
  vi.mocked(apiFetch).mockImplementation(async () => Response.json(detail.run));
  await updateRun(detail.run.id, { title: "Review", expected_version: 1 });
  expect(apiFetch).toHaveBeenLastCalledWith(
    runApiPath(detail.run.id),
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ title: "Review", expected_version: 1 }),
    }),
  );
  await archiveRun(detail.run.id, 1, true);
  expect(apiFetch).toHaveBeenLastCalledWith(
    `${runApiPath(detail.run.id)}/archive`,
    expect.objectContaining({ method: "POST" }),
  );
  await archiveRun(detail.run.id, 2, false);
  expect(apiFetch).toHaveBeenLastCalledWith(
    `${runApiPath(detail.run.id)}/restore`,
    expect.objectContaining({ body: JSON.stringify({ expected_version: 2 }) }),
  );
});
for (const status of [401, 403, 404, 409, 422, 500]) {
  it(`does not retry or hide a ${status} response`, async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      Response.json({ private: "never display" }, { status }),
    );
    await expect(getRun(detail.run.id)).rejects.toMatchObject({ status });
    expect(apiFetch).toHaveBeenCalledOnce();
  });
}
it("rejects malformed saved reports", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    Response.json({ ...detail, report: {} }),
  );
  await expect(getRun(detail.run.id)).rejects.toBeInstanceOf(RunRequestError);
});
it("creates an exact mode-specific persistent request without stateless fallback", async () => {
  vi.mocked(apiFetch).mockResolvedValue(Response.json(detail, { status: 201 }));
  const files = {
    ...EMPTY_UPLOADS,
    purchase_orders: new File(["po"], "po.csv"),
    invoices: new File(["invoice"], "invoice.csv"),
  };
  expect((await createRun("invoice-po", files)).run.id).toBe(detail.run.id);
  expect(apiFetch).toHaveBeenCalledWith(
    `${RUNS_API_PATH}/invoice-po`,
    expect.objectContaining({ method: "POST" }),
  );
  const body = vi.mocked(apiFetch).mock.calls[0][1]?.body as FormData;
  expect([...body.keys()]).toEqual(["purchase_orders", "invoices"]);
});

it("reports lossless storage limits without retrying the create", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    Response.json({ error: "storage_capacity" }, { status: 422 }),
  );
  await expect(
    createRun("invoice-po", {
      ...EMPTY_UPLOADS,
      purchase_orders: new File(["po"], "po.csv"),
      invoices: new File(["invoice"], "invoice.csv"),
    }),
  ).rejects.toMatchObject({ detail: { kind: "storage_capacity" } });
  expect(apiFetch).toHaveBeenCalledOnce();
});
