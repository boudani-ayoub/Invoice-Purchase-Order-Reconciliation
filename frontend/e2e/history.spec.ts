import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  test,
  authPost,
  registerAccount,
  TEST_PASSWORD,
} from "./auth-fixture";
import { E2E_API_ORIGIN, E2E_WEB_ORIGIN } from "./environment";
import { selectSourceFiles } from "./helpers";
import {
  createRunPath,
  HISTORY_PATH,
  RUN_CONFLICT_MESSAGE,
  runApiPath,
  runPath,
} from "../src/constants/runs";
import { AUTH_API_PATH, CSRF_HEADER } from "../src/constants/auth";
import type { Page } from "@playwright/test";

async function createSample(page: Page) {
  await page.goto("/reconcile/three-way");
  await selectSourceFiles(page);
  const pending = page.waitForResponse(
    `${E2E_API_ORIGIN}${createRunPath("three-way")}`,
  );
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  const response = await pending;
  expect(response.status()).toBe(201);
  const payload = await response.json();
  await expect(
    page.getByText("Saved to history.", { exact: false }),
  ).toBeVisible();
  return payload;
}
async function checkSample(page: Page) {
  await expect(
    page.getByText("Invoices processed").locator(".."),
  ).toContainText("15");
  await expect(
    page.getByText("Invoice lines", { exact: true }).locator(".."),
  ).toContainText("17");
  await expect(
    page.locator("p", { hasText: /^Matched$/ }).locator(".."),
  ).toContainText("6");
  await expect(
    page.locator("p", { hasText: /^Review required$/ }).locator(".."),
  ).toContainText("11");
  for (const amount of ["2,450.00", "10,199.00", "75.00"])
    await expect(page.getByText(amount, { exact: true }).first()).toBeVisible();
}
async function accessible(page: Page) {
  const scan = await new AxeBuilder({ page }).analyze();
  expect(
    scan.violations.filter((issue) =>
      ["serious", "critical"].includes(issue.impact ?? ""),
    ),
  ).toEqual([]);
}

test("saved sample survives history, edits, archive, restore, and a login cycle", async ({
  page,
}) => {
  const me = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
  ).json();
  const saved = await createSample(page);
  await checkSample(page);
  await page.getByRole("link", { name: "History", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Three-way Match", exact: true }),
  ).toBeVisible();
  await accessible(page);
  await page.reload();
  await page
    .getByRole("link", { name: "Three-way Match", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Source provenance" }),
  ).toBeVisible();
  await checkSample(page);
  await accessible(page);
  const detail = await (
    await page.request.get(`${E2E_API_ORIGIN}${runApiPath(saved.run.id)}`)
  ).json();
  expect(detail.report).toEqual(saved.report);
  await page.getByRole("button", { name: "Edit metadata" }).click();
  await expect(page.getByLabel("Title", { exact: true })).toBeFocused();
  await page.getByLabel("Title", { exact: true }).fill("Quarter-end review");
  await page
    .getByLabel("Internal note")
    .fill("Review with procurement before posting.");
  await accessible(page);
  await page.getByRole("button", { name: "Save metadata" }).click();
  await expect(
    page.getByRole("heading", { name: "Quarter-end review", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Review with procurement before posting."),
  ).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Archive run" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await accessible(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Archive run" })).toBeFocused();
  await page.getByRole("button", { name: "Archive run" }).click();
  await page.getByRole("button", { name: "Confirm archive" }).click();
  await expect(page.getByRole("button", { name: "Restore run" })).toBeVisible();
  await page.getByRole("link", { name: "History", exact: true }).click();
  await expect(page.getByText(/No saved runs match/)).toBeVisible();
  await page.getByLabel("History status").selectOption("true");
  await page.getByRole("link", { name: "Quarter-end review" }).click();
  await page.getByRole("button", { name: "Restore run" }).click();
  await expect(page.getByRole("button", { name: "Archive run" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email", { exact: true }).fill(me.user.email);
  await page.getByLabel("Password", { exact: true }).fill(TEST_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/reconcile$/);
  await page.goto(runPath(saved.run.id));
  await expect(
    page.getByRole("heading", { name: "Quarter-end review", exact: true }),
  ).toBeVisible();
  await checkSample(page);
});

test("another organization cannot read, edit, or archive the saved run", async ({
  page,
  browser,
}) => {
  const saved = await createSample(page);
  const context = await browser.newContext();
  try {
    const email = await registerAccount(context.request);
    expect(
      (
        await authPost(context.request, "login", {
          email,
          password: TEST_PASSWORD,
        })
      ).status(),
    ).toBe(200);
    const other = await context.newPage();
    await other.goto(`${E2E_WEB_ORIGIN}${runPath(saved.run.id)}`);
    await expect(other.getByRole("main").getByRole("alert")).toContainText(
      "Run not found",
    );
    await expect(
      other.getByRole("heading", { name: "Source provenance" }),
    ).toHaveCount(0);
    const bootstrap = await (
      await context.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`)
    ).json();
    const headers = {
      Origin: E2E_WEB_ORIGIN,
      [CSRF_HEADER]: bootstrap.csrf_token,
    };
    expect(
      (
        await context.request.patch(
          `${E2E_API_ORIGIN}${runApiPath(saved.run.id)}`,
          { headers, data: { expected_version: 1, title: "Other tenant" } },
        )
      ).status(),
    ).toBe(404);
    expect(
      (
        await context.request.post(
          `${E2E_API_ORIGIN}${runApiPath(saved.run.id)}/archive`,
          { headers, data: { expected_version: 1 } },
        )
      ).status(),
    ).toBe(404);
  } finally {
    await context.close();
  }
});

test("two browser editors cannot silently overwrite each other", async ({
  page,
}) => {
  const saved = await createSample(page);
  await page.goto(runPath(saved.run.id));
  await page.getByRole("button", { name: "Edit metadata" }).click();
  const second = await page.context().newPage();
  try {
    await second.goto(`${E2E_WEB_ORIGIN}${runPath(saved.run.id)}`);
    await second.getByRole("button", { name: "Edit metadata" }).click();
    await page.getByLabel("Title", { exact: true }).fill("First writer");
    await page.getByRole("button", { name: "Save metadata" }).click();
    await expect(
      page.getByRole("heading", { name: "First writer" }),
    ).toBeVisible();
    await second.getByLabel("Title", { exact: true }).fill("Stale writer");
    await second.getByRole("button", { name: "Save metadata" }).click();
    await expect(second.getByRole("main").getByRole("alert")).toHaveText(
      RUN_CONFLICT_MESSAGE,
    );
    await expect(second.getByRole("main").getByRole("alert")).toBeFocused();
    await second.getByRole("button", { name: "Refresh run" }).click();
    await expect(
      second.getByRole("heading", { name: "First writer" }),
    ).toBeVisible();
  } finally {
    await second.close();
  }
});

test("saved titles and notes display markup as text", async ({ page }) => {
  const saved = await createSample(page);
  await page.goto(runPath(saved.run.id));
  await page.getByRole("button", { name: "Edit metadata" }).click();
  const attack = "<script>window.historyAttack=true</script>";
  await page.getByLabel("Title", { exact: true }).fill(attack);
  await page.getByLabel("Internal note").fill(attack);
  await page.getByRole("button", { name: "Save metadata" }).click();
  await expect(
    page.getByRole("heading", { name: attack, exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => "historyAttack" in window)).toBe(false);
  await page.goto(HISTORY_PATH);
  await expect(
    page.getByRole("link", { name: attack, exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => "historyAttack" in window)).toBe(false);
});
