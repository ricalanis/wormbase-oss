import { test, expect } from "@playwright/test";

test.describe("/policies", () => {
  test("renders the 3 PRD §4.6 must-have policies", async ({ page }) => {
    await page.goto("/policies");
    for (const id of ["pii_redaction", "warmup_required", "interjection_budget"]) {
      await expect(page.getByTestId(`policy-${id}`)).toBeVisible();
    }
  });
});
