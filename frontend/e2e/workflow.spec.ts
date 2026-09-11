import AxeBuilder from "@axe-core/playwright";
import type { APIRequestContext, Page } from "@playwright/test";
import {
  expect,
  test,
  authPost,
  registerAccount,
  TEST_PASSWORD,
} from "./auth-fixture";
import { E2E_API_ORIGIN, E2E_WEB_ORIGIN } from "./environment";
import { selectSourceFiles } from "./helpers";
import { AUTH_API_PATH, CSRF_HEADER } from "../src/constants/auth";
import { createRunPath, runApiPath, runPath } from "../src/constants/runs";
import {
  FINDINGS_API_PATH,
  findingApiPath,
  findingPath,
  WORKFLOW_CONFLICT,
} from "../src/constants/workflow";

async function sample(page: Page) {
  await page.goto("/reconcile/three-way");
  await selectSourceFiles(page);
  const pending = page.waitForResponse(
    `${E2E_API_ORIGIN}${createRunPath("three-way")}`,
  );
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  const response = await pending;
  expect(response.status()).toBe(201);
  const saved = await response.json();
  await expect(
    page.getByText("Saved to history.", { exact: false }),
  ).toBeVisible();
  return saved;
}
async function firstFinding(page: Page, runId: string) {
  const response = await page.request.get(
    `${E2E_API_ORIGIN}${FINDINGS_API_PATH}?run_id=${encodeURIComponent(runId)}`,
  );
  expect(response.status()).toBe(200);
  return (await response.json()).items[0];
}
async function mutation(
  request: APIRequestContext,
  id: string,
  body: object,
  action?: string,
) {
  const bootstrap = await request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`);
  const { csrf_token } = await bootstrap.json();
  return request.fetch(
    `${E2E_API_ORIGIN}${findingApiPath(id)}${action ? `/${action}` : ""}`,
    {
      method: action ? "POST" : "PATCH",
      data: body,
      headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: csrf_token },
    },
  );
}
async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter((v) =>
      ["serious", "critical"].includes(v.impact ?? ""),
    ),
  ).toEqual([]);
}
async function currentStatus(page: Page, status: string) {
  await expect(
    page
      .getByRole("region", { name: "Current workflow" })
      .getByText(status, { exact: true }),
  ).toBeVisible();
}

test("run findings support assignment, schedule, comments, resolve, reopen, and login persistence", async ({
  page,
}) => {
  const me = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
  ).json();
  const saved = await sample(page);
  const finding = await firstFinding(page, saved.run.id);
  await page.goto(runPath(saved.run.id));
  await page
    .getByRole("link", { name: "Work on findings from this run" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Work", exact: true }),
  ).toBeVisible();
  await accessible(page);
  await page.screenshot({
    path: "test-results/workflow-queue-desktop.png",
    fullPage: true,
  });
  await page.goto(findingPath(finding.id));
  await currentStatus(page, "Open");
  await page.getByLabel("Assignee", { exact: true }).selectOption(me.user.id);
  const past = new Date(Date.now() - 86_400_000).toISOString().slice(0, 16);
  await page.getByLabel("Due date and time (UTC)", { exact: true }).fill(past);
  await page
    .getByLabel("Reminder date and time (UTC)", { exact: true })
    .fill(past);
  await page
    .getByRole("button", { name: "Save assignment and schedule" })
    .click();
  await expect(page.getByText("Overdue", { exact: true })).toBeVisible();
  await expect(page.getByText("Reminder due", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await accessible(page);
  const markup =
    '<img src=x onerror="window.workflowXss=true"> supplier discussion';
  await page.getByLabel("Comment", { exact: true }).fill(markup);
  await page.getByRole("button", { name: "Add comment", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Workflow history" })
      .getByText(markup, { exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => "workflowXss" in window)).toBe(false);
  await page.getByRole("button", { name: "Start review" }).focus();
  await page.keyboard.press("Enter");
  await currentStatus(page, "In review");
  await page.getByLabel("Resolution note").fill(markup);
  await page
    .getByRole("button", { name: "Resolve finding", exact: true })
    .click();
  await currentStatus(page, "Resolved");
  await expect(page.getByText("Overdue", { exact: true })).toHaveCount(0);
  await accessible(page);
  await page.getByRole("button", { name: "Reopen finding" }).click();
  await currentStatus(page, "Open");
  await expect(
    page
      .getByRole("region", { name: "Workflow history" })
      .getByText(markup, { exact: true }),
  ).toHaveCount(2);
  await page.goto("/work");
  await page.getByLabel("Assignment", { exact: true }).selectOption("me");
  await page.getByLabel("Overdue only").check();
  await page.getByLabel("Reminder due only").check();
  await expect(
    page.getByRole("list", { name: "Finding queue" }).locator(":scope > li"),
  ).toHaveCount(1);
  await accessible(page);
  await page.getByLabel("Workflow status").selectOption("RESOLVED");
  await expect(page.getByText("No findings match this view.")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Email", { exact: true }).fill(me.user.email);
  await page.getByLabel("Password", { exact: true }).fill(TEST_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/reconcile$/);
  await page.goto(findingPath(finding.id));
  await page.reload();
  await currentStatus(page, "Open");
  await expect(
    page
      .getByRole("region", { name: "Workflow history" })
      .getByText(markup, { exact: true }),
  ).toHaveCount(2);
  expect(
    (
      await (
        await page.request.get(`${E2E_API_ORIGIN}${runApiPath(saved.run.id)}`)
      ).json()
    ).report,
  ).toEqual(saved.report);
  expect(saved.report.summary.disputed_amounts).toEqual({
    EUR: "2450.00",
    MAD: "10199.00",
    USD: "75.00",
  });
  await page.screenshot({
    path: "test-results/workflow-mobile.png",
    fullPage: true,
  });
});

test("two editors conflict and must refresh without overwriting", async ({
  page,
}) => {
  const saved = await sample(page);
  const finding = await firstFinding(page, saved.run.id);
  const other = await page.context().newPage();
  try {
    await page.goto(findingPath(finding.id));
    await other.goto(findingPath(finding.id));
    await currentStatus(page, "Open");
    await currentStatus(other, "Open");
    await page.getByRole("button", { name: "Start review" }).click();
    await currentStatus(page, "In review");
    await other.getByRole("button", { name: "Start review" }).click();
    const alert = other.getByRole("main").getByRole("alert");
    await expect(alert).toHaveText(WORKFLOW_CONFLICT);
    await expect(alert).toBeFocused();
    await expect(
      other.getByRole("button", { name: "Start review" }),
    ).toBeDisabled();
    await accessible(other);
    await other.getByRole("button", { name: "Refresh finding" }).click();
    await currentStatus(other, "In review");
  } finally {
    await other.close();
  }
});

test("cross-tenant finding, mutations, comments, and run filters are denied", async ({
  page,
  playwright,
}) => {
  const saved = await sample(page);
  const finding = await firstFinding(page, saved.run.id);
  const second = await playwright.request.newContext();
  try {
    const email = await registerAccount(second);
    await authPost(second, "login", { email, password: TEST_PASSWORD });
    expect(
      (
        await second.get(
          `${E2E_API_ORIGIN}${FINDINGS_API_PATH}?run_id=${encodeURIComponent(saved.run.id)}`,
        )
      ).status(),
    ).toBe(404);
    expect(
      (
        await second.get(`${E2E_API_ORIGIN}${findingApiPath(finding.id)}`)
      ).status(),
    ).toBe(404);
    expect(
      (
        await mutation(second, finding.id, {
          expected_version: 1,
          due_at: null,
        })
      ).status(),
    ).toBe(404);
    expect(
      (
        await mutation(
          second,
          finding.id,
          { expected_version: 1, target_status: "IN_REVIEW" },
          "transition",
        )
      ).status(),
    ).toBe(404);
    expect(
      (
        await mutation(second, finding.id, { text: "Denied" }, "comments")
      ).status(),
    ).toBe(404);
    await authPost(page.request, "logout");
    await authPost(page.request, "login", { email, password: TEST_PASSWORD });
    await page.goto(findingPath(finding.id));
    await expect(
      page.getByRole("heading", { name: "Finding unavailable" }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Workflow controls" }),
    ).toHaveCount(0);
    await accessible(page);
  } finally {
    await second.dispose();
  }
});

test("real member sees self-scoped controls and cannot manage assignment", async ({
  page,
  browser,
}) => {
  const seed = JSON.parse(process.env.E2E_WORKFLOW_SEED!);
  await authPost(page.request, "logout");
  await authPost(page.request, "login", {
    email: seed.manager_email,
    password: seed.password,
  });
  const saved = await sample(page);
  const finding = await firstFinding(page, saved.run.id);
  const memberContext = await browser.newContext();
  const memberPage = await memberContext.newPage();
  try {
    await authPost(memberPage.request, "login", {
      email: seed.member_email,
      password: seed.password,
    });
    const me = await (
      await memberPage.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
    ).json();
    const team = me.memberships.find(
      (m: { organization_name: string }) =>
        m.organization_name === seed.organization_name,
    );
    expect(team.role).toBe("MEMBER");
    await authPost(memberPage.request, "select-organization", {
      organization_id: team.organization_id,
    });
    await memberPage.goto(findingPath(finding.id));
    await currentStatus(memberPage, "Open");
    await expect(
      memberPage.getByRole("button", { name: "Start review" }),
    ).toHaveCount(0);
    expect(
      (
        await mutation(
          memberPage.request,
          finding.id,
          { expected_version: 1, target_status: "IN_REVIEW" },
          "transition",
        )
      ).status(),
    ).toBe(403);
    await page.goto(findingPath(finding.id));
    await page.getByLabel("Assignee", { exact: true }).selectOption(me.user.id);
    await page
      .getByRole("button", { name: "Save assignment and schedule" })
      .click();
    await expect(
      page
        .getByRole("region", { name: "Current workflow" })
        .getByText(seed.member_name, { exact: true }),
    ).toBeVisible();
    expect(await page.evaluate(() => "workflowXss" in window)).toBe(false);
    await memberPage.reload();
    await expect(
      memberPage.getByLabel("Assignee", { exact: true }),
    ).toHaveCount(0);
    await memberPage.getByRole("button", { name: "Start review" }).click();
    await currentStatus(memberPage, "In review");
    expect(
      (
        await mutation(memberPage.request, finding.id, {
          expected_version: 3,
          assignee_user_id: null,
        })
      ).status(),
    ).toBe(403);
    await memberPage
      .getByLabel("Comment", { exact: true })
      .fill("Member investigation");
    await memberPage
      .getByRole("button", { name: "Add comment", exact: true })
      .click();
    await memberPage
      .getByLabel("Resolution note")
      .fill("Checked the discrepancy.");
    await memberPage
      .getByRole("button", { name: "Resolve finding", exact: true })
      .click();
    await currentStatus(memberPage, "Resolved");
    await memberPage.getByRole("button", { name: "Reopen finding" }).click();
    await currentStatus(memberPage, "Open");
    await memberPage.setViewportSize({ width: 375, height: 812 });
    await accessible(memberPage);
  } finally {
    await memberContext.close();
  }
});
