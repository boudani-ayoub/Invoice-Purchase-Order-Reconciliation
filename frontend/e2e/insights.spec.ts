import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import type { APIRequestContext, Page } from "@playwright/test";
import { authPost, expect, test } from "./auth-fixture";
import { E2E_API_ORIGIN, E2E_WEB_ORIGIN } from "./environment";
import { SAMPLE_FILES } from "./helpers";
import { AUTH_API_PATH, CSRF_HEADER } from "../src/constants/auth";
import { INTELLIGENCE_API_PATH } from "../src/constants/intelligence";
import { runApiPath } from "../src/constants/runs";

interface Seed {
  password: string;
  manager_email: string;
  member_email: string;
  organization_name: string;
}

const seed = JSON.parse(process.env.E2E_WORKFLOW_SEED!) as Seed;

async function login(request: APIRequestContext, email: string) {
  await authPost(request, "logout");
  expect(
    (await authPost(request, "login", { email, password: seed.password })).status(),
  ).toBe(200);
}

async function csrf(request: APIRequestContext) {
  return (
    await (
      await request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`, {
        headers: { Origin: E2E_WEB_ORIGIN },
      })
    ).json()
  ).csrf_token as string;
}

async function createRun(request: APIRequestContext) {
  const [purchaseOrders, receipts, invoices] = await Promise.all([
    readFile(SAMPLE_FILES.purchase_orders),
    readFile(SAMPLE_FILES.receipts),
    readFile(SAMPLE_FILES.invoices),
  ]);
  const response = await request.post(`${E2E_API_ORIGIN}/api/v1/runs/three-way`, {
    headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: await csrf(request) },
    multipart: {
      purchase_orders: {
        name: "purchase_orders.csv",
        mimeType: "text/csv",
        buffer: purchaseOrders,
      },
      receipts: {
        name: "goods_receipts.csv",
        mimeType: "text/csv",
        buffer: receipts,
      },
      invoices: {
        name: "invoices.csv",
        mimeType: "text/csv",
        buffer: invoices,
      },
    },
  });
  expect(response.status()).toBe(201);
  return response.json();
}

async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
}

test("selected and archived runs stay separate from current ledger intelligence", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const first = await createRun(page.request);
  await createRun(page.request);
  const archived = await page.request.post(
    `${E2E_API_ORIGIN}${runApiPath(first.run.id)}/archive`,
    {
      data: { expected_version: first.run.version },
      headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: await csrf(page.request) },
    },
  );
  expect(archived.status()).toBe(200);

  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Selected-run summary" })).toBeVisible();
  await expect(page.getByLabel("Saved analysis").getByRole("option")).toHaveCount(2);
  await expect(page.getByRole("option", { name: /archived/ })).toHaveCount(1);
  const money = page.getByRole("table", {
    name: "Selected run values separated by currency",
  });
  await expect(money.getByText("2,450.00", { exact: true })).toBeVisible();
  await expect(money.getByText("10,199.00", { exact: true })).toBeVisible();
  await expect(money.getByText("4,900.00", { exact: true })).toHaveCount(0);

  await page.getByRole("tab", { name: "Suppliers" }).click();
  const supplierTable = page.getByRole("table", {
    name: "Selected run supplier evidence",
  });
  await expect(supplierTable.getByText(/Unresolved supplier: SUP-ALPHA/)).toBeVisible();
  await expect(supplierTable.getByText(/First: .* across /).first()).toBeVisible();

  await page.getByRole("tab", { name: "Inventory" }).click();
  await expect(page.getByText("Imported goods receipts do not post inventory.")).toBeVisible();
  await expect(page.getByText("No stock-ledger positions have been recorded.")).toBeVisible();
  for (const window of ["7d", "90d", "30d"]) {
    await page.getByLabel("Activity window").selectOption(window);
    const response = await page.request.get(
      `${E2E_API_ORIGIN}${INTELLIGENCE_API_PATH}/inventory?window=${window}`,
    );
    expect(response.status()).toBe(200);
    expect((await response.json()).period.window).toBe(window);
  }
  await accessible(page);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
    true,
  );
  await accessible(page);
});

test("manager access and member denial agree in the UI and API", async ({ page }) => {
  await login(page.request, seed.manager_email);
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Insights" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Insights", exact: true })).toBeVisible();
  expect(
    (await page.request.get(`${E2E_API_ORIGIN}${INTELLIGENCE_API_PATH}/inventory`)).status(),
  ).toBe(200);

  await login(page.request, seed.member_email);
  const identity = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
  ).json();
  const membership = identity.memberships.find(
    (candidate: { organization_name: string; role: string }) =>
      candidate.organization_name === seed.organization_name && candidate.role === "MEMBER",
  );
  await authPost(page.request, "select-organization", {
    organization_id: membership.organization_id,
  });
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Insights access required" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Insights", exact: true })).toHaveCount(0);
  expect(
    (await page.request.get(`${E2E_API_ORIGIN}${INTELLIGENCE_API_PATH}/inventory`)).status(),
  ).toBe(403);
  await accessible(page);
});
