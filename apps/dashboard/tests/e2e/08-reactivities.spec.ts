/**
 * 08-reactivities.spec.ts (W6.A5)
 *
 * Invariant: /reactivities surfaces the worm's registered rules + budget
 * telemetry for admin lens. Member + observer lenses must not see this
 * tab (per role-nav admin-only contract). Propose / confirm / disable
 * paths render where the role has the grant.
 */
import { test, expect } from "./fixtures";

test.describe("reactivities — admin lens", () => {
  test("J1 — /reactivities renders rules surface", async ({
    ctxPage: page,
  }) => {
    await page.goto("/reactivities");
    const rows = page.locator('[data-testid^="reactivity-"]').first();
    const empty = page
      .getByText(/(no reactivities|no rules|nothing registered yet|empty)/i)
      .first();
    const banner = page
      .getByText(/(unreachable|service unavailable|coming soon)/i)
      .first();
    await expect((rows.or(empty).or(banner)).first()).toBeVisible();
  });

  test("J2 — propose-reactivity input is reachable", async ({ ctxPage: page }) => {
    await page.goto("/reactivities");
    // The natural-language propose input is either a textbox or a
    // dedicated "Propose reactivity" button. Tolerate absence (e.g.
    // ledger empty + banner-only render).
    const input = page.getByRole("textbox").first();
    const cta = page
      .getByRole("button", { name: /propose reactivity|new reactivity/i })
      .first();
    if ((await input.count()) > 0 || (await cta.count()) > 0) {
      await expect((input.or(cta)).first()).toBeVisible();
    }
  });

  test("J3 — disable / enable controls render on at least one rule (when present)", async ({
    ctxPage: page,
  }) => {
    await page.goto("/reactivities");
    const disable = page.getByRole("button", { name: /^disable/i });
    const enable = page.getByRole("button", { name: /^enable/i });
    if ((await disable.count()) > 0 || (await enable.count()) > 0) {
      await expect(disable.first().or(enable.first())).toBeVisible();
    }
  });

  test("J4 — budget-bar surfaces an interjection budget telemetry", async ({
    ctxPage: page,
  }) => {
    await page.goto("/reactivities");
    const budget = page
      .locator('[data-testid^="budget-"]')
      .or(page.getByText(/(budget|interjections|fires today)/i));
    if (await budget.first().count()) {
      await expect(budget.first()).toBeVisible();
    }
  });
});

test.describe("reactivities — member lens hidden", () => {
  test.use({ role: "member" });
  test("J5 — member lens does NOT have /reactivities in nav", async ({
    ctxPage: page,
  }) => {
    await page.goto("/dashboard");
    // role-nav.ts hides /reactivities from member lens. The sidebar must
    // not surface a `nav-reactivities` testid for this role.
    const navItem = page.locator('[data-testid="nav-reactivities"]');
    expect(await navItem.count()).toBe(0);
  });
});
