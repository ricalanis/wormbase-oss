import { test, expect } from "@playwright/test";

test.describe("/trace", () => {
  test("shows ≥20 entries with all four quadrant colors", async ({ page }) => {
    await page.goto("/trace");
    const rows = page.locator('[data-testid^="trace-row-"]');
    expect(await rows.count()).toBeGreaterThanOrEqual(20);
    const quadrants = await page.locator("[data-quadrant]").evaluateAll((els) =>
      Array.from(new Set(els.map((e) => e.getAttribute("data-quadrant"))))
    );
    for (const q of ["propose", "execute", "verify", "resolve"]) {
      expect(quadrants).toContain(q);
    }
  });

  test("clicking a row toggles the detail block", async ({ page }) => {
    await page.goto("/trace");
    const first = page.locator('[data-testid^="trace-row-"]').first();
    const rowId = await first.getAttribute("data-testid");
    const id = rowId!.replace("trace-row-", "");
    await page.locator(`[data-testid='trace-toggle-${id}']`).click();
    await expect(page.locator(`[data-testid='trace-detail-${id}']`)).toBeVisible();
  });
});
