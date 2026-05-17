import { test, expect } from "@playwright/test";

test.describe("/dashboard ramp gauges (live ledger)", () => {
  test("renders 6 gauges with the canonical labels", async ({ page }) => {
    await page.goto("/dashboard");
    const labels = ["Ontology", "Schema", "Business Definitions", "KPI Relational", "Conversational", "Operational"];
    for (const label of labels) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
  });

  test("each gauge has a Receipt with a non-empty hash", async ({ page }) => {
    await page.goto("/dashboard");
    const gauges = page.locator('[data-testid^="gauge-"]');
    const count = await gauges.count();
    expect(count).toBe(6);
    for (let i = 0; i < count; i++) {
      const r = gauges.nth(i).locator("[data-receipt]");
      await expect(r).toBeVisible();
      const hash = await r.getAttribute("data-full-hash");
      expect(hash?.length ?? 0).toBeGreaterThan(0);
    }
  });
});
