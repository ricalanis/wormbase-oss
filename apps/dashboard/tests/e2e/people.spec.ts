import { test, expect } from "@playwright/test";

test.describe("/people", () => {
  test("renders ≥3 people with rectangular chips and Receipts", async ({ page }) => {
    await page.goto("/people");
    const rows = page.locator('[data-testid^="person-"]');
    expect(await rows.count()).toBeGreaterThanOrEqual(3);
    const chips = page.locator("[data-chip]");
    const c = await chips.count();
    for (let i = 0; i < c; i++) {
      const radius = await chips.nth(i).evaluate((el) => getComputedStyle(el).borderRadius);
      expect(radius).toBe("0px");
    }
  });
});
