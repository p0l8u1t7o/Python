import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end configuration.
 *
 * Runs against the **real stack**, not a mock: `scripts/dev.ps1` brings up the
 * bundled MQTT broker, the API, the ingest pipeline and three simulators, so
 * these tests see live values arriving the way a user does. That is worth more
 * than fixtures for the things a browser is needed to catch at all - Leaflet
 * measuring its container, native drag-and-drop, a hook order violation - and
 * it is why no assertion here pins a live *number*: those move every few
 * seconds by design.
 *
 * Uses the Chrome that is already installed rather than downloading Playwright's
 * own build. One less 150 MB copy, and it is the browser the operators actually
 * use.
 */
export default defineConfig({
  testDir: './e2e',
  // Serial. The suite signs in as the same account and writes per-user layout
  // preferences; parallel workers would race each other's saved state.
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'e2e-report' }]],
  outputDir: './e2e-results',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173',
    channel: 'chrome',
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    // The dev stack is on a self-signed-free plain HTTP origin; nothing to
    // relax, but keep navigation patient - the first load compiles the app.
    navigationTimeout: 30_000,
  },
  projects: [
    // Signs in once and saves the session. Everything else depends on it,
    // because login is throttled and a per-test sign-in would trip it.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chrome',
      dependencies: ['setup'],
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        storageState: 'e2e/.auth/user.json',
      },
    },
  ],

  /**
   * Playwright owns the dev server for the run.
   *
   * The API, broker and ingest pipeline are expected to be up already - start
   * them with `scripts/dev.ps1`. Only Vite is managed here, because it is the
   * one process whose lifetime should match the test run rather than the
   * developer's session.
   *
   * `reuseExistingServer` means a console you already have open is used as-is
   * instead of failing on a port clash.
   */
  webServer: {
    command: 'npx vite --port 5173 --host 127.0.0.1',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 60_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
})
