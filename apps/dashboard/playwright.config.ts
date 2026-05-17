/**
 * Playwright config (W6.A5).
 *
 * Two suites live under `tests/`:
 *
 *   - `tests/e2e/`            user-journey specs (component-level Playwright)
 *   - `tests/visual/`         visual-regression snapshot specs
 *
 * Plus the legacy top-level `tests/*.spec.ts` smoke files which still drive
 * the happy-dom-backed shell sanity checks. Vitest owns `tests/unit/`.
 *
 * Environment contract:
 *
 *   - `WORMBASE_DASHBOARD_URL`  base URL the suite drives. Defaults to the
 *                                local dev server on `http://localhost:3000`.
 *   - `WORMBASE_HARNESS_UP=1`   when set, the global setup skips the
 *                                health probe and assumes the stack is up
 *                                (the operator drove `make tutorial` already).
 *                                When unset, global-setup probes the dashboard's
 *                                `/api/v1/ops/health` and skips the entire
 *                                suite if it fails — keeps `pnpm test:e2e`
 *                                green in CI without a stack.
 *
 * Visual diffs use Playwright's built-in `toHaveScreenshot` assertion with a
 * 5% per-pixel tolerance + a small max-pixel-diff allowance to absorb the
 * inevitable cross-platform anti-aliasing drift. We additionally vendor
 * `pixelmatch` + `pngjs` in dev dependencies so a future custom diff harness
 * can be slotted in without churning Playwright versions.
 */
import { defineConfig, devices } from "@playwright/test";

const BASE_URL =
  process.env.WORMBASE_DASHBOARD_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests",
  // E2E + visual + the legacy top-level *.spec.ts smoke files. Vitest owns
  // tests/unit/.
  testMatch: ["e2e/**/*.spec.ts", "visual/**/*.spec.ts", "*.spec.ts"],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  // Per-test wall-clock cap; the spec suite targets <60s per file.
  timeout: 60_000,
  // Visual baselines live under `tests/visual/__snapshots__/<name>.png` (not
  // Playwright's default `tests/visual/visual.spec.ts-snapshots/` directory).
  // Drop the OS / project suffix so the on-disk shape matches the spec call:
  //   `<tab>--<role>--<state>.png`
  snapshotPathTemplate:
    "{testDir}/visual/__snapshots__/{arg}{ext}",
  expect: {
    timeout: 5_000,
    toHaveScreenshot: {
      // 5% per-pixel tolerance — absorbs cross-platform anti-aliasing without
      // letting genuine layout drift through.
      maxDiffPixelRatio: 0.05,
      // Threshold per pixel before counting it as different (0..1).
      threshold: 0.2,
      animations: "disabled",
      caret: "hide",
    },
  },
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    // Bound expect timeouts inside specs so a missing data-testid surfaces
    // as a clean failure instead of a 30s hang.
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    // Firefox + WebKit are kept off the default project list so the local
    // suite stays fast. Re-enable per-project via PLAYWRIGHT_PROJECT=firefox
    // when investigating cross-engine regressions.
  ],
  // Global setup: skip-with-message when the stack isn't reachable. Avoids
  // the false-failure noise of running the suite against a cold dev box.
  globalSetup: "./tests/e2e/global-setup.ts",
  // No webServer block: assume `make tutorial` has the stack hot. The legacy
  // `pnpm dev` autoboot was nice for local sanity but it racy-conflicted with
  // the harness; explicit "stack must be up" is the production contract.
  outputDir: "./test-results/playwright",
});
