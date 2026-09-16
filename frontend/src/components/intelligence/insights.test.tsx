import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ANALYSIS_REPORTS } from "@/test/fixtures/analyses";
import {
  inventory,
  procurement,
  suppliers,
} from "@/test/fixtures/intelligence";
import { savedRun } from "@/test/fixtures/runs";
import {
  getInventoryIntelligence,
  getProcurementIntelligence,
  getSupplierIntelligence,
} from "@/lib/api/intelligence";
import { listRuns } from "@/lib/api/runs";
import { InsightsPage } from "./insights-page";

const auth = vi.hoisted(() => ({ role: "ORG_ADMIN" }));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    session: {
      active_organization_id: "org",
      memberships: [{ organization_id: "org", role: auth.role }],
    },
  }),
}));
vi.mock("@/lib/api/runs", () => ({ listRuns: vi.fn() }));
vi.mock("@/lib/api/intelligence", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/intelligence")>()),
  getProcurementIntelligence: vi.fn(),
  getSupplierIntelligence: vi.fn(),
  getInventoryIntelligence: vi.fn(),
}));

const run = savedRun(
  ANALYSIS_REPORTS.find((report) => report.mode === "three-way")!,
).run;
const archived = { ...run, id: "archived-run", title: "Archived evidence", archived_at: run.updated_at };

beforeEach(() => {
  auth.role = "ORG_ADMIN";
  vi.mocked(listRuns)
    .mockReset()
    .mockImplementation(async ({ archived: archivedQuery }) => ({
      items: archivedQuery ? [archived] : [run],
      next_cursor: null,
    }));
  vi.mocked(getProcurementIntelligence).mockReset().mockResolvedValue(procurement);
  vi.mocked(getSupplierIntelligence).mockReset().mockResolvedValue(suppliers);
  vi.mocked(getInventoryIntelligence).mockReset().mockResolvedValue(inventory);
});

it("does not request intelligence for members", () => {
  auth.role = "MEMBER";
  render(<InsightsPage />);
  expect(screen.getByRole("heading", { name: "Insights access required" })).toBeVisible();
  expect(listRuns).not.toHaveBeenCalled();
  expect(getProcurementIntelligence).not.toHaveBeenCalled();
});

for (const role of ["AP_MANAGER", "ORG_ADMIN"]) {
  it(`shows selected-run money and archived choices for ${role}`, async () => {
    auth.role = role;
    render(<InsightsPage />);
    expect(await screen.findByRole("heading", { name: "Selected-run summary" })).toBeVisible();
    expect(screen.getByRole("option", { name: /Archived evidence.*archived/ })).toBeVisible();
    expect(screen.getByText("1,250.00")).toBeVisible();
    expect(screen.getByText("1,300.00")).toBeVisible();
    expect(screen.queryByText("2,550.00")).not.toBeInTheDocument();
    expect(getProcurementIntelligence).toHaveBeenCalledWith(run.id, expect.any(AbortSignal));
  });
}

it("switches run-scoped suppliers and renders stored labels as text", async () => {
  const user = userEvent.setup();
  render(<InsightsPage />);
  await screen.findByRole("heading", { name: "Selected-run summary" });
  await user.click(screen.getByRole("tab", { name: "Suppliers" }));
  expect(
    await screen.findByText('Unresolved supplier: <script>alert("x")</script>'),
  ).toBeVisible();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByText(/First: 3.5 across 2; full: 5 across 1/)).toBeVisible();
  await user.selectOptions(screen.getByLabelText("Saved analysis"), archived.id);
  await waitFor(() =>
    expect(getSupplierIntelligence).toHaveBeenLastCalledWith(
      archived.id,
      expect.any(AbortSignal),
    ),
  );
});

it("switches bounded inventory windows without combining item quantities", async () => {
  const user = userEvent.setup();
  render(<InsightsPage />);
  await user.click(screen.getByRole("tab", { name: "Inventory" }));
  expect(await screen.findByText("12.500 EA")).toBeVisible();
  expect(screen.getByText("Imported goods receipts do not post inventory.")).toBeVisible();
  await user.selectOptions(screen.getByLabelText("Activity window"), "7d");
  await waitFor(() =>
    expect(getInventoryIntelligence).toHaveBeenLastCalledWith(
      "7d",
      expect.any(AbortSignal),
    ),
  );
  expect(screen.queryByText("Total inventory quantity")).not.toBeInTheDocument();
});
