import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "./transport";
import {
  getInventoryBalances,
  getInventoryOperations,
  postInventoryMovement,
  updateInventoryItem,
} from "./inventory";
import type {
  InventoryBalance,
  InventoryItem,
  InventoryOperation,
} from "@/types/inventory";

vi.mock("./transport", () => ({ apiFetch: vi.fn() }));

const item: InventoryItem = {
  id: "item-a",
  item_code: "SKU-1",
  description: "Part",
  base_uom: "EA",
  status: "ACTIVE",
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
  updated_at: "2026-09-15T00:00:00Z",
};
const location = {
  id: "location-a",
  location_code: "MAIN",
  name: "Main store",
  status: "ACTIVE" as const,
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
  updated_at: "2026-09-15T00:00:00Z",
};
const balance: InventoryBalance = { item, location, quantity: "12.500" };
const operation: InventoryOperation = {
  id: "operation-a",
  type: "STOCK_RECEIPT",
  actor_user_id: "user-a",
  occurred_at: "2026-09-15T00:00:00Z",
  created_at: "2026-09-15T00:00:01Z",
  external_reference: null,
  note: null,
  request_id: "request-a",
  idempotency_key: "key-a",
  reverses_operation_id: null,
  movements: [
    {
      id: "movement-a",
      item: {
        id: item.id,
        item_code: item.item_code,
        description: item.description,
        base_uom: item.base_uom,
      },
      location: {
        id: location.id,
        location_code: location.location_code,
        name: location.name,
      },
      quantity_delta: "12.500",
    },
  ],
};

beforeEach(() => vi.mocked(apiFetch).mockReset());

it("uses bounded ledger reads and preserves exact decimal strings", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: [balance], next_cursor: null }),
  );
  expect(await getInventoryBalances()).toEqual({ items: [balance], next_cursor: null });
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/inventory/balances?limit=25",
    {},
  );
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: [operation], next_cursor: null }),
  );
  expect((await getInventoryOperations()).items[0].movements[0].quantity_delta).toBe(
    "12.500",
  );
});

it("sends the caller-owned idempotency key without rewriting quantity", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(Response.json(operation, { status: 201 }));
  await postInventoryMovement({
    idempotency_key: "stable-key",
    type: "STOCK_RECEIPT",
    item_id: item.id,
    location_id: location.id,
    quantity: "12.500",
  });
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/inventory/movements",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        idempotency_key: "stable-key",
        type: "STOCK_RECEIPT",
        item_id: item.id,
        location_id: location.id,
        quantity: "12.500",
      }),
    }),
  );
});

it("uses optimistic versions for item changes", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ ...item, description: "Updated", version: 2 }),
  );
  await updateInventoryItem(item, { description: "Updated" });
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/inventory/items/item-a",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ expected_version: 1, description: "Updated" }),
    }),
  );
});

it("rejects malformed and oversized inventory responses", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: [{ ...balance, quantity: 12.5 }], next_cursor: null }),
  );
  await expect(getInventoryBalances()).rejects.toMatchObject({ status: 0 });
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: [{ ...balance, quantity: "not-decimal" }], next_cursor: null }),
  );
  await expect(getInventoryBalances()).rejects.toMatchObject({ status: 0 });
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: Array(26).fill(operation), next_cursor: null }),
  );
  await expect(getInventoryOperations()).rejects.toMatchObject({ status: 0 });
});

for (const status of [401, 403, 404, 409, 422, 500]) {
  it(`surfaces a safe inventory ${status} response once`, async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      Response.json({ message: "Safe inventory message" }, { status }),
    );
    await expect(getInventoryBalances()).rejects.toMatchObject({ status });
    expect(apiFetch).toHaveBeenCalledOnce();
  });
}
