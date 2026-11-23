import { defineConfig, devices } from "@playwright/test";

/**
 * Page load measurements on a throttled connection and a slowed CPU.
 *
 * Not part of the e2e suite and not run in CI: timings on a shared runner are
 * noise, and a number that changes every run is worse than none. Run it on a
 * quiet machine against the production build of the web app:
 *
 *   npx playwright test -c playwright.perf.config.ts
 *
 * Results print as a table and are written to perf-results.json. The numbers
 * recorded in docs/performance.md come from this.
 */
export default defineConfig({
  testDir: "./perf",
  timeout: 300_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.WEB_URL ?? "http://localhost:3000",
    launchOptions: process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : undefined,
  },
  projects: [{ name: "android-3g", use: { ...devices["Pixel 7"] } }],
});
