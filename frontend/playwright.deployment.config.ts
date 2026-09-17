import { defineConfig, devices } from "@playwright/test";

const origin = process.env.PRODUCTION_E2E_ORIGIN?.trim() || "https://localhost";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "deployment.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: origin,
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
});
