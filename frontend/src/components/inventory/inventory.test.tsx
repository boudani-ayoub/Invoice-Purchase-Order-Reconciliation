import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthProvider } from "@/components/auth/auth-provider";
import { InventoryPage } from "@/components/inventory/inventory-page";
import {
  createInventoryItem,
  createInventoryLocation,
  getInventoryBalances,
  getInventoryItems,
  getInventoryLocations,
  getInventoryOperations,
  InventoryRequestError,
  postInventoryMovement,
  postInventoryTransfer,
  reverseInventoryOperation,
  setInventoryItemArchived,
  setInventoryLocationArchived,
  updateInventoryItem,
  updateInventoryLocation,
} from "@/lib/api/inventory";
import { authAction, getSession } from "@/lib/api/auth";
import type { AuthSession } from "@/types/auth";
import type {
  InventoryBalance,
  InventoryItem,
  InventoryLocation,
  InventoryOperation,
} from "@/types/inventory";

vi.mock("@/lib/api/auth", () => ({ authAction: vi.fn(), getSession: vi.fn() }));
vi.mock("@/lib/api/inventory", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/inventory")>();
  return {
    ...actual,
    createInventoryItem: vi.fn(),
    createInventoryLocation: vi.fn(),
    getInventoryBalances: vi.fn(),
    getInventoryItems: vi.fn(),
    getInventoryLocations: vi.fn(),
    getInventoryOperations: vi.fn(),
    postInventoryMovement: vi.fn(),
    postInventoryTransfer: vi.fn(),
    reverseInventoryOperation: vi.fn(),
    setInventoryItemArchived: vi.fn(),
    setInventoryLocationArchived: vi.fn(),
    updateInventoryItem: vi.fn(),
    updateInventoryLocation: vi.fn(),
  };
});

const item: InventoryItem = {
  id: "item-a",
  item_code: "SKU-1",
  description: '<img src=x onerror="window.inventoryXss=true">',
  base_uom: "EA",
  status: "ACTIVE",
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
  updated_at: "2026-09-15T00:00:00Z",
};
const location: InventoryLocation = {
  id: "location-a",
  location_code: "MAIN",
  name: "Main store",
  status: "ACTIVE",
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
  external_reference: "Dock <b>7</b>",
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
const session = (role: "MEMBER" | "AP_MANAGER" | "ORG_ADMIN"): AuthSession => ({
  user: { id: "user-a", email: "person@example.com", display_name: "Person" },
  memberships: [{ organization_id: "org", organization_name: "Company", role }],
  active_organization_id: "org",
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(authAction).mockResolvedValue(null);
  vi.mocked(getInventoryItems).mockResolvedValue({ items: [item], next_cursor: null });
  vi.mocked(getInventoryLocations).mockResolvedValue({ items: [location], next_cursor: null });
  vi.mocked(getInventoryBalances).mockResolvedValue({ items: [balance], next_cursor: null });
  vi.mocked(getInventoryOperations).mockResolvedValue({
    items: [operation],
    next_cursor: null,
  });
  vi.mocked(createInventoryItem).mockResolvedValue(item);
  vi.mocked(createInventoryLocation).mockResolvedValue(location);
  vi.mocked(postInventoryMovement).mockResolvedValue(operation);
  vi.mocked(postInventoryTransfer).mockResolvedValue({ ...operation, type: "TRANSFER" });
  vi.mocked(reverseInventoryOperation).mockResolvedValue({
    ...operation,
    id: "reversal-a",
    type: "REVERSAL",
  });
  vi.mocked(updateInventoryItem).mockResolvedValue({ ...item, version: 2 });
  vi.mocked(updateInventoryLocation).mockResolvedValue({ ...location, version: 2 });
  vi.mocked(setInventoryItemArchived).mockResolvedValue({
    ...item,
    status: "ARCHIVED",
    version: 2,
  });
  vi.mocked(setInventoryLocationArchived).mockResolvedValue({
    ...location,
    status: "ARCHIVED",
    version: 2,
  });
});

function renderPage(role: "MEMBER" | "AP_MANAGER" | "ORG_ADMIN") {
  vi.mocked(getSession).mockResolvedValue(session(role));
  return render(
    <AuthProvider>
      <InventoryPage />
    </AuthProvider>,
  );
}

it("denies members and gives AP managers a read-only exact balance", async () => {
  renderPage("MEMBER");
  expect(
    await screen.findByRole("heading", { name: "Inventory access required" }),
  ).toBeVisible();
  expect(getInventoryBalances).not.toHaveBeenCalled();

  renderPage("AP_MANAGER");
  expect(await screen.findByText("12.500")).toBeVisible();
  expect(screen.getByText(item.description)).toBeVisible();
  expect(document.querySelector("img")).toBeNull();
  expect(screen.queryByRole("heading", { name: "Post inventory" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Reverse" })).not.toBeInTheDocument();
});

it("creates master data and posts an explicit stock receipt", async () => {
  const user = userEvent.setup();
  renderPage("ORG_ADMIN");
  await screen.findByRole("region", { name: "Current on-hand inventory" });
  const itemCode = screen.getByLabelText("Item code");
  await user.type(itemCode, "NEW-ITEM");
  await user.type(screen.getAllByLabelText("Description")[0], "New part");
  await user.type(screen.getAllByLabelText("Base unit")[0], "BOX");
  await user.click(screen.getByRole("button", { name: "Create item" }));
  expect(createInventoryItem).toHaveBeenCalledWith("NEW-ITEM", "New part", "BOX");

  await user.selectOptions(screen.getByLabelText("Item"), item.id);
  await user.selectOptions(screen.getByLabelText("Location"), location.id);
  await user.type(screen.getByLabelText("Quantity"), "2.500");
  await user.click(screen.getByRole("button", { name: "Post operation" }));
  expect(postInventoryMovement).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "STOCK_RECEIPT",
      item_id: item.id,
      location_id: location.id,
      quantity: "2.500",
      idempotency_key: expect.any(String),
    }),
  );
});

it("focuses insufficient-stock conflicts and offers an explicit refresh", async () => {
  vi.mocked(postInventoryMovement).mockRejectedValue(
    new InventoryRequestError(
      409,
      "Insufficient on-hand quantity at this location. Refresh inventory before trying again.",
    ),
  );
  const user = userEvent.setup();
  renderPage("ORG_ADMIN");
  await user.selectOptions(await screen.findByLabelText("Operation"), "STOCK_ISSUE");
  await user.selectOptions(screen.getByLabelText("Item"), item.id);
  await user.selectOptions(screen.getByLabelText("Location"), location.id);
  await user.type(screen.getByLabelText("Quantity"), "99");
  await user.click(screen.getByRole("button", { name: "Post operation" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveFocus();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeVisible();
});

it("retries an ambiguous posting with the same idempotency key", async () => {
  vi.mocked(postInventoryMovement)
    .mockRejectedValueOnce(new InventoryRequestError(0, "Connection lost."))
    .mockResolvedValueOnce(operation);
  const user = userEvent.setup();
  renderPage("ORG_ADMIN");
  await screen.findByRole("option", { name: "SKU-1 · EA" });
  await user.selectOptions(await screen.findByLabelText("Item"), item.id);
  await user.selectOptions(screen.getByLabelText("Location"), location.id);
  await user.type(screen.getByLabelText("Quantity"), "1");
  await user.click(screen.getByRole("button", { name: "Post operation" }));
  await user.click(await screen.findByRole("button", { name: "Retry same posting" }));
  await waitFor(() => expect(postInventoryMovement).toHaveBeenCalledTimes(2));
  expect(vi.mocked(postInventoryMovement).mock.calls[0][0].idempotency_key).toBe(
    vi.mocked(postInventoryMovement).mock.calls[1][0].idempotency_key,
  );
});

it("focuses a stale master-data conflict and preserves the submitted form", async () => {
  vi.mocked(updateInventoryItem).mockRejectedValue(
    new InventoryRequestError(409, "This record changed. Refresh and try again."),
  );
  const user = userEvent.setup();
  renderPage("ORG_ADMIN");
  const form = await screen.findByRole("form", { name: "Edit item SKU-1" });
  const description = within(form).getByLabelText("Description");
  await user.clear(description);
  await user.type(description, "Locally edited description");
  await user.click(within(form).getByRole("button", { name: "Save item" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveFocus();
  expect(description).toHaveValue("Locally edited description");
  expect(screen.getByRole("button", { name: "Refresh" })).toBeVisible();
});
