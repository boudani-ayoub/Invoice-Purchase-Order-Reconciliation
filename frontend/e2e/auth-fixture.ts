import { randomUUID } from "node:crypto";
import { test as base, expect, type APIRequestContext } from "@playwright/test";
import { E2E_API_ORIGIN, E2E_WEB_ORIGIN } from "./environment";
import { AUTH_API_PATH, CSRF_HEADER } from "../src/constants/auth";

export const TEST_PASSWORD = "browser test private passphrase";

export async function authPost(
  request: APIRequestContext,
  action: string,
  data: Record<string, string> = {},
) {
  const bootstrap = await request.get(
    `${E2E_API_ORIGIN}${AUTH_API_PATH}/csrf`,
    { headers: { Origin: E2E_WEB_ORIGIN } },
  );
  expect(bootstrap.ok()).toBe(true);
  const { csrf_token } = await bootstrap.json();
  return request.post(`${E2E_API_ORIGIN}${AUTH_API_PATH}/${action}`, {
    data,
    headers: { Origin: E2E_WEB_ORIGIN, [CSRF_HEADER]: csrf_token },
  });
}

export async function registerAccount(request: APIRequestContext) {
  const email = `browser-${randomUUID()}@example.com`;
  expect(
    (
      await authPost(request, "register", {
        email,
        password: TEST_PASSWORD,
        display_name: "Browser tester",
        organization_name: "Browser test organization",
      })
    ).status(),
  ).toBe(202);
  return email;
}

export const test = base.extend({
  page: async ({ page }, runTest) => {
    const email = await registerAccount(page.request);
    expect(
      (
        await authPost(page.request, "login", {
          email,
          password: TEST_PASSWORD,
        })
      ).status(),
    ).toBe(200);
    await runTest(page);
  },
});
export { expect };
