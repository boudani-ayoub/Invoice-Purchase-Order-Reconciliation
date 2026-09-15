import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { authPost } from "./auth-fixture";
import { E2E_API_ORIGIN, E2E_WEB_ORIGIN } from "./environment";
import { SAMPLE_FILES } from "./helpers";
import { AUTH_API_PATH, CSRF_HEADER } from "../src/constants/auth";
import { INVENTORY_API_PATH } from "../src/constants/inventory";

interface Seed {
  password: string;
  manager_email: string;
  member_email: string;
  organization_name: string;
  governance_admin_email: string;
}

const seed = JSON.parse(process.env.E2E_WORKFLOW_SEED!) as Seed;

async function login(request: APIRequestContext, email: string) {
  await authPost(request, "logout");
  expect(
    (await authPost(request, "login", { email, password: seed.password })).status(),
  ).toBe(200);
}

async function inventoryWrite(
  request: APIRequestContext,
  path: string,
  data: Record<string, unknown>,
  method: "POST" | "PATCH" = "POST",
) {
  const bootstrap = await request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`, {
    headers: { Origin: E2E_WEB_ORIGIN },
  });
  const { csrf_token } = await bootstrap.json();
  return request.fetch(`${E2E_API_ORIGIN}${INVENTORY_API_PATH}${path}`, {
    method,
    data,
    headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: csrf_token },
  });
}

async function expectAccessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
}

async function expectStatus(page: Page, message: string) {
  await expect(page.getByRole("status").filter({ hasText: message })).toBeVisible();
}

function onHandTable(page: Page) {
  return page.getByRole("table").filter({
    has: page.getByRole("columnheader", { name: "On-hand" }),
  });
}

async function choosePosting(
  page: Page,
  type: string,
  itemCode: string,
  locationCode: string,
  quantity: string,
) {
  const posting = page.getByRole("form", { name: "Post inventory operation" });
  await posting.getByLabel("Operation", { exact: true }).selectOption(type);
  await posting.getByLabel("Item", { exact: true }).selectOption({
    label: `${itemCode} · EA`,
  });
  await posting
    .getByLabel(type === "TRANSFER" ? "Source location" : "Location", { exact: true })
    .selectOption({ label: locationCode });
  await posting.getByLabel("Quantity", { exact: true }).fill(quantity);
}

test("explicit inventory operations drive on-hand without procurement inference", async ({
  page,
}) => {
  test.setTimeout(150_000);
  await login(page.request, seed.governance_admin_email);
  await page.goto("/inventory");
  await expect(page.getByRole("heading", { name: "Current on-hand inventory" })).toBeVisible();

  const suffix = randomUUID().slice(0, 8).toUpperCase();
  const itemCode = `E2E-${suffix}`;
  const mainCode = `MAIN-${suffix}`;
  const storeCode = `STORE-${suffix}`;
  await page.getByLabel("Item code").fill(itemCode);
  await page.getByLabel("Description").first().fill('<img src=x onerror="inventoryXss=true">');
  await page.getByLabel("Base unit").first().fill("EA");
  await page.getByRole("button", { name: "Create item" }).click();
  await expectStatus(page, "Item created");
  expect(await page.evaluate(() => Boolean(window.inventoryXss))).toBe(false);

  await page.getByLabel("Location code").fill(mainCode);
  await page.getByLabel("Location name").fill("Main warehouse");
  await page.getByRole("button", { name: "Create location" }).click();
  await expectStatus(page, "Location created");
  await page.getByLabel("Location code").fill(storeCode);
  await page.getByLabel("Location name").fill("Store room");
  await page.getByRole("button", { name: "Create location" }).click();

  await choosePosting(page, "OPENING_BALANCE", itemCode, mainCode, "10.500");
  await page.getByRole("button", { name: "Post operation" }).click();
  await expectStatus(page, "operation posted");
  await expect(
    onHandTable(page).getByRole("row", {
      name: new RegExp(`${itemCode}.*${mainCode}.*10.500`),
    }),
  ).toBeVisible();

  const beforeImport = await onHandTable(page).textContent();
  const [purchaseOrders, receipts, invoices] = await Promise.all([
    readFile(SAMPLE_FILES.purchase_orders),
    readFile(SAMPLE_FILES.receipts),
    readFile(SAMPLE_FILES.invoices),
  ]);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const bootstrap = await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`, {
      headers: { Origin: E2E_WEB_ORIGIN },
    });
    const { csrf_token } = await bootstrap.json();
    const saved = await page.request.post(`${E2E_API_ORIGIN}/api/v1/runs/three-way`, {
      headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: csrf_token },
      multipart: {
        purchase_orders: {
          name: "purchase_orders.csv",
          mimeType: "text/csv",
          buffer: purchaseOrders,
        },
        receipts: { name: "goods_receipts.csv", mimeType: "text/csv", buffer: receipts },
        invoices: { name: "invoices.csv", mimeType: "text/csv", buffer: invoices },
      },
    });
    expect(saved.status()).toBe(201);
  }
  await page.reload();
  await expect(page.getByRole("heading", { name: "Current on-hand inventory" })).toBeVisible();
  expect(
    await onHandTable(page).textContent(),
  ).toBe(beforeImport);

  await choosePosting(page, "STOCK_RECEIPT", itemCode, mainCode, "2.500");
  await page.getByRole("button", { name: "Post operation" }).click();
  await choosePosting(page, "STOCK_ISSUE", itemCode, mainCode, "3");
  await page.getByRole("button", { name: "Post operation" }).click();
  await choosePosting(page, "ADJUSTMENT_IN", itemCode, mainCode, "1");
  await page.getByRole("button", { name: "Post operation" }).click();
  await choosePosting(page, "ADJUSTMENT_OUT", itemCode, mainCode, "1");
  await page.getByRole("button", { name: "Post operation" }).click();
  await choosePosting(page, "TRANSFER", itemCode, mainCode, "4");
  await page.getByLabel("Destination location").selectOption({ label: storeCode });
  await page.getByRole("button", { name: "Post operation" }).click();
  await expect(page.getByText(`${itemCode} · ${storeCode} ·`, { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Reverse" }).first().click();
  await expectStatus(page, "Reversal posted");
  await page.reload();
  await expect(
    onHandTable(page).getByRole("row", {
      name: new RegExp(`${itemCode}.*${mainCode}.*10.000`),
    }),
  ).toBeVisible();

  await choosePosting(page, "STOCK_ISSUE", itemCode, mainCode, "999");
  await page.getByRole("button", { name: "Post operation" }).click();
  const conflict = page
    .getByRole("alert")
    .filter({ hasText: "Insufficient on-hand quantity" });
  await expect(conflict).toBeVisible();
  await expect(conflict).toBeFocused();

  const storeForm = page.getByRole("form", { name: `Edit location ${storeCode}` });
  await storeForm.getByRole("button", { name: "Archive" }).click();
  await expectStatus(page, "Location archived");
  await expect(storeForm.getByRole("button", { name: "Restore" })).toBeEnabled();
  await expectAccessible(page);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("region", { name: "Inventory movement history" }).focus();
  await page.keyboard.press("ArrowRight");
  await expectAccessible(page);
});

test("inventory roles are enforced in UI and API", async ({ page }) => {
  await login(page.request, seed.manager_email);
  await page.goto("/inventory");
  await expect(page.getByRole("heading", { name: "Current on-hand inventory" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Post inventory" })).toHaveCount(0);
  expect((await page.request.get(`${E2E_API_ORIGIN}${INVENTORY_API_PATH}/balances`)).status()).toBe(
    200,
  );
  expect(
    (
      await inventoryWrite(page.request, "/locations", {
        location_code: "DENIED",
        name: "Denied",
      })
    ).status(),
  ).toBe(403);

  await login(page.request, seed.member_email);
  const identity = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
  ).json();
  const memberOrganization = identity.memberships.find(
    (membership: { organization_name: string; role: string }) =>
      membership.organization_name === seed.organization_name && membership.role === "MEMBER",
  );
  expect(memberOrganization).toBeTruthy();
  await authPost(page.request, "select-organization", {
    organization_id: memberOrganization.organization_id,
  });
  await page.goto("/inventory");
  await expect(page.getByRole("heading", { name: "Inventory access required" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Inventory", exact: true })).toHaveCount(0);
  expect((await page.request.get(`${E2E_API_ORIGIN}${INVENTORY_API_PATH}/balances`)).status()).toBe(
    403,
  );
  await expectAccessible(page);
});

declare global {
  interface Window {
    inventoryXss?: boolean;
  }
}
