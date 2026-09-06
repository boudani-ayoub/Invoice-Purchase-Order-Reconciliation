import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { createInvalidPurchaseOrders, selectSourceFiles } from "./helpers";

async function expectNoHighImpactViolations(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page }).analyze();
  const violations = result.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  const summary = violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    targets: violation.nodes.flatMap((node) => node.target),
  }));
  expect(violations, JSON.stringify(summary, null, 2)).toEqual([]);
}

test("initial upload state has no serious or critical axe violations", async ({ page }) => {
  await page.goto("/");
  await expectNoHighImpactViolations(page);
});

test("ready state has no serious or critical axe violations", async ({ page }) => {
  await page.goto("/");
  await selectSourceFiles(page);
  await expect(page.getByRole("button", { name: "Run reconciliation" })).toBeEnabled();
  await expectNoHighImpactViolations(page);
});

test("successful result state has no serious or critical axe violations", async ({ page }) => {
  await page.goto("/");
  await selectSourceFiles(page);
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(page.getByRole("heading", { name: "Reconciliation results" })).toBeVisible();
  await expectNoHighImpactViolations(page);
});

test("validation error state has no serious or critical axe violations", async (
  { page },
  testInfo: TestInfo,
) => {
  const invalidPurchaseOrders = await createInvalidPurchaseOrders(testInfo);
  await page.goto("/");
  await selectSourceFiles(page, { purchase_orders: invalidPurchaseOrders });
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Some CSV data could not be processed" }),
  ).toBeVisible();
  await expectNoHighImpactViolations(page);
});
