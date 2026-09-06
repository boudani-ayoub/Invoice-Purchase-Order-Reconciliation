import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import {
  ANALYSIS_MODES,
  ANALYSIS_HUB_PATH,
  analysisApiPath,
  analysisPath,
} from "../src/constants/analysis-modes";
import { UPLOAD_SOURCES } from "../src/constants/uploads";
import { E2E_API_ORIGIN } from "./environment";
import { createUnicodeSources } from "./helpers";

test("analysis hub exposes all four choices accessibly", async ({ page }) => {
  await page.goto(ANALYSIS_HUB_PATH);
  for (const definition of Object.values(ANALYSIS_MODES)) {
    await expect(
      page.getByRole("link", { name: new RegExp(definition.title) }),
    ).toHaveAttribute("href", analysisPath(definition.id));
  }
  const scan = await new AxeBuilder({ page }).analyze();
  expect(
    scan.violations.filter((issue) =>
      ["serious", "critical"].includes(issue.impact ?? ""),
    ),
  ).toEqual([]);
});

for (const definition of Object.values(ANALYSIS_MODES)) {
  test(`${definition.id} completes with real services and accessible results`, async ({
    page,
  }, testInfo) => {
    const { files } = await createUnicodeSources(testInfo);
    await page.goto(analysisPath(definition.id));
    await expect(page.getByText(definition.limitations)).toBeVisible();
    const submit = page.getByRole("button", { name: definition.submitLabel });
    for (const source of UPLOAD_SOURCES) {
      if (definition.requiredSources.includes(source.field)) {
        await expect(submit).toBeDisabled();
        await page
          .getByLabel(source.actionLabel)
          .setInputFiles(files[source.field]);
      } else {
        await expect(page.getByLabel(source.actionLabel)).toHaveCount(0);
      }
    }
    const responsePromise = page.waitForResponse(
      `${E2E_API_ORIGIN}${analysisApiPath(definition.id)}`,
    );
    await submit.click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const report = await response.json();
    expect(report.mode).toBe(definition.id);
    expect(report.results).toHaveLength(1);
    const heading = page.getByRole("heading", { name: definition.resultTitle });
    await expect(heading).toBeVisible();
    await expect(heading).toBeFocused();
    const scrollRegion = page.getByRole("region", {
      name:
        definition.id === "po-receipt"
          ? "Fulfillment quantities"
          : "Invoice analysis lines",
    });
    await scrollRegion.focus();
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(() => scrollRegion.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0);
    const scan = await new AxeBuilder({ page }).analyze();
    expect(
      scan.violations.filter((issue) =>
        ["serious", "critical"].includes(issue.impact ?? ""),
      ),
    ).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole("button", {
        name:
          definition.id === "po-receipt"
            ? "Start new analysis"
            : "Start new reconciliation",
      })
      .click();
    await expect(submit).toBeDisabled();
    await expect(heading).toBeHidden();
  });
}
