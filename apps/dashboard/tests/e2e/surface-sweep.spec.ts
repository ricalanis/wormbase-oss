import { test, expect } from "@playwright/test";

const SURFACES: Array<{ path: string; selector?: string; min?: number }> = [
  { path: "/", selector: "h1" },
  { path: "/onboarding", selector: '[data-testid="onboarding-progress"]' },
  { path: "/onboarding/tier2", selector: '[data-testid="defs-section"]' },
  { path: "/onboarding/tier3", selector: '[data-testid="add-source-form"]' },
  { path: "/dashboard", selector: '[data-testid="ramp-gauges"]' },
  { path: "/kpis", selector: '[data-testid="kpi-tree"]' },
  { path: "/trace", selector: '[data-testid="trace-stream"]', min: 20 },
  { path: "/people", selector: '[data-testid="people-table"]' },
  { path: "/domains", selector: '[data-testid="domains-table"]' },
  { path: "/sources", selector: '[data-testid="sources-list"]' },
  { path: "/policies", selector: '[data-testid="policies-list"]' },
  { path: "/settings/channels", selector: '[data-testid="channels-list"]' },
  { path: "/activity", selector: '[data-testid="conversations-feed"]' },
];

test.describe("end-to-end surface sweep", () => {
  for (const s of SURFACES) {
    test(`${s.path} renders`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      const resp = await page.goto(s.path);
      expect(resp?.status()).toBeLessThan(400);
      if (s.selector) await expect(page.locator(s.selector).first()).toBeVisible();
      expect(errors).toEqual([]);
    });
  }

  test("≥50 receipts across all surfaces (acceptance density)", async ({ page }) => {
    let total = 0;
    for (const s of SURFACES) {
      await page.goto(s.path);
      total += await page.locator("[data-receipt]").count();
    }
    expect(total).toBeGreaterThanOrEqual(50);
  });
});
