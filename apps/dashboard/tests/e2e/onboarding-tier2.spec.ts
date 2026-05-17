import { test, expect } from "@playwright/test";

test.describe("/onboarding/tier2", () => {
  test("renders three sections, accept one def, then advance to tier3", async ({ page }) => {
    await page.goto("/onboarding/tier2");
    await expect(page.getByTestId("defs-section")).toBeVisible();
    await expect(page.getByTestId("talkativeness-section")).toBeVisible();
    await expect(page.getByTestId("governance-section")).toBeVisible();
    await page.getByTestId("confirm-Active-account").click();
    await expect(
      page.locator('[data-testid="business-def-Active-account"][data-status="accepted"]')
    ).toBeVisible();
    await page.getByTestId("next").click();
    await expect(page).toHaveURL(/\/onboarding\/tier3$/);
  });
});
