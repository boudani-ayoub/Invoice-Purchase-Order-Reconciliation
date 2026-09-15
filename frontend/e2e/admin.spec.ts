import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { authPost, TEST_PASSWORD } from "./auth-fixture";
import { E2E_API_ORIGIN, E2E_WEB_ORIGIN } from "./environment";
import { ADMIN_API_PATH } from "../src/constants/admin";
import { AUTH_API_PATH, CSRF_HEADER } from "../src/constants/auth";

interface Seed {
  password: string;
  manager_email: string;
  governance_admin_email: string;
  governance_member_email: string;
  governance_peer_email: string;
  governance_invited_email: string;
  governance_invitation_token: string;
  governance_organization_name: string;
  governance_member_name: string;
}

const seed = JSON.parse(process.env.E2E_WORKFLOW_SEED!) as Seed;

async function login(request: APIRequestContext, email: string) {
  await authPost(request, "logout");
  expect(
    (await authPost(request, "login", { email, password: seed.password })).status(),
  ).toBe(200);
}

async function adminMutation(
  request: APIRequestContext,
  path: string,
  data: Record<string, unknown>,
  method: "POST" | "PATCH" = "PATCH",
) {
  const bootstrap = await request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`, {
    headers: { Origin: E2E_WEB_ORIGIN },
  });
  const { csrf_token } = await bootstrap.json();
  return request.fetch(`${E2E_API_ORIGIN}${ADMIN_API_PATH}${path}`, {
    method,
    data,
    headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: csrf_token },
  });
}

async function members(request: APIRequestContext) {
  const response = await request.get(`${E2E_API_ORIGIN}${ADMIN_API_PATH}/members?limit=100`);
  expect(response.status()).toBe(200);
  return (await response.json()).items as Array<{
    user_id: string;
    email: string;
    role: string;
    status: string;
    version: number;
  }>;
}

async function loginInBrowser(page: Page, email: string, password = seed.password) {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/reconcile$/);
}

async function expectAccessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? ""),
    ),
  ).toEqual([]);
}

test("real organization governance covers invitations, lifecycle, conflicts, and audit", async ({
  page,
  playwright,
}) => {
  test.setTimeout(150_000);
  await login(page.request, seed.governance_admin_email);
  const identity = await (
    await page.request.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
  ).json();
  const organizationId = identity.active_organization_id as string;

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Administration navigation" })
    .getByRole("link", { name: "Members & invitations" })
    .click();
  await expect(page.getByRole("heading", { name: "Members" })).toBeVisible();
  await expect(
    page.getByRole("rowheader", { name: seed.governance_member_name }),
  ).toBeVisible();
  expect(await page.evaluate(() => Boolean(window.governanceXss))).toBe(false);

  const createdEmail = `browser-invite-${randomUUID()}@example.com`;
  await page.getByLabel("Email", { exact: true }).fill(createdEmail);
  await page.getByLabel("Role", { exact: true }).selectOption("AP_MANAGER");
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByText(createdEmail)).toBeVisible();

  const memberRole = page.getByLabel(`Role for ${seed.governance_member_name}`);
  await memberRole.selectOption("AP_MANAGER");
  await expect(memberRole).toHaveValue("AP_MANAGER");
  await page.getByRole("button", { name: "Sign out" }).click();
  await loginInBrowser(page, seed.governance_member_email);
  await page.getByLabel("Organization", { exact: true }).selectOption(organizationId);
  await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toBeVisible();

  const admin = await playwright.request.newContext({
    extraHTTPHeaders: { Origin: E2E_WEB_ORIGIN },
  });
  try {
    await login(admin, seed.governance_admin_email);
    let target = (await members(admin)).find(
      (value) => value.email === seed.governance_member_email,
    )!;
    let response = await adminMutation(admin, `/members/${target.user_id}`, {
      expected_version: target.version,
      role: "MEMBER",
    });
    expect(response.status()).toBe(200);
    await page.reload();
    await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toHaveCount(0);
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard access required" })).toBeVisible();

    target = (await members(admin)).find(
      (value) => value.email === seed.governance_member_email,
    )!;
    response = await adminMutation(admin, `/members/${target.user_id}`, {
      expected_version: target.version,
      status: "ARCHIVED",
    });
    expect(response.status()).toBe(200);
    expect(
      (
        await page.request.get(`${E2E_API_ORIGIN}/api/v1/dashboard/overview`)
      ).status(),
    ).toBe(403);
    target = (await members(admin)).find(
      (value) => value.email === seed.governance_member_email,
    )!;
    expect(
      (
        await adminMutation(admin, `/members/${target.user_id}`, {
          expected_version: target.version,
          status: "ACTIVE",
        })
      ).status(),
    ).toBe(200);

    const peer = await playwright.request.newContext({
      extraHTTPHeaders: { Origin: E2E_WEB_ORIGIN },
    });
    try {
      await login(peer, seed.governance_peer_email);
      const peerIdentity = await (
        await peer.get(`${E2E_API_ORIGIN}${AUTH_API_PATH}/me`)
      ).json();
      const personal = peerIdentity.memberships.find(
        (membership: { organization_id: string }) =>
          membership.organization_id !== organizationId,
      );
      await authPost(peer, "select-organization", {
        organization_id: personal.organization_id,
      });
      const isolated = await members(peer);
      expect(isolated).toHaveLength(1);
      expect(isolated.some((value) => value.email === seed.governance_member_email)).toBe(false);
      const onlyAdmin = isolated[0];
      expect(
        (
          await adminMutation(peer, `/members/${onlyAdmin.user_id}`, {
            expected_version: onlyAdmin.version,
            role: "MEMBER",
          })
        ).status(),
      ).toBe(409);

      await authPost(peer, "select-organization", { organization_id: organizationId });
      const shared = (await members(admin)).find(
        (value) => value.email === seed.governance_member_email,
      )!;
      const first = await adminMutation(admin, `/members/${shared.user_id}`, {
        expected_version: shared.version,
        role: "AP_MANAGER",
      });
      expect(first.status()).toBe(200);
      const stale = await adminMutation(peer, `/members/${shared.user_id}`, {
        expected_version: shared.version,
        status: "ARCHIVED",
      });
      expect(stale.status()).toBe(409);
      const changed = await first.json();
      expect(
        (
          await adminMutation(admin, `/members/${shared.user_id}`, {
            expected_version: changed.version,
            role: "MEMBER",
          })
        ).status(),
      ).toBe(200);
    } finally {
      await peer.dispose();
    }
  } finally {
    await admin.dispose();
  }

  await authPost(page.request, "logout");
  await page.goto(`/invite#token=${seed.governance_invitation_token}`);
  await expect(page).toHaveURL(/\/invite$/);
  await expect(page.getByText(seed.governance_organization_name)).toBeVisible();
  await page.getByLabel("Your name").fill("Invited browser member");
  await page.getByLabel("Password").fill(TEST_PASSWORD);
  await page.getByRole("button", { name: "Create invited account" }).click();
  await expect(page.getByRole("status")).toContainText("Account created");
  await loginInBrowser(page, seed.governance_invited_email, TEST_PASSWORD);
  await expect(page.getByText(seed.governance_organization_name, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await loginInBrowser(page, seed.governance_admin_email);
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  const renamed = `Renamed governance ${randomUUID()}`;
  await page.getByLabel("Display name").fill(renamed);
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("status")).toContainText("updated");
  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue(renamed);
  await page
    .getByRole("link", { name: "Members & invitations", exact: true })
    .click();
  await expect(
    page
      .getByRole("table", { name: "Organization members" })
      .getByRole("cell", { name: seed.governance_invited_email }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Audit", exact: true }).click();
  const audit = page.getByRole("table", { name: "Organization audit events" });
  await expect(audit.getByText("Invitation Accepted")).toBeVisible();
  await expect(audit.getByText("Organization Renamed")).toBeVisible();
  await expectAccessible(page);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("region", { name: "Audit table scroll area" }).focus();
  await page.keyboard.press("ArrowRight");
  await expectAccessible(page);
});

test("AP manager direct administration access is denied in UI and API", async ({ page }) => {
  await login(page.request, seed.manager_email);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  for (const resource of ["organization", "members", "invitations", "audit"]) {
    expect(
      (
        await page.request.get(`${E2E_API_ORIGIN}${ADMIN_API_PATH}/${resource}`)
      ).status(),
    ).toBe(403);
  }
  await expectAccessible(page);
});

declare global {
  interface Window {
    governanceXss?: boolean;
  }
}
