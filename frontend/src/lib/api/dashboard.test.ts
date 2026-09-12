import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "./transport";
import { getOverview, getTrends, getIssues, getWorkload } from "./dashboard";
import { overview, trends, workload } from "@/test/fixtures/dashboard";

vi.mock("./transport", () => ({ apiFetch: vi.fn() }));
beforeEach(() => vi.mocked(apiFetch).mockReset());
it("uses narrow credentialed read requests and preserves server metrics", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(Response.json(overview));
  expect(await getOverview("30d")).toEqual(overview);
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/dashboard/overview?window=30d",
    expect.any(Object),
  );
  vi.mocked(apiFetch).mockResolvedValueOnce(Response.json(trends));
  expect(await getTrends("30d")).toEqual(trends);
  vi.mocked(apiFetch).mockResolvedValueOnce(Response.json(workload));
  expect(await getWorkload("next")).toEqual(workload);
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/dashboard/workload?limit=25&cursor=next",
    expect.any(Object),
  );
});
for (const status of [401, 403, 422, 500]) {
  it(`surfaces a safe ${status} error without retries`, async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      Response.json({ message: "Private DB detail" }, { status }),
    );
    await expect(getOverview("30d")).rejects.toMatchObject({ status });
    expect(apiFetch).toHaveBeenCalledOnce();
    await expect(getOverview("30d")).rejects.not.toThrow("Private");
  });
}
it("rejects unbounded trends and invalid count payloads", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ ...trends, items: [...trends.items, trends.items[0]] }),
  );
  await expect(getTrends("30d")).rejects.toMatchObject({ status: 0 });
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({
      ...overview,
      backlog: { ...overview.backlog, overdue: -1 },
    }),
  );
  await expect(getOverview("30d")).rejects.toMatchObject({ status: 0 });
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({
      server_now: overview.server_now,
      items: [{ code: "X", category: "Y", count: 0.5 }],
    }),
  );
  await expect(getIssues()).rejects.toMatchObject({ status: 0 });
});
it("accepts null ages, zero counts, and signed clock skew without inventing a duration", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({
      ...overview,
      age: {
        median_unresolved_age_seconds: null,
        oldest_unresolved_age_seconds: -1,
      },
    }),
  );
  expect(
    (await getOverview("30d")).age.median_unresolved_age_seconds,
  ).toBeNull();
});
it("handles malformed JSON and transport failures safely", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response("not json"));
  await expect(getIssues()).rejects.toMatchObject({ status: 0 });
  vi.mocked(apiFetch).mockRejectedValueOnce(
    new Error("private network address"),
  );
  await expect(getIssues()).rejects.not.toThrow("private");
});
