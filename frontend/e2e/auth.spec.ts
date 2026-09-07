import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { authPost, registerAccount, TEST_PASSWORD } from "./auth-fixture";
import { E2E_API_ORIGIN } from "./environment";

test("registration, invalid login, sign in, refresh, and logout use the real API", async ({
  page,
}) => {
  const email = `browser-${randomUUID()}@example.com`;
  await page.goto("/reconcile");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByRole("link", { name: "Create account" }).click();
  await page.getByLabel("Your name").fill("Browser reviewer");
  await page.getByLabel("Organization name").fill("Browser procurement");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(TEST_PASSWORD);
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
    "type",
    "text",
  );
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("status")).toContainText("eligible");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("incorrect password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const loginError = page.getByRole("main").getByRole("alert");
  await expect(loginError).toContainText("Unable to sign in");
  await expect(loginError).toBeFocused();
  await page.getByLabel("Password", { exact: true }).fill(TEST_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/reconcile$/);
  await expect(
    page.getByText("Browser procurement", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Browser reviewer", { exact: true }),
  ).toBeVisible();
  const cookies = await page.context().cookies(E2E_API_ORIGIN);
  const session = cookies.find(
    (cookie) => cookie.name === "reconcile-dev-session",
  );
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Strict");
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/reconcile/three-way");
  await expect(page).toHaveURL(/\/login$/);
});

test("server-side revocation removes the workspace on refresh", async ({
  page,
}) => {
  const email = await registerAccount(page.request);
  await authPost(page.request, "login", { email, password: TEST_PASSWORD });
  await page.goto("/reconcile");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  const copied = (await page.context().cookies(E2E_API_ORIGIN)).find(
    (c) => c.name === "reconcile-dev-session",
  )!;
  await authPost(page.request, "logout");
  await page.context().addCookies([copied]);
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);
  expect(
    (await page.request.get(`${E2E_API_ORIGIN}/api/v1/auth/me`)).status(),
  ).toBe(401);
});

test("two real accounts cannot select each other's organizations", async ({
  playwright,
}) => {
  const first = await playwright.request.newContext();
  const second = await playwright.request.newContext();
  try {
    const organizations: string[] = [];
    for (const request of [first, second]) {
      const email = await registerAccount(request);
      expect(
        (
          await authPost(request, "login", { email, password: TEST_PASSWORD })
        ).ok(),
      ).toBe(true);
      const identity = await (
        await request.get(`${E2E_API_ORIGIN}/api/v1/auth/me`)
      ).json();
      organizations.push(identity.active_organization_id);
    }
    for (const [index, request] of [first, second].entries()) {
      expect(
        (
          await authPost(request, "select-organization", {
            organization_id: organizations[1 - index],
          })
        ).status(),
      ).toBe(403);
      const identity = await (
        await request.get(`${E2E_API_ORIGIN}/api/v1/auth/me`)
      ).json();
      expect(identity.active_organization_id).toBe(organizations[index]);
    }
  } finally {
    await first.dispose();
    await second.dispose();
  }
});

test("recovery and verification stay generic, and invalid fragment tokens are removed", async ({
  page,
}) => {
  await page.goto("/forgot-password");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`unknown-${randomUUID()}@example.com`);
  await page
    .getByRole("button", { name: "Send recovery instructions" })
    .click();
  await expect(page.getByRole("status")).toContainText("eligible");
  await page.goto("/verify-email#token=invalid");
  await expect(page).toHaveURL(/\/verify-email$/);
  await page.getByRole("button", { name: "Verify email", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await page
    .getByRole("button", { name: "Request a new verification link" })
    .click();
  await page
    .getByLabel("Email", { exact: true })
    .fill(`unknown-${randomUUID()}@example.com`);
  await page.getByRole("button", { name: "Resend verification" }).click();
  await expect(page.getByRole("status")).toContainText("eligible");
  await page.goto("/reset-password");
  await expect(
    page.getByRole("button", { name: "Change password" }),
  ).toBeDisabled();
});

for (const path of [
  "login",
  "register",
  "forgot-password",
  "reset-password",
  "verify-email",
]) {
  test(`${path} supports narrow layout and has no serious or critical axe violations`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`/${path}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() => document.activeElement !== document.body),
    ).toBe(true);
    const result = await new AxeBuilder({ page }).analyze();
    expect(
      result.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      ),
    ).toEqual([]);
  });
}
