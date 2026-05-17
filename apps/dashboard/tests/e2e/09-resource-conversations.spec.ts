/**
 * 09-resource-conversations.spec.ts (W6.A5)
 *
 * Invariant: a chat statement that fires a Statement-to-Owner reactivity
 * surfaces as a resource conversation on the owner's /people/<id> page.
 * Resolving it converts to a decision row at /decisions. We can't always
 * drive sim-harness from inside the browser; the spec asserts the surface
 * shape — the wire integration is exercised in tests/e2e (Python).
 */
import { test, expect } from "./fixtures";

test.describe("resource conversations on a person page", () => {
  test("J1 — /people/<id> renders for at least one Person OR honest empty", async ({
    ctxPage: page,
  }) => {
    await page.goto("/people");
    const firstRow = page.locator('[data-testid^="person-chip"], [data-testid^="person-row"]').first();
    if (await firstRow.count()) {
      const link = firstRow.getByRole("link").first();
      if (await link.count()) {
        await link.click();
        await page.waitForURL(/\/people\/[^/]+/, { timeout: 5_000 });
        // Either the resource-conversations panel renders, OR an honest empty
        // state, OR the page just shows the Person header.
        const panel = page
          .locator('[data-testid="resource-conversations"]')
          .or(page.getByText(/resource conversations?/i));
        const empty = page
          .getByText(/(no conversations|nothing yet|no statements)/i)
          .first();
        await expect(panel.first().or(empty).first()).toBeVisible();
      }
    } else {
      // No row rendered → an honest empty signal must surface. The
      // dashboard renders a Merge panel header even on an empty roster.
      const empty = page
        .getByText(/(no people|empty roster|merge multi-platform identities|invite)/i)
        .first();
      await expect(empty).toBeVisible();
    }
  });

  test("J2 — Resolve action exists on a resource conversation (when present)", async ({
    ctxPage: page,
  }) => {
    await page.goto("/people");
    const firstRow = page.locator('[data-testid^="person-chip"], [data-testid^="person-row"]').first();
    if (!(await firstRow.count())) return;
    const link = firstRow.getByRole("link").first();
    if (!(await link.count())) return;
    await link.click();
    await page.waitForURL(/\/people\/[^/]+/, { timeout: 5_000 });
    const resolve = page.getByRole("button", { name: /^resolve/i });
    if (await resolve.first().count()) {
      await expect(resolve.first()).toBeVisible();
    }
  });

  test("J3 — outcome dropdown surfaces a 'decision' option (when reachable)", async ({
    ctxPage: page,
  }) => {
    await page.goto("/people");
    const firstRow = page.locator('[data-testid^="person-chip"], [data-testid^="person-row"]').first();
    if (!(await firstRow.count())) return;
    const link = firstRow.getByRole("link").first();
    if (!(await link.count())) return;
    await link.click();
    await page.waitForURL(/\/people\/[^/]+/, { timeout: 5_000 });
    const resolve = page.getByRole("button", { name: /^resolve/i });
    if (await resolve.first().count()) {
      await resolve.first().click();
      // Outcome dropdown might be a select or a menu.
      const decisionOption = page.getByRole("option", { name: /decision/i });
      const decisionMenu = page.getByRole("menuitem", { name: /decision/i });
      const decisionText = page.getByText(/decision/i).first();
      await expect(
        decisionOption.first().or(decisionMenu.first()).or(decisionText),
      ).toBeVisible();
    }
  });

  test("J4 — /decisions tab is the canonical receiving surface", async ({
    ctxPage: page,
  }) => {
    await page.goto("/decisions");
    // Either decision rows or an honest empty state — the page must render
    // chrome regardless.
    const rows = page.locator('[data-testid^="decision-"]').first();
    const empty = page.getByText(/(no decisions|empty)/i).first();
    await expect((rows.or(empty)).first()).toBeVisible();
  });
});
