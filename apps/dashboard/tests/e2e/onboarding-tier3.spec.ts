import { test, expect } from "@playwright/test";

test.describe("/onboarding/tier3", () => {
  test("renders all four panels and finishes to /dashboard", async ({ page }) => {
    await page.goto("/onboarding/tier3");
    await expect(page.getByTestId("pii-rules-panel")).toBeVisible();
    await expect(page.getByTestId("dm-routing-panel")).toBeVisible();
    await expect(page.getByTestId("ontology-seeds-panel")).toBeVisible();
    await expect(page.getByTestId("add-source-form")).toBeVisible();
    await page.getByTestId("finish").click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });
});
