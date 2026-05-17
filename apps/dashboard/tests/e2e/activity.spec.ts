import { test, expect } from "@playwright/test";

test.describe("/activity", () => {
  test("renders all three sections (conversations / tasks / insights)", async ({ page }) => {
    await page.goto("/activity");
    await expect(page.getByTestId("conversations-feed")).toBeVisible();
    await expect(page.getByTestId("tasks-panel")).toBeVisible();
    await expect(page.getByTestId("insights-panel")).toBeVisible();
  });

  test("dismissing an insight removes it from view", async ({ page }) => {
    await page.goto("/activity");
    const cards = page.locator('[data-testid^="insight-"][data-testid$="ins_1"]');
    const before = await page.locator('[data-testid^="insight-"]:not([data-testid*="dismiss"]):not([data-testid*="act"]):not([data-testid*="schedule"])').count();
    await page.getByTestId("insight-dismiss-ins_1").click();
    const after = await page.locator('[data-testid^="insight-"]:not([data-testid*="dismiss"]):not([data-testid*="act"]):not([data-testid*="schedule"])').count();
    expect(after).toBeLessThan(before);
  });
});
