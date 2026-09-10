import { expect, test } from "./auth-fixture";

import { E2E_API_ORIGIN } from "./environment";
import { createRunPath } from "../src/constants/runs";
import {
  createInvalidPurchaseOrders,
  createLargeAllowedPurchaseOrders,
  createOversizedPurchaseOrders,
  createUnicodeSources,
  SAMPLE_FILES,
  selectSourceFiles,
} from "./helpers";

const RECONCILIATION_URL = `${E2E_API_ORIGIN}${createRunPath("three-way")}`;

test("reconciles the sample exports and supports inspection and reset", async ({
  page,
}) => {
  const response = await page.goto("/");

  expect(response?.headers()["content-security-policy"]).toContain(
    "frame-ancestors 'none'",
  );
  expect(response?.headers()["x-content-type-options"]).toBe("nosniff");
  await expect(
    page.getByRole("heading", { name: "Choose the three source exports" }),
  ).toBeVisible();

  const purchaseOrderInput = page.getByLabel("Choose purchase orders");
  await purchaseOrderInput.focus();
  await expect(purchaseOrderInput).toBeFocused();
  await purchaseOrderInput.setInputFiles(SAMPLE_FILES.purchase_orders);
  await expect(page.getByText("purchase_orders.csv")).toBeVisible();
  await page.getByRole("button", { name: "Remove" }).click();
  await expect(page.getByText("purchase_orders.csv")).toBeHidden();

  await selectSourceFiles(page);
  await page.getByRole("button", { name: "Run reconciliation" }).click();

  const resultHeading = page.getByRole("heading", {
    name: "Reconciliation results",
  });
  await expect(resultHeading).toBeVisible();
  await expect(resultHeading).toBeFocused();
  await expect(page.getByText("Showing 11 of 17 lines")).toBeVisible();

  await page.getByRole("button", { name: "Matched" }).click();
  await expect(page.getByText("Showing 6 of 17 lines")).toBeVisible();
  await page
    .getByRole("searchbox", { name: "Search reconciliation lines" })
    .fill("INV-001");
  await expect(page.getByText("Showing 1 of 17 lines")).toBeVisible();
  await expect(page.getByText("INV-001", { exact: true })).toBeVisible();
  await page
    .getByRole("searchbox", { name: "Search reconciliation lines" })
    .fill("");

  await page.getByRole("button", { name: "All" }).click();
  await expect(page.getByText("Showing 17 of 17 lines")).toBeVisible();
  await page.getByRole("combobox", { name: "Filter by issue" }).click();
  await page.getByRole("option", { name: "Price mismatch" }).click();
  await expect(page.getByText("Showing 1 of 17 lines")).toBeVisible();
  await expect(page.getByText("INV-003", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Start new reconciliation" }).click();
  await expect(resultHeading).toBeHidden();
  await expect(page.getByText("No file selected")).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "Run reconciliation" }),
  ).toBeDisabled();
});

test("shows structured validation details from the real API", async ({
  page,
}, testInfo) => {
  const invalidPurchaseOrders = await createInvalidPurchaseOrders(testInfo);
  await page.goto("/");
  await selectSourceFiles(page, { purchase_orders: invalidPurchaseOrders });
  await page.getByRole("button", { name: "Run reconciliation" }).click();

  const alert = page
    .getByRole("alert")
    .filter({ hasText: "Some CSV data could not be processed" });
  await expect(alert).toContainText("Some CSV data could not be processed");
  await expect(alert).toContainText("Purchase orders");
  await expect(alert).toContainText("Row 2");
  await expect(alert).toContainText("ordered_quantity");
  await expect(alert).toContainText("greater than zero");
});

test("accepts a near-limit file without allowing duplicate submission", async ({
  page,
}, testInfo) => {
  test.slow();
  const largePurchaseOrders = await createLargeAllowedPurchaseOrders(testInfo);
  let reconciliationRequests = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url() === RECONCILIATION_URL) {
      reconciliationRequests += 1;
    }
  });

  await page.goto("/");
  await selectSourceFiles(page, { purchase_orders: largePurchaseOrders });
  await page.getByRole("button", { name: "Run reconciliation" }).click();

  const loadingButton = page.getByRole("button", { name: "Reconciling…" });
  await expect(loadingButton).toBeDisabled();
  await loadingButton.evaluate((button: HTMLButtonElement) => button.click());
  await expect(
    page.getByRole("heading", { name: "Reconciliation results" }),
  ).toBeVisible({
    timeout: 120_000,
  });
  expect(reconciliationRequests).toBe(1);
});

test("reports an oversized file and succeeds after replacement", async ({
  page,
}, testInfo) => {
  test.slow();
  const oversizedPurchaseOrders = await createOversizedPurchaseOrders(testInfo);
  await page.goto("/");
  await selectSourceFiles(page, { purchase_orders: oversizedPurchaseOrders });
  await page.getByRole("button", { name: "Run reconciliation" }).click();

  const alert = page
    .getByRole("alert")
    .filter({ hasText: "file is too large" });
  await expect(alert).toContainText("Purchase orders file is too large");
  await expect(alert).toContainText("10.0 MB");

  await page
    .getByLabel("Choose purchase orders")
    .setInputFiles(SAMPLE_FILES.purchase_orders);
  await expect(alert).toBeHidden();
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(
    page.getByRole("heading", { name: "Reconciliation results" }),
  ).toBeVisible();
});

test("recovers after the reconciliation service is unavailable", async ({
  page,
}) => {
  await page.route(RECONCILIATION_URL, (route) =>
    route.abort("connectionrefused"),
  );
  await page.goto("/");
  await selectSourceFiles(page);
  await page.getByRole("button", { name: "Run reconciliation" }).click();

  const alert = page
    .getByRole("alert")
    .filter({ hasText: "The reconciliation service could not be reached" });
  await expect(alert).toContainText(
    "The reconciliation service could not be reached",
  );
  await page.unroute(RECONCILIATION_URL);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByRole("heading", { name: "Reconciliation results" }),
  ).toBeVisible();
});

test("keeps long Unicode identifiers usable on a mobile viewport", async ({
  page,
}, testInfo) => {
  const { files, identifiers } = await createUnicodeSources(testInfo);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await selectSourceFiles(page, files);
  await page.getByRole("button", { name: "Run reconciliation" }).click();

  await expect(
    page.getByRole("heading", { name: "Reconciliation results" }),
  ).toBeVisible();
  const resultRow = page.getByRole("row").filter({ hasText: identifiers[0] });
  await expect(resultRow).toBeVisible();
  for (const identifier of identifiers) {
    await expect(resultRow).toContainText(identifier);
  }
  const viewport = await page.evaluate(() => ({
    contentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(viewport.contentWidth).toBeLessThanOrEqual(viewport.viewportWidth);
});
