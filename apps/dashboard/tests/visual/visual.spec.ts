/**
 * visual.spec.ts (W6.A5; canonical-seed dependency added W7.A6)
 *
 * Invariant: visible chrome of each high-traffic tab × each role lens × each
 * state (loaded / empty) does not drift more than the configured per-pixel
 * threshold (5%) between runs. CSS regressions, layout breaks, and silent
 * panes that sneak past component tests fail here.
 *
 * Storage: snapshots are kept under
 * `apps/dashboard/tests/visual/__snapshots__/<tab>--<role>--<state>.png`,
 * checked into git so CI diffs against a deterministic baseline.
 *
 * State variants:
 *   - `loaded`  — the dashboard's normal data state (whatever the harness
 *                  has seeded). This is the canonical "this is what users
 *                  see" snapshot.
 *   - `empty`   — the same tab with the test injecting a network override
 *                  that returns empty data. Catches "silent pane" regressions
 *                  the component tests miss because the empty branch isn't
 *                  rendered in the canonical preview state.
 *
 * Trim policy: 10 tabs × 4 roles × 2 states = 80 snapshots. The cut is the
 * tabs the demo arc walks across plus the role-aware delta surfaces.
 *
 * Canonical-seed dependency (W7.A6):
 *   This suite assumes the `baseworm` tenant has been seeded with the
 *   W7.A1 rich seed (`wormbase demo seed --reset-first --rich`) and,
 *   ideally, an `Install` row (`--install-from-env` when a Slack token
 *   is present in `.env`). Without an Install, every tab redirects to
 *   `/onboarding` and the baselines collapse to the onboarding chrome.
 *   Run `make visual-baselines` to regenerate against the canonical
 *   state in one command. See `tests/visual/README.md` for the full
 *   workflow.
 */
import { test, expect, plantTenantCookies, ROLE_LENSES, type RoleLens } from "../e2e/fixtures";

/** High-traffic tabs the demo arc + production daily use focuses on. */
const VISUAL_TABS: ReadonlyArray<{ href: string; slug: string }> = [
  { href: "/dashboard", slug: "dashboard" },
  { href: "/sources", slug: "sources" },
  { href: "/kpis", slug: "kpis" },
  { href: "/people", slug: "people" },
  { href: "/decisions", slug: "decisions" },
  { href: "/processes", slug: "processes" },
  { href: "/data-products", slug: "data-products" },
  { href: "/notebooks", slug: "notebooks" },
  { href: "/research", slug: "research" },
  { href: "/trace", slug: "trace" },
];

const STATES: ReadonlyArray<"loaded" | "empty"> = ["loaded", "empty"];

/**
 * Snap a single (tab, role, state) cell. Encapsulates the cookie planting,
 * the optional empty-state network mock, the navigation, and the screenshot
 * comparison.
 */
async function snap(
  page: import("@playwright/test").Page,
  context: import("@playwright/test").BrowserContext,
  baseUrl: string,
  href: string,
  slug: string,
  role: RoleLens,
  state: "loaded" | "empty",
): Promise<void> {
  await plantTenantCookies(context, baseUrl, { tenant: "baseworm", role });
  if (state === "empty") {
    // Force the dashboard's read accessors to return empty arrays for the
    // visual-regression empty-state cell. The route override matches every
    // /api/* read endpoint; writes are unaffected (visual specs don't write).
    await context.route(/\/api\/.*/, (route) => {
      const req = route.request();
      if (req.method() !== "GET") {
        return route.continue();
      }
      // Tolerate the tenant + ops/health endpoints — they must not be
      // forced empty (the page would render an honest red banner).
      const url = req.url();
      if (/\/api\/(tenant|v1\/ops\/health)\b/.test(url)) {
        return route.continue();
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });
  }
  const response = await page.goto(href, { waitUntil: "domcontentloaded" });
  // 5xx renders the production error boundary; we still snap that — it's a
  // valid visual state. 4xx (e.g. 401 on member trying admin tab) is also a
  // valid visual contract.
  if (response && response.status() >= 500) {
     
    console.warn(
      `[visual.spec] ${href} returned ${response.status()} — snap will record the error boundary.`,
    );
  }
  // Settle: wait for the layout to render. We wait for either the body or
  // the boundary copy; whichever lands first is the snapshot target.
  await page
    .waitForLoadState("networkidle", { timeout: 8_000 })
    .catch(() => {
      /* SSE polling can keep the network busy; tolerate */
    });
  // Disable animations + carets for byte-stable diffs.
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
        caret-color: transparent !important;
      }
    `,
  });
  // Snap the visible viewport (1440×900) rather than fullPage. Full-page
  // captures grow with the ledger and become unstable; the visible
  // viewport is the chrome users actually see and is dimensionally stable.
  await expect(page).toHaveScreenshot(`${slug}--${role}--${state}.png`, {
    fullPage: false,
    timeout: 15_000,
    // Mask known-volatile regions: timestamps, freshness pills, live
    // tickers. Identified by data-mask-volatile attribute on host components,
    // OR by class hooks that name the volatile copy.
    mask: [
      page.locator("[data-mask-volatile]"),
      page.locator("time, [data-testid='freshness-pill']"),
    ],
  });
}

for (const { href, slug } of VISUAL_TABS) {
  for (const role of ROLE_LENSES) {
    for (const state of STATES) {
      test(`visual ${slug} · ${role} · ${state}`, async ({
        page,
        context,
        baseURL,
      }) => {
        await snap(
          page,
          context,
          baseURL ?? "http://localhost:3000",
          href,
          slug,
          role,
          state,
        );
      });
    }
  }
}
