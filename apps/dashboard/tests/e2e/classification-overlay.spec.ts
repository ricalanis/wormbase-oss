import { test, expect } from "@playwright/test";

test.describe("classification overlay", () => {
  test("toggle adds [data-overlay] to body and persists across nav", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByTestId("classification-overlay-toggle").click();
    await expect(page.locator("body")).toHaveAttribute("data-overlay", "classification");
    await page.goto("/sources");
    await expect(page.locator("body")).toHaveAttribute("data-overlay", "classification");
  });

  test("toggling off removes the attribute", async ({ page }) => {
    await page.goto("/dashboard");
    const toggle = page.getByTestId("classification-overlay-toggle");
    await toggle.click();
    await expect(page.locator("body")).toHaveAttribute("data-overlay", "classification");
    await toggle.click();
    await expect(page.locator("body")).not.toHaveAttribute("data-overlay", "classification");
  });
});
