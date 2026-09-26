import { readFile } from "node:fs/promises";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";

import { expect, test, type APIRequestContext } from "@playwright/test";

const ORIGIN = process.env.PRODUCTION_E2E_ORIGIN?.trim() || "https://localhost";
const HTTP_ORIGIN = process.env.PRODUCTION_E2E_HTTP_ORIGIN?.trim() || "http://localhost";
const MANAGER =
  process.env.PRODUCTION_E2E_MANAGER_EMAIL?.trim() ||
  "deployment-manager@example.com";
const OUTSIDER =
  process.env.PRODUCTION_E2E_OUTSIDER_EMAIL?.trim() ||
  "deployment-outsider@example.com";
const PASSWORD =
  process.env.PRODUCTION_E2E_PASSWORD?.trim() ||
  "synthetic deployment passphrase";
const PRIVATE_MARKER = "deployment-log-private-marker";
const AUTH = "/api/v1/auth";
const SAMPLE_DIR = path.resolve(process.cwd(), "../examples/sample_data");

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get(`${AUTH}/csrf`, {
    headers: { Origin: ORIGIN },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).csrf_token;
}

async function postAuth(
  request: APIRequestContext,
  action: string,
  data: Record<string, string> = {},
) {
  return request.post(`${AUTH}/${action}`, {
    data,
    headers: { Origin: ORIGIN, "X-CSRF-Token": await csrf(request) },
  });
}

async function login(request: APIRequestContext, email: string) {
  const response = await postAuth(request, "login", {
    email,
    password: PASSWORD,
  });
  expect(response.status()).toBe(200);
  return response;
}

test("production HTTPS proxy preserves the complete security boundary", async ({
  page,
  playwright,
  request,
}) => {
  const redirect = await request.get(`${HTTP_ORIGIN}/health`, {
    maxRedirects: 0,
  });
  expect(redirect.status()).toBe(308);
  expect(redirect.headers().location).toBe(`${ORIGIN}/health`);

  const live = await request.get(`/health?probe=${PRIVATE_MARKER}`, {
    headers: {
      Authorization: PRIVATE_MARKER,
      "X-Forwarded-For": "198.51.100.42",
    },
  });
  expect(live.status()).toBe(200);
  expect(live.headers()["x-request-id"]).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  const ready = await request.get("/health/ready");
  expect(ready.status()).toBe(200);
  expect(await ready.json()).toEqual({ status: "ready" });
  expect(ready.headers()["cache-control"]).toBe("no-store");

  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const frontendHeaders = await (await request.get("/login")).headers();
  expect(frontendHeaders["content-security-policy"]).toContain(
    "frame-ancestors 'none'",
  );
  expect(frontendHeaders["x-content-type-options"]).toBe("nosniff");
  expect(frontendHeaders["permissions-policy"]).toContain("camera=()");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByLabel("Email", { exact: true }).fill(MANAGER);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/reconcile$/);
  await page.reload();
  await expect(page.getByText("Deployment manager", { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  const loginResponse = await login(request, MANAGER);
  const setCookies = loginResponse
    .headersArray()
    .filter((header) => header.name.toLowerCase() === "set-cookie")
    .map((header) => header.value);
  expect(setCookies).toHaveLength(2);
  for (const cookie of setCookies) {
    expect(cookie).toMatch(/^__Host-/);
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("HttpOnly");
    expect(cookie.toLowerCase()).toContain("samesite=strict");
    expect(cookie).toContain("Path=/");
    expect(cookie).not.toContain("Domain=");
  }

  const identity = await request.get(`${AUTH}/me`);
  expect(identity.status()).toBe(200);
  expect(identity.headers()["cache-control"]).toBe("no-store");
  expect(identity.headers()["x-content-type-options"]).toBe("nosniff");

  const samples = await Promise.all(
    ["purchase_orders.csv", "goods_receipts.csv", "invoices.csv"].map(
      async (name) => ({
        name,
        mimeType: "text/csv",
        buffer: await readFile(path.join(SAMPLE_DIR, name)),
      }),
    ),
  );
  const created = await request.post("/api/v1/runs/three-way", {
    headers: { Origin: ORIGIN, "X-CSRF-Token": await csrf(request) },
    multipart: {
      purchase_orders: samples[0],
      receipts: samples[1],
      invoices: samples[2],
    },
  });
  expect(created.status()).toBe(201);
  const saved = await created.json();
  expect(saved.report.summary).toMatchObject({
    invoices_processed: 15,
    invoice_lines_processed: 17,
    matched_lines: 6,
    review_required_lines: 11,
    disputed_amounts: { EUR: "2450.00", MAD: "10199.00", USD: "75.00" },
  });

  const rejectedMutation = await request.patch(
    `/api/v1/runs/${saved.run.id}`,
    { data: { expected_version: saved.run.version, title: "Synthetic release smoke" } },
  );
  expect(rejectedMutation.status()).toBe(403);
  const updated = await request.patch(`/api/v1/runs/${saved.run.id}`, {
    data: { expected_version: saved.run.version, title: "Synthetic release smoke" },
    headers: { Origin: ORIGIN, "X-CSRF-Token": await csrf(request) },
  });
  expect(updated.status()).toBe(200);

  const outsider = await playwright.request.newContext({
    baseURL: ORIGIN,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { Origin: ORIGIN },
  });
  try {
    await login(outsider, OUTSIDER);
    expect((await outsider.get(`/api/v1/runs/${saved.run.id}`)).status()).toBe(
      404,
    );
  } finally {
    await outsider.dispose();
  }

  const spoofed = await request.get(`${AUTH}/me/`, {
    maxRedirects: 0,
    headers: {
      "X-Forwarded-For": "198.51.100.99",
      "X-Forwarded-Host": "attacker.example",
      "X-Forwarded-Proto": "http",
    },
  });
  expect(spoofed.status()).toBe(307);
  expect(spoofed.headers().location).toBe(`${ORIGIN}${AUTH}/me`);
  expect(spoofed.headers().location).not.toContain("attacker.example");

  const oversizedAuth = await request.post(`${AUTH}/login`, {
    data: "x".repeat(40 * 1024),
    headers: { "Content-Type": "application/json", Origin: ORIGIN },
  });
  expect(oversizedAuth.status()).toBe(413);

  const oversizedUpload = await request.post("/api/v1/reconcile", {
    data: Buffer.alloc(32 * 1024 * 1024 + 1),
    headers: { "Content-Type": "application/octet-stream" },
    timeout: 120_000,
  });
  expect(oversizedUpload.status()).toBe(413);

  const logout = await postAuth(request, "logout");
  expect(logout.status()).toBe(200);
  expect((await request.get(`${AUTH}/me`)).status()).toBe(401);

  const rateStatuses: number[] = [];
  const proof = await csrf(request);
  for (let index = 0; index < 12; index += 1) {
    const response = await request.post(`${AUTH}/login`, {
      data: { email: `rate-${index}@example.com`, password: PASSWORD },
      headers: { Origin: ORIGIN, "X-CSRF-Token": proof },
    });
    rateStatuses.push(response.status());
  }
  expect(rateStatuses).toContain(429);
});
