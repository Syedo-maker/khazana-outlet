import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end to end tests. They drive the real web app against the real API,
 * so the stack has to be running with seed data first:
 *
 *   .\scripts\dev.ps1 up
 *   .\scripts\dev.ps1 seed --reset
 *   .\scripts\dev.ps1 e2e
 *
 * The phone profile is the default because a reseller on an Android phone is
 * who the product is built for.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.WEB_URL ?? "http://localhost:3000",
    // Staging runs behind Caddy with its own local certificate authority.
    ignoreHTTPSErrors: Boolean(process.env.E2E_IGNORE_HTTPS_ERRORS),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : undefined,
  },
  projects: [{ name: "phone", use: { ...devices["Pixel 7"] } }],
});
