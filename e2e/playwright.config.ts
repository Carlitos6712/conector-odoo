import { defineConfig, devices } from "@playwright/test";

const BACKEND_PORT = process.env.E2E_BACKEND_PORT ?? "8100";
const ODOO_PORT = process.env.E2E_ODOO_PORT ?? "8169";

export default defineConfig({
  testDir: "./tests",
  // One serial flow against shared state (single backend, single fake Odoo).
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${BACKEND_PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    locale: "es-ES",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Fake Odoo JSON-RPC (tests-only). Not reused: a stale server would carry old partners.
      command: `uv run python -m tests.e2e_support.fake_odoo --port ${ODOO_PORT}`,
      cwd: "..",
      url: `http://127.0.0.1:${ODOO_PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "node scripts/start-backend.mjs",
      url: `http://127.0.0.1:${BACKEND_PORT}/`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
});
