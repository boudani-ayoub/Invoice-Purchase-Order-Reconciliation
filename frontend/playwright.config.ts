import { defineConfig, devices } from "@playwright/test";

import {
  E2E_API_HOST,
  E2E_API_ORIGIN,
  E2E_API_PORT,
  E2E_WEB_HOST,
  E2E_WEB_ORIGIN,
  E2E_WEB_PORT,
} from "./e2e/environment";

const pythonExecutable =
  process.env.E2E_PYTHON_EXECUTABLE?.trim() ||
  (process.platform === "win32" ? ".venv/Scripts/python.exe" : "python");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: "test-results",
  reporter: [
    [process.env.CI ? "github" : "list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: E2E_WEB_ORIGIN,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `${JSON.stringify(pythonExecutable)} -m uvicorn reconcile.web.app:app --host ${E2E_API_HOST} --port ${E2E_API_PORT}`,
      cwd: "..",
      env: {
        ...process.env,
        RECONCILE_ALLOWED_ORIGINS: E2E_WEB_ORIGIN,
      },
      url: `${E2E_API_ORIGIN}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `npm run start -- --hostname ${E2E_WEB_HOST} --port ${E2E_WEB_PORT}`,
      cwd: ".",
      env: {
        ...process.env,
        NEXT_PUBLIC_API_BASE_URL: E2E_API_ORIGIN,
      },
      url: E2E_WEB_ORIGIN,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
