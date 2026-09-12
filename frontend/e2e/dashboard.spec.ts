import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect, authPost } from "./auth-fixture";
import { E2E_API_ORIGIN, E2E_WEB_ORIGIN } from "./environment";
import { selectSourceFiles } from "./helpers";
import { AUTH_API_PATH, CSRF_HEADER } from "../src/constants/auth";
import { DASHBOARD_API_PATH } from "../src/constants/dashboard";
import { createRunPath, runApiPath } from "../src/constants/runs";
import { FINDINGS_API_PATH, findingApiPath } from "../src/constants/workflow";

async function sample(page: Page) {
  await page.goto("/reconcile/three-way");
  await selectSourceFiles(page);
  const pending = page.waitForResponse(
    `${E2E_API_ORIGIN}${createRunPath("three-way")}`,
  );
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  const response = await pending;
  expect(response.status()).toBe(201);
  await expect(
    page.getByText("Saved to history.", { exact: false }),
  ).toBeVisible();
  return response.json();
}
async function mutate(page: Page, path: string, data: object, method = "POST") {
  const { csrf_token } = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`)
  ).json();
  const response = await page.request.fetch(`${E2E_API_ORIGIN}${path}`, {
    method,
    data,
    headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: csrf_token },
  });
  expect(response.status()).toBe(200);
  return response.json();
}
async function overview(page: Page) {
  const response = await page.request.get(
    `${E2E_API_ORIGIN}${DASHBOARD_API_PATH}/overview`,
  );
  expect(response.status()).toBe(200);
  return response.json();
}
async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter((v) =>
      ["serious", "critical"].includes(v.impact ?? ""),
    ),
  ).toEqual([]);
}

test("empty dashboard, UTC windows, keyboard table, and mobile layout", async ({
  page,
}) => {
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Current backlog" }),
  ).toBeVisible();
  await expect(page.getByText(/No non-archived analyses yet/)).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Unresolved age" })
      .getByText("No unresolved findings"),
  ).toHaveCount(2);
  await accessible(page);
  for (const days of [7, 90, 30]) {
    await page.getByLabel("Activity window").selectOption(`${days}d`);
    const tableToggle = page.getByText("Daily activity table", { exact: true });
    await expect(tableToggle).toBeVisible();
    await tableToggle.focus();
    await page.keyboard.press("Enter");
    await expect(
      page
        .getByRole("table", { name: "Daily workflow activity" })
        .getByRole("row"),
    ).toHaveCount(days + 1);
  }
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await accessible(page);
});

test("real workflow changes refresh dashboard without combining repeated run amounts", async ({
  page,
}) => {
  const saved = await sample(page);
  const first = await overview(page);
  const me = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
  ).json();
  const findings = await (
    await page.request.get(
      `${E2E_API_ORIGIN}${FINDINGS_API_PATH}?run_id=${saved.run.id}`,
    )
  ).json();
  let finding = findings.items[0];
  finding = await mutate(
    page,
    findingApiPath(finding.id),
    {
      expected_version: finding.version,
      assignee_user_id: me.user.id,
      due_at: new Date(Date.now() - 86400000).toISOString(),
      reminder_at: new Date(Date.now() - 86400000).toISOString(),
    },
    "PATCH",
  );
  for (const target_status of ["RESOLVED", "OPEN", "RESOLVED", "OPEN"]) {
    finding = await mutate(page, `${findingApiPath(finding.id)}/transition`, {
      expected_version: finding.version,
      target_status,
      ...(target_status === "RESOLVED"
        ? { resolution_note: "Private resolution text not in dashboard" }
        : {}),
    });
  }
  const changed = await overview(page);
  expect(changed.backlog.unresolved).toBe(first.backlog.unresolved);
  expect(changed.backlog.overdue).toBe(1);
  expect(changed.backlog.reminder_due).toBe(1);
  expect(changed.activity.resolution_events).toBe(2);
  expect(changed.activity.reopen_events).toBe(2);
  await sample(page);
  await page.goto("/dashboard");
  await expect(
    page
      .getByRole("table", { name: "Current assignee workload" })
      .getByText(me.user.display_name),
  ).toBeVisible();
  const recent = page.getByRole("region", { name: "Recent analyses" });
  await expect(recent.getByText("2,450.00", { exact: true })).toHaveCount(2);
  await expect(recent.getByText("10,199.00", { exact: true })).toHaveCount(2);
  await expect(recent.getByText("75.00", { exact: true })).toHaveCount(2);
  await expect(recent.getByText("4,900.00", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("Private resolution text not in dashboard"),
  ).toHaveCount(0);
  const beforeArchive = await overview(page);
  await mutate(page, `${runApiPath(saved.run.id)}/archive`, {
    expected_version: saved.run.version,
  });
  await page.getByRole("button", { name: "Refresh dashboard" }).click();
  await expect(recent.getByText("2,450.00", { exact: true })).toHaveCount(1);
  expect((await overview(page)).backlog).toEqual(beforeArchive.backlog);
  await accessible(page);
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByText("Daily activity table", { exact: true }).click();
  await expect(
    page
      .getByRole("table", { name: "Daily workflow activity" })
      .getByRole("row"),
  ).toHaveCount(31);
  await accessible(page);
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
});

test("manager access, member denial, and organization switch clear the dashboard", async ({
  page,
}) => {
  const seed = JSON.parse(process.env.E2E_WORKFLOW_SEED!);
  await authPost(page.request, "logout");
  expect(
    (
      await authPost(page.request, "login", {
        email: seed.manager_email,
        password: seed.password,
      })
    ).status(),
  ).toBe(200);
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Current backlog" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  await authPost(page.request, "logout");
  expect(
    (
      await authPost(page.request, "login", {
        email: seed.member_email,
        password: seed.password,
      })
    ).status(),
  ).toBe(200);
  const me = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
  ).json();
  const team = me.memberships.find(
    (m: { role: string }) => m.role === "MEMBER",
  );
  const personal = me.memberships.find(
    (m: { role: string }) => m.role === "ORG_ADMIN",
  );
  await authPost(page.request, "select-organization", {
    organization_id: personal.organization_id,
  });
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Current backlog" }),
  ).toBeVisible();
  await page
    .getByLabel("Organization", { exact: true })
    .selectOption(team.organization_id);
  await expect(
    page.getByRole("heading", { name: "Dashboard access required" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Dashboard", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Current backlog" }),
  ).toHaveCount(0);
  for (const endpoint of ["overview", "trends", "issues", "workload"]) {
    expect(
      (
        await page.request.get(
          `${E2E_API_ORIGIN}${DASHBOARD_API_PATH}/${endpoint}`,
        )
      ).status(),
    ).toBe(403);
  }
  await accessible(page);
  await page
    .getByLabel("Organization", { exact: true })
    .selectOption(personal.organization_id);
  await expect(
    page.getByRole("heading", { name: "Current backlog" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});
