import { test, expect } from "@playwright/test";

test.describe("/settings/channels", () => {
  test("renders dials for ≥8 channels", async ({ page }) => {
    await page.goto("/settings/channels");
    const dials = page.locator('[data-testid^="channel-dial-"]');
    expect(await dials.count()).toBeGreaterThanOrEqual(8);
  });

  test("changing a channel posts to /api/channels/talkativeness", async ({ page }) => {
    await page.goto("/settings/channels");
    const reqWait = page.waitForRequest(
      (r) =>
        r.url().includes("/api/channels/talkativeness") && r.method() === "POST"
    );
    await page.getByTestId("channel-ch_data-proactive").click();
    const req = await reqWait;
    expect(req.method()).toBe("POST");
  });
});
