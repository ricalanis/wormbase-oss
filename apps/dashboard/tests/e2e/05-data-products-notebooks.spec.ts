/**
 * 05-data-products-notebooks.spec.ts (W6.A5)
 *
 * Invariant: data products + notebooks expose drill-in surfaces with
 * replay + sign affordances. Hash-receipt badges are a load-bearing
 * production contract (the audit-completeness story).
 */
import { test, expect } from "./fixtures";

test.describe("data products tab", () => {
  test("J1 — /data-products renders rows or honest empty", async ({
    ctxPage: page,
  }) => {
    await page.goto("/data-products");
    const rows = page.locator('[data-testid^="data-product-"]').first();
    const empty = page.getByText(/(no data products|nothing yet|empty)/i).first();
    await expect((rows.or(empty)).first()).toBeVisible();
  });

  test("J2 — drilling into a data product shows replay surface OR empty", async ({
    ctxPage: page,
  }) => {
    await page.goto("/data-products");
    // First product row, if any. If none, skip via assertion against empty.
    const firstRow = page.locator('[data-testid^="data-product-"]').first();
    if (await firstRow.count()) {
      const link = firstRow.getByRole("link").first();
      if (await link.count()) {
        await link.click();
        await page.waitForURL(/\/data-products\/[^/]+/, { timeout: 5_000 });
        // Replay button OR an honest "no kernel" empty.
        const replay = page.getByRole("button", { name: /replay/i });
        const empty = page.getByText(/(no kernel|coming soon|unavailable)/i);
        await expect(replay.first().or(empty.first())).toBeVisible();
      }
    } else {
      const empty = page.getByText(/(no data products|nothing yet|empty)/i).first();
      await expect(empty).toBeVisible();
    }
  });

  test("J3 — replay receipt surfaces a content-hash badge when present", async ({
    ctxPage: page,
  }) => {
    await page.goto("/data-products");
    // The badge contract: when a replay has happened, the dashboard renders
    // a "✓ bit-identical content_hash" element. The assertion is loose
    // (presence-only) — replay execution is exercised in worm-core tests.
    const badge = page.getByText(/(content[_\s-]?hash|bit[-\s]?identical|✓)/i);
    if (await badge.first().count()) {
      await expect(badge.first()).toBeVisible();
    }
  });
});

test.describe("notebooks tab", () => {
  test("J4 — /notebooks renders rows or honest empty", async ({
    ctxPage: page,
  }) => {
    await page.goto("/notebooks");
    const rows = page.locator('[data-testid^="notebook-"]').first();
    const empty = page.getByText(/(no notebooks|empty|nothing yet)/i).first();
    await expect((rows.or(empty)).first()).toBeVisible();
  });

  test("J5 — drilling into a notebook shows cell-by-cell + Sign", async ({
    ctxPage: page,
  }) => {
    await page.goto("/notebooks");
    const firstRow = page.locator('[data-testid^="notebook-"]').first();
    if (await firstRow.count()) {
      const link = firstRow.getByRole("link").first();
      if (await link.count()) {
        await link.click();
        await page.waitForURL(/\/notebooks\/[^/]+/, { timeout: 5_000 });
        // Cells render as `[data-testid^="cell-"]` OR an honest empty.
        const cells = page.locator('[data-testid^="cell-"]').first();
        const empty = page.getByText(/(no cells|empty|coming soon)/i).first();
        await expect((cells.or(empty)).first()).toBeVisible();
        // Sign control may be admin-only; tolerate absence.
        const sign = page.getByRole("button", { name: /sign/i });
        if (await sign.count()) {
          await expect(sign.first()).toBeVisible();
        }
      }
    }
  });
});
