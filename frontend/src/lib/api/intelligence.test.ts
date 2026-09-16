import { beforeEach, expect, it, vi } from "vitest";
import { INTELLIGENCE_API_PATH } from "@/constants/intelligence";
import {
  inventory,
  procurement,
  suppliers,
} from "@/test/fixtures/intelligence";
import {
  getInventoryIntelligence,
  getProcurementIntelligence,
  getSupplierIntelligence,
  IntelligenceRequestError,
} from "./intelligence";
import { apiFetch } from "./transport";

vi.mock("./transport", () => ({ apiFetch: vi.fn() }));

beforeEach(() => vi.mocked(apiFetch).mockReset());

it("reads the selected-run procurement contract without number conversion", async () => {
  vi.mocked(apiFetch).mockResolvedValue(Response.json(procurement));
  expect((await getProcurementIntelligence("run/a")).money).toEqual(
    procurement.money,
  );
  expect(apiFetch).toHaveBeenCalledWith(
    `${INTELLIGENCE_API_PATH}/runs/run%2Fa/procurement`,
    expect.objectContaining({ signal: undefined }),
  );
});

it("accepts supplier and inventory pages with exact decimal strings", async () => {
  vi.mocked(apiFetch)
    .mockResolvedValueOnce(Response.json(suppliers))
    .mockResolvedValueOnce(Response.json(inventory));
  expect((await getSupplierIntelligence("run-a")).items[0].identity.resolved).toBe(
    false,
  );
  expect((await getInventoryIntelligence("30d")).items[0].current_on_hand).toBe(
    "12.500",
  );
});

it("rejects currency mixing, numeric money, and oversized pages", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({
      ...procurement,
      money: { ...procurement.money, ordered_value_by_currency: { MIXED: 1290 } },
    }),
  );
  await expect(getProcurementIntelligence("run-a")).rejects.toBeInstanceOf(
    IntelligenceRequestError,
  );
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ ...suppliers, items: Array(26).fill(suppliers.items[0]) }),
  );
  await expect(getSupplierIntelligence("run-a")).rejects.toBeInstanceOf(
    IntelligenceRequestError,
  );
});

it("uses safe status-specific errors without exposing response fields", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    Response.json({ secret: "do not show" }, { status: 403 }),
  );
  await expect(getInventoryIntelligence("7d")).rejects.toMatchObject({
    status: 403,
    message: expect.not.stringContaining("secret"),
  });
});
