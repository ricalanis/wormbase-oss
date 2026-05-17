import { test, expect } from "@playwright/test";

test.describe("dashboard shell", () => {
  test("sidebar lists every primary route", async ({ page }) => {
    await page.goto("/dashboard");
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).toBeVisible();
    const targets = [
      "/dashboard",
      "/onboarding",
      "/sources",
      "/settings/channels",
      "/kpis",
      "/people",
      "/domains",
      "/trace",
      "/policies",
      "/activity",
    ];
    for (const t of targets) {
      const slug = t.replace(/\//g, "-").replace(/^-/, "");
      await expect(sidebar.getByTestId(`nav-${slug}`)).toBeVisible();
    }
  });

  test("body background is paper", async ({ page }) => {
    await page.goto("/dashboard");
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    // happy-dom returns rgb form
    expect(bg).toBe("rgb(250, 247, 240)");
  });

  test("top rule renders the tenant strip", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("top-rule")).toBeVisible();
    await expect(page.getByTestId("top-rule")).toContainText(/baseworm/);
  });
});
