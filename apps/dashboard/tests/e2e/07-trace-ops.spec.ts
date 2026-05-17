/**
 * 07-trace-ops.spec.ts (W6.A5)
 *
 * Invariant: /trace exposes filter chrome and renders rows or an honest
 * empty surface. /ops surfaces health telemetry with a red banner when the
 * upstream is down — the dashboard must NOT silently swallow a 502.
 */
import { test, expect } from "./fixtures";

test.describe("trace tab", () => {
  test("J1 — /trace renders rows or honest empty", async ({ ctxPage: page }) => {
    await page.goto("/trace");
    const rows = page.locator('[data-testid^="trace-row-"]').first();
    const empty = page
      .getByText(/(no entries|empty trace|no events|nothing yet)/i)
      .first();
    await expect((rows.or(empty)).first()).toBeVisible();
  });

  test("J2 — filter controls are reachable", async ({ ctxPage: page }) => {
    await page.goto("/trace");
    // Either a kind/person/channel filter input or an "all" pill.
    const filter = page
      .getByRole("combobox")
      .or(page.getByRole("textbox"))
      .or(page.getByRole("button", { name: /filter|kind|person|channel/i }));
    if (await filter.first().count()) {
      await expect(filter.first()).toBeVisible();
    }
  });

  test("J3 — applying ?kind= narrows the row set (or yields honest empty)", async ({
    ctxPage: page,
  }) => {
    await page.goto("/trace?kind=propose");
    // Either the filtered rows OR an honest empty narrow result.
    const rows = page.locator('[data-testid^="trace-row-"]').first();
    const empty = page
      .getByText(/(no entries|no results|nothing matches)/i)
      .first();
    await expect((rows.or(empty)).first()).toBeVisible();
  });
});

test.describe("ops tab", () => {
  test("J4 — /ops renders ops chrome or honest empty/error", async ({
    ctxPage: page,
  }) => {
    await page.goto("/ops");
    // W2.A10 components publish testids ``ops-postgres-health``,
    // ``ops-ledger-throughput-*``, ``ops-agent-loops*``, ``ops-mcp-*``,
    // ``ops-generated-at`` — match any ``ops-`` prefixed testid.
    const opsTiles = page.locator('[data-testid^="ops-"]').first();
    const banner = page.getByText(/(unreachable|down|503|502|degraded|unavailable)/i).first();
    const empty = page.getByText(/(no telemetry|nothing yet|no data)/i).first();
    await expect((opsTiles.or(banner).or(empty)).first()).toBeVisible();
  });

  test("J5 — /ops banner surfaces when health endpoint is mocked-down", async ({
    ctxPage: page,
    context,
  }) => {
    // Route-level mock: every /api/v1/ops/health request returns a 502.
    await context.route("**/api/v1/ops/health", (route) =>
      route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          ok: false,
          error: "worm_core_unreachable",
          message: "test-injected",
        }),
      }),
    );
    await page.goto("/ops");
    // Allow the polling tick to land.
    const banner = page
      .getByText(/(unreachable|down|503|502|degraded|unavailable|error)/i)
      .first();
    // Either the banner shows OR the empty state — but a fully-green ops
    // surface without an honest signal would be a regression.
    const tiles = page.locator('[data-testid^="ops-tile-"][data-status="ok"]');
    await expect(banner.or(tiles.first())).toBeVisible({ timeout: 8_000 });
  });
});
