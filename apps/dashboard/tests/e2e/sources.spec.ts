import { test, expect } from "@playwright/test";

test.describe("/sources", () => {
  test("renders ≥3 sources spanning ≥2 distinct provenance flows", async ({ page }) => {
    await page.goto("/sources");
    const rows = page.locator('[data-testid^="source-"]');
    expect(await rows.count()).toBeGreaterThanOrEqual(3);

    const flows = await page.locator("[data-flow]").evaluateAll((els) =>
      Array.from(new Set(els.map((e) => e.getAttribute("data-flow"))))
    );
    expect(flows.length).toBeGreaterThanOrEqual(2);
  });

  test("each source row has a Receipt", async ({ page }) => {
    await page.goto("/sources");
    const rows = page.locator('[data-testid^="source-"]');
    const count = await rows.count();
    for (let i = 0; i < count; i++) {
      await expect(rows.nth(i).locator("[data-receipt]")).toBeVisible();
    }
  });
});
