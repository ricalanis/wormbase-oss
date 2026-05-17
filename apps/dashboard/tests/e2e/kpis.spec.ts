import { test, expect } from "@playwright/test";

test.describe("/kpis", () => {
  test("renders the KPI tree with ≥7 nodes by default", async ({ page }) => {
    await page.goto("/kpis");
    await expect(page.getByTestId("kpi-tree")).toBeVisible();
    const nodes = page.locator('[data-testid^="kpi-node-"]');
    expect(await nodes.count()).toBeGreaterThanOrEqual(7);
  });

  test("low-confidence nodes carry data-conf=low", async ({ page }) => {
    await page.goto("/kpis");
    const lows = await page.locator('[data-conf="low"]').count();
    expect(lows).toBeGreaterThanOrEqual(1);
  });
});
